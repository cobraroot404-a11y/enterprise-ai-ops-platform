#!/bin/bash
# Second dev-split queue: follow-ups motivated by the first queue (query-override gate, asset-context guidance, determinism and noise floor).
cd "$(dirname "$0")/../../.."
PY=.venv/Scripts/python.exe
run() { id="$1"; tuning="$2"; phases="$3"; echo "== $id $tuning $phases $(date -u +%H:%M)"; $PY evaluation/phase8/run_experiment.py --id "$id" --tuning "$tuning" --phases "$phases" --reps 1 > "/tmp/q_$id.log" 2>&1; tail -1 "/tmp/q_$id.log"; }
B='"entity_boost": 0.02'
run E10d  "{$B, \"guidance_query\": \"asset_context\"}" extraction
run E10e  "{$B, \"numeric_verification\": true, \"guidance_query\": \"asset_context\"}" extraction
run E8b   "{$B, \"entity_gate\": true, \"query_override_gate\": true}" qa
run RSTAR2 "{$B}" qa
run DET1  "{$B, \"stable_ranking\": true}" qa
run DET2  "{$B, \"stable_ranking\": true}" qa
echo QUEUE_DONE
