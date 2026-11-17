"""Tenant profile: everything domain-specific about a customer, as validated configuration.

A tenant is onboarded by creating it (API), adding connectors and members (API), then PUTting a profile and
uploading documents (API). No shared code changes per customer. Absent a profile, the platform falls back to
its original built-in equipment-maintenance defaults (app/ai/rules.py), which existing tenants keep using.

Safety notes:
  * Keywords are matched as plain substrings. The only tenant-supplied regular expressions are the asset ID
    pattern and numeric-signal patterns; they are length-limited, must compile, and nested quantifiers (the
    classic catastrophic-backtracking shape) are rejected. They only ever run on <= 4000-char reports.
  * Priority is decided only by the deterministic rules below, never by a model.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

NAME = r"^[a-z][a-z0-9_]{1,40}$"
KIND = r"^[a-z][a-z0-9_]{1,40}$"
Priority = Literal["P1", "P2", "P3", "P4"]
_NESTED_QUANTIFIER = re.compile(r"\([^()]*[+*][^()]*\)\s*[+*{]")


def _safe_regex(pattern: str, groups: int) -> str:
    if len(pattern) > 200:
        raise ValueError("regex longer than 200 characters")
    if _NESTED_QUANTIFIER.search(pattern):
        raise ValueError("nested quantifiers are not allowed")
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"invalid regex: {exc}") from exc
    if compiled.groups != groups:
        raise ValueError(f"regex must contain exactly {groups} capture group(s)")
    return pattern


class Category(BaseModel):
    name: str = Field(pattern=NAME)
    keywords: list[str] = Field(min_length=1, max_length=30)
    description: str = Field(default="", max_length=300)  # guidance for the language model


class Symptom(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    keywords: list[str] = Field(min_length=1, max_length=30)


class Signal(BaseModel):
    """A numeric reading to extract from a report (for example brake pressure in psi)."""
    name: str = Field(pattern=NAME)
    regex: str
    unit: str = Field(default="", max_length=12)

    @field_validator("regex")
    @classmethod
    def _regex(cls, value: str) -> str:
        return _safe_regex(value, 1)


class Condition(BaseModel):
    """Exactly one of: safety flag, a signal threshold (gte/lte), or a category membership."""
    flag: Literal["safety"] | None = None
    signal: str | None = None
    gte: float | None = None
    lte: float | None = None
    category_in: list[str] | None = None

    @model_validator(mode="after")
    def _one_kind(self):
        kinds = [self.flag is not None, self.signal is not None, self.category_in is not None]
        if sum(kinds) != 1:
            raise ValueError("a condition needs exactly one of: flag, signal, category_in")
        if self.signal is not None and (self.gte is None) == (self.lte is None):
            raise ValueError("a signal condition needs exactly one of gte / lte")
        return self


class PriorityRule(BaseModel):
    priority: Priority
    any: list[Condition] = Field(min_length=1)


class Enrichment(BaseModel):
    """Read-only lookup against a tenant connector, rendered into incident notes (never decides priority)."""
    label: str = Field(min_length=2, max_length=60)
    connector_kind: Literal["inventory", "crm", "fleet", "rest"]
    path: str = Field(pattern=r"^/[A-Za-z0-9_\-/{}.]*\{asset_id\}[A-Za-z0-9_\-/{}.]*$", max_length=120)
    template: str = Field(min_length=3, max_length=300)  # {field} placeholders from the JSON response
    required_fields: list[str] = Field(default_factory=list, max_length=10)


class KindMapping(BaseModel):
    """Maps a customer's CSV/JSON layout onto the platform for one document kind."""
    id_field: str | None = Field(default=None, max_length=60)
    columns: dict[str, str] = Field(default_factory=dict, max_length=40)


class TenantProfile(BaseModel):
    asset_label: str = Field(default="equipment", min_length=3, max_length=30)
    asset_id_pattern: str
    register_kind: str = Field(pattern=KIND)
    guidance_kinds: list[str] = Field(min_length=1, max_length=8)
    history_kind: str | None = Field(default=None, pattern=KIND)
    document_kinds: list[str] = Field(default_factory=list, max_length=16)
    categories: list[Category] = Field(min_length=1, max_length=20)
    symptoms: list[Symptom] = Field(default_factory=list, max_length=30)
    signals: list[Signal] = Field(default_factory=list, max_length=8)
    safety_keywords: list[str] = Field(default_factory=list, max_length=20)
    priority_rules: list[PriorityRule] = Field(min_length=1, max_length=20)
    default_priority: Priority = "P4"
    enrichments: list[Enrichment] = Field(default_factory=list, max_length=6)
    field_maps: dict[str, KindMapping] = Field(default_factory=dict, max_length=16)

    @field_validator("asset_id_pattern")
    @classmethod
    def _asset_pattern(cls, value: str) -> str:
        return _safe_regex(value, 1)

    @field_validator("document_kinds", "guidance_kinds")
    @classmethod
    def _kinds(cls, values: list[str]) -> list[str]:
        for value in values:
            if not re.match(KIND, value):
                raise ValueError(f"invalid document kind '{value}'")
        return values

    @model_validator(mode="after")
    def _consistency(self):
        names = [c.name for c in self.categories]
        if len(set(names)) != len(names) or "other" in names:
            raise ValueError("category names must be unique and 'other' is implicit")
        signals = [s.name for s in self.signals]
        if len(set(signals)) != len(signals):
            raise ValueError("signal names must be unique")
        for rule in self.priority_rules:
            for cond in rule.any:
                if cond.signal is not None and cond.signal not in signals:
                    raise ValueError(f"priority rule references unknown signal '{cond.signal}'")
                if cond.category_in is not None and not set(cond.category_in) <= set(names):
                    raise ValueError("priority rule references an unknown category")
        return self

    def allowed_kinds(self) -> set[str]:
        kinds = set(self.document_kinds) | set(self.guidance_kinds) | {self.register_kind}
        return kinds | ({self.history_kind} if self.history_kind else set())
