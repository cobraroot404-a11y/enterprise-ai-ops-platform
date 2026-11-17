"""Explicitly download the pinned embedding model into the project cache (the only place that downloads).

Run: python scripts/fetch_models.py     (about 92 MB; Apache-2.0; needs requirements-ai.txt installed)
The app itself loads the model offline (local_files_only), so nothing downloads implicitly.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from huggingface_hub import snapshot_download  # noqa: E402

from app.core.config import MINILM_MODEL, MINILM_REVISION, get_settings  # noqa: E402

FILES = ["model.safetensors", "config.json", "tokenizer.json", "tokenizer_config.json", "vocab.txt",
         "special_tokens_map.json", "modules.json", "sentence_bert_config.json",
         "config_sentence_transformers.json", "1_Pooling/config.json"]


def main() -> None:
    path = snapshot_download(MINILM_MODEL, revision=MINILM_REVISION, cache_dir=get_settings().model_cache_dir,
                             allow_patterns=FILES)
    print(f"{MINILM_MODEL}@{MINILM_REVISION} -> {path}")


if __name__ == "__main__":
    main()
