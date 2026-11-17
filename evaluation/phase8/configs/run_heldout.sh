#!/bin/bash
# The single approved held-out evaluation: unchanged baseline first, then the frozen candidate, same split, same environment, 3 repetitions each.
cd "$(dirname "$0")/../../.."
PY=.venv/Scripts/python.exe
CAND="$(cat evaluation/phase8/configs/candidate_v1.json)"
echo "== BASELINE_TEST $(date -u +%Y-%m-%dT%H:%M:%SZ)"
$PY evaluation/phase8/run_experiment.py --id HELDOUT-BASELINE --tuning '{}' --split test --allow-heldout --phases retrieval,qa,extraction,workflow --reps 3 > /tmp/heldout_baseline.log 2>&1; tail -1 /tmp/heldout_baseline.log
echo "== CANDIDATE_TEST $(date -u +%Y-%m-%dT%H:%M:%SZ)"
$PY evaluation/phase8/run_experiment.py --id HELDOUT-CANDIDATE --tuning "$CAND" --split test --allow-heldout --phases retrieval,qa,extraction,workflow --reps 3 > /tmp/heldout_candidate.log 2>&1; tail -1 /tmp/heldout_candidate.log
echo HELDOUT_DONE
