"""Validated incident schema. Model output must parse into this or it is rejected."""
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Built-in categories (the platform defaults). A tenant profile may define its own category names.
DEFAULT_CATEGORIES = ("mechanical_vibration", "leak", "overheating", "electrical_fault", "noise",
                      "performance_degradation", "other")


class Citation(BaseModel):
    marker: int
    chunk_id: str
    document_id: str
    filename: str
    version: int
    page_number: int | None = None
    record_id: str | None = None
    quote: str


class RelatedIncident(BaseModel):
    record_id: str | None
    summary: str
    filename: str
    chunk_id: str
    same_asset: bool


class IncidentDraft(BaseModel):
    tenant_id: uuid.UUID
    asset_id: str = Field(pattern=r"^[A-Z0-9][A-Z0-9-]{1,19}$")
    asset_verified: bool
    category: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")
    symptoms: list[str] = Field(min_length=1)
    related_incidents: list[RelatedIncident] = []
    priority: Literal["P1", "P2", "P3", "P4"]
    citations: list[Citation] = []
    recommended_action: str = Field(min_length=10)
    review_status: Literal["pending_review", "needs_review"] = "pending_review"
    notes: list[str] = []


class SimulationClaim(BaseModel):
    """Simulator provenance claim; accepted only with a valid server-keyed signature (app.ai.measurement_trust)."""
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=1, max_length=40)
    signature: str = Field(pattern="^[0-9a-f]{64}$")


class StructuredObservation(BaseModel):
    """Typed observation from the authenticated submitter; there is no tenant field on purpose."""
    model_config = ConfigDict(extra="forbid")
    asset_id: str = Field(min_length=2, max_length=40)
    measurement_type: Literal["vibration", "brake_pressure", "coolant_temperature"]
    value: float
    unit: str = Field(min_length=1, max_length=12)
    observed_at: str | None = Field(default=None, max_length=40)
    source: str | None = Field(default=None, max_length=80)
    simulation: SimulationClaim | None = None


class MeasurementVerification(BaseModel):
    """Human verification decision; the expected status guards against stale or repeated decisions."""
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject"]
    comment: str = Field(min_length=10, max_length=500)
    expected_trust_status: Literal["UNVERIFIED", "VALIDATED"]


class ExtractRequest(BaseModel):
    report_text: str = Field(min_length=10, max_length=4000)
    observations: list[StructuredObservation] = Field(default_factory=list, max_length=20)
    numeric_locale: Literal["en", "de"] | None = None
