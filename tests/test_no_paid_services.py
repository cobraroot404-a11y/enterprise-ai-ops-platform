"""V41-02.04 and Definition of done 2: no paid service is mandatory. Scans dependency, container, compose and workflow files for paid-API SDKs and endpoints,
and for settings that would activate one. A static check: it cannot prove a service is never reached at runtime, only that nothing in the repository requires one."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [*ROOT.glob("backend/requirements*.txt"), ROOT / "frontend" / "package.json", *ROOT.glob("docker-compose*.yml"), *ROOT.glob("infrastructure/docker/Dockerfile*"),
         ROOT / ".github" / "workflows" / "ci.yml", ROOT / ".env.example"]
PAID_PACKAGES = ["openai", "anthropic", "cohere", "google-generativeai", "google-cloud-aiplatform", "boto3", "azure-ai", "mistralai", "pinecone", "weaviate-client", "datadog", "newrelic",
                 "sentry-sdk", "twilio", "stripe", "sendgrid", "langsmith"]
PAID_ENDPOINTS = ["api.openai.com", "api.anthropic.com", "amazonaws.com", "openai.azure.com", "generativelanguage.googleapis.com", "api.cohere", "pinecone.io", "datadoghq.com"]
KEY_SETTINGS = re.compile(r"^\s*(OPENAI|ANTHROPIC|COHERE|AWS|AZURE|GOOGLE|PINECONE|DATADOG)[A-Z_]*\s*=\s*\S", re.MULTILINE)


def test_the_scanned_file_set_is_not_empty():
    assert len(FILES) >= 8 and all(f.exists() for f in FILES)


def test_no_paid_sdk_in_any_dependency_file():
    for f in FILES:
        if f.suffix == ".txt" or f.name == "package.json":
            text = f.read_text(encoding="utf-8").lower()
            for pkg in PAID_PACKAGES:
                assert not re.search(rf'(^|["\s]){re.escape(pkg)}([<>=\[~^"\s]|$)', text, re.MULTILINE), f"{f.name}: {pkg}"


def test_no_paid_endpoint_or_credential_setting_in_infrastructure_files():
    for f in FILES:
        text = f.read_text(encoding="utf-8")
        for endpoint in PAID_ENDPOINTS:
            assert endpoint not in text, f"{f.name}: {endpoint}"
        assert not KEY_SETTINGS.search(text), f"{f.name}: a paid-provider key setting has a value"


def test_the_ai_runtime_setting_names_a_local_backend():
    env = (ROOT / ".env.example").read_text(encoding="utf-8").lower()
    assert "llm_backend" in env and "ollama" in env
