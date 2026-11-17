"""Pure metric functions for the Phase 8 evaluation (formulas: docs/evaluation/phase8-metric-definitions.md).

No I/O and no model calls, so every function is unit-tested against hand-calculated values.
Undefined metrics (zero denominator) return None and are reported as N/A, never as a pass.
"""
import math
import random
from collections.abc import Sequence


def dedupe(ranked: Sequence) -> list:
    """A passage counts once, at its best (first) rank."""
    seen, out = set(), []
    for item in ranked:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def recall_at_k(ranked: Sequence, relevant: set, k: int) -> float | None:
    if not relevant:
        return None
    return len(set(dedupe(ranked)[:k]) & relevant) / len(relevant)


def precision_at_k(ranked: Sequence, relevant: set, k: int) -> float | None:
    if not relevant:
        return None
    return len(set(dedupe(ranked)[:k]) & relevant) / k


def precision_ceiling(n_relevant: int, k: int) -> float:
    return min(1.0, n_relevant / k)


def reciprocal_rank(ranked: Sequence, relevant: set, depth: int = 10) -> float | None:
    if not relevant:
        return None
    for i, item in enumerate(dedupe(ranked)[:depth], 1):
        if item in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: Sequence, grades: dict, k: int) -> float | None:
    """Graded nDCG: gain = 2^grade - 1, discount = log2(rank + 1), normalised by the ideal ordering of the labelled passages."""
    if not grades or not any(g > 0 for g in grades.values()):
        return None

    def gain(g):
        return (2 ** g) - 1

    dcg = sum(gain(grades.get(item, 0)) / math.log2(i + 1) for i, item in enumerate(dedupe(ranked)[:k], 1))
    ideal = sorted(grades.values(), reverse=True)[:k]
    idcg = sum(gain(g) / math.log2(i + 1) for i, g in enumerate(ideal, 1))
    return dcg / idcg


def rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def wilson(successes: int, n: int, z: float = 1.959964) -> tuple[float, float] | None:
    """95% Wilson score interval for a proportion; None when n == 0."""
    if n == 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def proportion_report(successes: int, n: int, target: float | None = None) -> dict:
    """Numerator, denominator, percentage, Wilson interval and the observed-target classification.

    A confidence interval that overlaps the target does not demonstrate equivalence; `interval_vs_target` states the relation only.
    """
    out = {"numerator": successes, "denominator": n, "value": rate(successes, n), "wilson95": wilson(successes, n)}
    if target is not None:
        if n == 0:
            out["classification"], out["interval_vs_target"] = "NOT EVALUABLE", "n/a"
        else:
            lo, hi = out["wilson95"]
            out["classification"] = "OBSERVED TARGET MET" if successes / n >= target else "OBSERVED TARGET NOT MET"
            out["interval_vs_target"] = ("interval entirely above target" if lo >= target
                                         else "interval entirely below target" if hi < target else "interval overlaps target")
    return out


def bootstrap_mean_ci(values: Sequence[float], resamples: int = 10000, seed: int = 20261111) -> tuple[float, float] | None:
    """Percentile bootstrap over queries (query-level metrics). Repeated model runs are never pooled as extra queries."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    rng = random.Random(seed)
    n = len(vals)
    means = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    return means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]


def mean(values: Sequence[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    pos = (len(s) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def mcnemar_exact(improved: int, regressed: int) -> float | None:
    """Exact two-sided McNemar p-value from the discordant pairs (improved / regressed); None when there are no discordant pairs."""
    n = improved + regressed
    if n == 0:
        return None
    k = min(improved, regressed)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def paired_bootstrap_diff(base: Sequence[float | None], cand: Sequence[float | None], resamples: int = 10000, seed: int = 20261111) -> dict | None:
    """Mean paired difference (candidate - baseline) over queries with a percentile bootstrap interval; queries undefined in either run are dropped."""
    pairs = [(b, c) for b, c in zip(base, cand, strict=True) if b is not None and c is not None]
    if not pairs:
        return None
    diffs = [c - b for b, c in pairs]
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    return {"n": n, "mean_diff": sum(diffs) / n, "ci95": [means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]]}
