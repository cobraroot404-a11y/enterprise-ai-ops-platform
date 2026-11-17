"""Part 6, 24 and 25 deliverables: the documents exist, say what they must say, and do not claim what did not happen.

These are structural and honesty checks, not a review of the prose. They guard against drift (the requirements matrix is regenerated and compared) and against over-claiming (nothing
may say a cloud deployment, a container build or a real customer interview happened)."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DELIVERY = ["01-customer-discovery-summary", "02-requirements-to-solution-matrix", "03-solution-architecture-proposal", "04-integration-specification", "05-deployment-plan",
            "06-customer-acceptance-plan", "07-troubleshooting-guide", "08-operational-handover", "09-architecture-tradeoff-record", "10-implementation-retrospective"]
DISCOVERY_HEADINGS = ["Business background", "Current workflow", "Pain points", "Stakeholders", "Existing systems", "Data sources", "Security constraints", "Deployment constraints",
                      "Success criteria", "Assumptions", "Open questions"]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_customer_discovery_documents_cover_every_required_heading_and_say_they_are_fictional():
    for name in ("apex-industrial", "meridian-fleet"):
        text = read(f"docs/customer-discovery/{name}.md")
        assert "FICTIONAL" in text.splitlines()[0].upper() and "fictional" in text.lower() and "No real" in text
        for heading in DISCOVERY_HEADINGS:
            assert re.search(rf"^## {heading}", text, re.M), (name, heading)
    assert "fictional" in read("docs/customer-discovery/README.md").lower()


def test_the_ten_customer_delivery_documents_and_the_walkthrough_exist():
    for stem in DELIVERY:
        assert (ROOT / "docs" / "customer-delivery" / f"{stem}.md").stat().st_size > 400, stem
    walk = read("docs/customer-delivery/technical-walkthrough.md")
    for topic in ("Customer problem", "Requirements", "Architecture", "Integrations", "Security", "Workflow automation", "Failure recovery", "Measured outcomes", "Deployment tradeoffs"):
        assert topic in walk, topic
    assert "Do not say" in walk


def test_the_requirements_matrix_is_current_and_maps_every_catalogue_requirement():
    committed = read("docs/customer-delivery/02-requirements-to-solution-matrix.md")
    sys.path.insert(0, str(ROOT / "scripts"))
    import traceability_data as t
    for r in t.REQUIREMENTS:
        assert f"| {r['id']} |" in committed, r["id"]
    before = committed
    subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_solution_matrix.py")], check=True, capture_output=True)
    assert read("docs/customer-delivery/02-requirements-to-solution-matrix.md") == before  # regenerating changes nothing: run the generator after changing the catalogue
    assert all(col in committed for col in ("Technical implementation", "Test cases", "Acceptance criterion", "Evidence", "Customer need"))


def test_cloud_and_infrastructure_documents_do_not_claim_a_deployment_or_validation_that_did_not_happen():
    cloud = read("docs/architecture/cloud-portability.md")
    assert "No cloud resource was provisioned" in cloud and "AWS" in cloud and "Azure" in cloud and "Google Cloud" in cloud
    for topic in ("Compute", "Database", "Storage", "Networking", "Identity", "Secrets", "Observability", "Scaling", "Availability", "Security", "Cost"):
        assert topic in cloud, topic
    assert "Monolith or microservices" in read("docs/architecture/deployment-tradeoffs.md")
    tf = read("infrastructure/terraform/README.md")
    assert "No cloud resource was provisioned" in tf
    assert "terraform fmt" in tf and "terraform validate" in tf and "terraform init -backend=false" in tf
    assert (ROOT / "evaluation" / "terraform" / "fmt-check.txt").exists()
    assert "evaluation/terraform/provider-validation.md" in tf
    evidence = read("evaluation/terraform/provider-validation.md")
    assert "Success! The configuration is valid." in evidence and "Exact SHA-256 match before installation" in evidence
    assert "`terraform providers schema -json` | Exit 0." in evidence
    assert "No remote backend, state files, plan, apply, destroy, cloud API calls, or cloud resource changes." in evidence
    for rel in ("versions.tf", "variables.tf", "outputs.tf", "main.tf", "terraform.tfvars.example"):
        assert (ROOT / "infrastructure" / "terraform" / rel).exists(), rel
    text = "\n".join(read(f"docs/customer-delivery/{s}.md") for s in DELIVERY) + cloud
    for banned in ("successfully deployed", "deployed to AWS", "deployed to Azure", "deployed to production", "customer interviews were conducted", "production-ready", "fully compliant"):
        assert banned not in text, banned


def test_diagrams_and_the_deployment_runbook_exist_and_state_their_scope():
    diagrams = read("docs/architecture/diagrams.md")
    assert diagrams.count("```mermaid") >= 5
    runbook = read("docs/operations/deployment-runbook.md")
    assert "local" in runbook.lower() and "shared `eaop` database" in runbook


def test_the_container_stack_is_defined_without_baked_secrets_and_its_smoke_evidence_exists():
    compose = read("docker-compose.app.yml")
    for service in ("db:", "migrate:", "seed:", "api:", "worker:", "ticketing:", "inventory:", "fleet:", "crm:", "servicedesk:", "ui:"):
        assert f"\n  {service}" in compose, service
    assert "name: eaop-app" in compose and "app_pgdata" in compose and "EMBEDDING_BACKEND: deterministic" in compose  # its own project, own volume, labelled test-only AI
    assert "127.0.0.1:${EAOP_APP_API_PORT" in compose and "ports:\n      - \"5432" not in compose  # published on loopback only; the database has no host port
    for rel in ("infrastructure/docker/Dockerfile.backend", "infrastructure/docker/Dockerfile.frontend"):
        text = read(rel)
        assert ".env" not in text.replace(".env is excluded", "").replace("never from the image", "") or "COPY .env" not in text
        assert "COPY .env" not in text and "ENV POSTGRES_PASSWORD" not in text and "ENV JWT_SECRET" not in text
    assert ".env" in read(".dockerignore").splitlines()
    assert "USER eaop" in read("infrastructure/docker/Dockerfile.backend")
    reports = sorted((ROOT / "evaluation" / "container-smoke").glob("*/report.md"))
    assert reports and "PASSED" in reports[-1].read_text(encoding="utf-8").splitlines()[0]
