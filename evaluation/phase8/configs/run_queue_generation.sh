#!/bin/bash
# Sequential dev-split generation / extraction experiments on top of the accepted retrieval configuration R* = {"entity_boost": 0.02}.
# One run at a time (CPU-only machine; latency is measured). Logs: /tmp/q_<id>.log
cd "$(dirname "$0")/../../.."
PY=.venv/Scripts/python.exe
run() { id="$1"; tuning="$2"; phases="$3"; echo "== $id $tuning $phases $(date -u +%H:%M)"; $PY evaluation/phase8/run_experiment.py --id "$id" --tuning "$tuning" --phases "$phases" --reps 1 > "/tmp/q_$id.log" 2>&1; tail -1 "/tmp/q_$id.log"; }
B='"entity_boost": 0.02'
run RSTAR   "{$B}" retrieval,qa,extraction
run C1      "{$B, \"citation_marker_formats\": true}" qa
run E7      "{$B, \"quote_snap\": true}" qa
run E8      "{$B, \"entity_gate\": true}" qa
run E5a     "{$B, \"context_diverse\": true}" qa
run E5b     "{$B, \"context_diverse\": true, \"context_k\": 6}" qa
run E6v4    "{$B, \"prompt_variant\": \"4\"}" qa
run E6v5    "{$B, \"prompt_variant\": \"5\"}" qa
run E6v6    "{$B, \"prompt_variant\": \"6\"}" qa
run E10a    "{$B, \"numeric_verification\": true}" extraction
run E10b    "{$B, \"category_cross_check\": true}" extraction
run E10c    "{$B, \"guidance_query\": \"model_category\"}" extraction
run E10all  "{$B, \"numeric_verification\": true, \"category_cross_check\": true, \"guidance_query\": \"model_category\"}" extraction
echo QUEUE_DONE
