# Note on this run

Quality and latency results here are valid (first complete real-AI run, kept as a repeat measurement).

**The `ollama_working_set_mb_peak` values in `results.json` are INVALID**: the sampler only matched the `ollama` launcher processes, not the `llama-server` process that holds the model (about 1.4 GB working set when measured separately). The sampler was fixed afterwards; use the later run for memory figures.
