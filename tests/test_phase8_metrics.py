"""Hand-calculated checks of the Phase 8 metric functions."""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluation.phase8 import metrics as m  # noqa: E402


def test_recall_precision_with_multiple_relevant_passages():
    ranked = ["a", "x", "b", "y", "z", "c"]
    rel = {"a", "b", "c"}
    assert m.recall_at_k(ranked, rel, 1) == pytest.approx(1 / 3)
    assert m.recall_at_k(ranked, rel, 3) == pytest.approx(2 / 3)
    assert m.recall_at_k(ranked, rel, 5) == pytest.approx(2 / 3)  # c is at rank 6
    assert m.recall_at_k(ranked, rel, 10) == 1.0
    assert m.precision_at_k(ranked, rel, 5) == pytest.approx(2 / 5)
    assert m.precision_ceiling(3, 5) == 0.6 and m.precision_ceiling(8, 5) == 1.0


def test_duplicates_count_once_at_best_rank():
    assert m.dedupe(["a", "a", "b", "a"]) == ["a", "b"]
    assert m.recall_at_k(["a", "a", "a", "b"], {"a", "b"}, 2) == 1.0


def test_undefined_metrics_are_none_not_zero_or_one():
    assert m.recall_at_k(["a"], set(), 5) is None and m.reciprocal_rank(["a"], set()) is None
    assert m.ndcg_at_k(["a"], {}, 5) is None and m.rate(0, 0) is None and m.wilson(0, 0) is None


def test_mrr_depth_and_miss():
    assert m.reciprocal_rank(["x", "y", "b"], {"b"}) == pytest.approx(1 / 3)
    assert m.reciprocal_rank(["x", "y"], {"b"}) == 0.0
    beyond = [f"n{i}" for i in range(10)] + ["b"]
    assert m.reciprocal_rank(beyond, {"b"}, depth=10) == 0.0


def test_graded_ndcg_hand_calculation():
    grades = {"e": 2, "s": 1}  # essential gain 3, supporting gain 1
    ranked = ["s", "n", "e"]
    dcg = 1 / math.log2(2) + 0 + 3 / math.log2(4)
    idcg = 3 / math.log2(2) + 1 / math.log2(3)
    assert m.ndcg_at_k(ranked, grades, 5) == pytest.approx(dcg / idcg)
    assert m.ndcg_at_k(["e", "s"], grades, 5) == pytest.approx(1.0)


def test_wilson_interval_known_values():
    lo, hi = m.wilson(93, 100)
    assert lo == pytest.approx(0.8627, abs=1e-3) and hi == pytest.approx(0.9657, abs=1e-3)
    lo, hi = m.wilson(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-3)


def test_target_classification_never_overstates():
    met = m.proportion_report(97, 100, 0.95)
    assert met["classification"] == "OBSERVED TARGET MET" and met["interval_vs_target"] == "interval overlaps target"
    assert m.proportion_report(90, 100, 0.95)["classification"] == "OBSERVED TARGET NOT MET"
    assert m.proportion_report(0, 0, 0.95)["classification"] == "NOT EVALUABLE"
    assert m.proportion_report(990, 1000, 0.95)["interval_vs_target"] == "interval entirely above target"


def test_bootstrap_is_deterministic_and_brackets_the_mean():
    vals = [1, 0, 1, 1, 0, 1, 1, 1, 0, 1]
    a, b = m.bootstrap_mean_ci(vals, resamples=2000), m.bootstrap_mean_ci(vals, resamples=2000)
    assert a == b and a[0] <= 0.7 <= a[1]
    assert m.bootstrap_mean_ci([]) is None


def test_percentiles():
    assert m.percentile([1, 2, 3, 4, 5], 0.5) == 3 and m.percentile([1, 2, 3, 4], 0.5) == 2.5
    assert m.percentile([], 0.5) is None


def test_mcnemar_exact_hand_calculation():
    assert m.mcnemar_exact(0, 0) is None
    assert m.mcnemar_exact(8, 0) == pytest.approx(2 * (1 / 256))      # 8 improved, 0 regressed: p = 2 * 0.5^8
    assert m.mcnemar_exact(3, 3) == 1.0 and m.mcnemar_exact(10, 6) == pytest.approx(0.4545, abs=1e-3)


def test_paired_bootstrap_difference():
    out = m.paired_bootstrap_diff([0.0, 0.5, 1.0, None], [0.5, 1.0, 1.0, 0.2], resamples=2000)
    assert out["n"] == 3 and out["mean_diff"] == pytest.approx((0.5 + 0.5 + 0.0) / 3) and out["ci95"][0] <= out["mean_diff"] <= out["ci95"][1]
    assert m.paired_bootstrap_diff([None], [1.0]) is None
