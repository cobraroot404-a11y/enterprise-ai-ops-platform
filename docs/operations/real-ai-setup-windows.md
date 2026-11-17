# Real local AI setup (Windows, CPU only)

Tested on Windows 11, Intel i7-1165G7, 15.7 GB RAM, no discrete GPU, Python 3.10.

## 1. Ollama (official)
- Installer: https://ollama.com/download (OllamaSetup.exe). Tested: version 0.40.16, 1,771.6 MB, SHA-256 `84DB4F756DDC9E091142A85CDC0F7AE5DB68BC9B3E075F114388B326F8ED912D`, Authenticode signature valid (Ollama Inc.).
- Per-user install, no administrator needed; about 3.1 GB on disk. The installer adds Ollama to the user PATH and runs a background server on `127.0.0.1:11434`.
- Model: `ollama pull qwen2.5:1.5b` (986,061,892 bytes, Q4_K_M, Apache-2.0). Tested digest `65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b`.

## 2. Python dependencies (inside the project venv, never global)
```bash
python -m venv .venv
.venv\Scripts\pip install -r backend/requirements.lock.txt     # exact tested versions (Windows, CPython 3.10)
```
If an old bundled pip cannot verify TLS certificates (for example behind HTTPS-scanning antivirus), install with a newer global pip: `python -m pip --python .venv\Scripts\python.exe install -r backend/requirements.lock.txt`. Do not disable certificate verification.

The PyPI `torch` wheel on Windows is the CPU-only build (`torch.version.cuda` is `None`); no CUDA libraries are installed. `requirements-ai.txt` lists the direct AI dependency; `requirements.lock.txt` pins the full tested set.

## 3. Embedding model (pinned)
`python scripts/fetch_models.py` downloads `sentence-transformers/all-MiniLM-L6-v2` at commit `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` (safetensors weights and tokenizer files only, about 92 MB, Apache-2.0) into `data/models/` (git-ignored). The application loads it offline (`local_files_only`), so nothing downloads implicitly.

## 4. Switch a tenant to the real backends
1. `.env`: `LLM_BACKEND=ollama`, `EMBEDDING_BACKEND=sentence_transformers`.
2. Existing tenants hold deterministic test vectors and are refused by the real embedder (HTTP 409 `embedding_model_mismatch`) until re-embedded: `python scripts/reindex_embeddings.py --tenant apex-industrial --backend sentence_transformers --report evaluation/reports/phase3/reindex-apex.json`.
3. The reindex is atomic, keeps provenance and tenant isolation, verifies counts and 384 dimensions, rebuilds the HNSW index and runs a retrieval self-check.

Expected memory: Ollama about 1.5-2.5 GB while the model is loaded, MiniLM plus PyTorch about 0.5-1 GB (measured values are in the run's `results.json` under `resources`).
