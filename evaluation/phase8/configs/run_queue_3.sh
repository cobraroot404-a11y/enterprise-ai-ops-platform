#!/bin/bash
# Third dev-split queue: citation completion (C3) on top of the accepted abstention configuration, with and without quote snapping (E7).
cd "$(dirname "$0")/../../.."
PY=.venv/Scripts/python.exe
run() { id="$1"; tuning="$2"; phases="$3"; echo "== $id $tuning $phases $(date -u +%H:%M)"; $PY evaluation/phase8/run_experiment.py --id "$id" --tuning "$tuning" --phases "$phases" --reps 1 > "/tmp/q_$id.log" 2>&1; tail -1 "/tmp/q_$id.log"; }
B='"entity_boost": 0.02, "entity_gate": true, "query_override_gate": true'
run C3    "{$B, \"claim_completion\": true}" qa
run C3E7  "{$B, \"claim_completion\": true, \"quote_snap\": true}" qa
echo QUEUE_DONE
