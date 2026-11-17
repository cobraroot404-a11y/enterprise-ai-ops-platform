"""V41-24.06 (optional Kubernetes examples) and the optional monitoring example: parsed and checked as TEXT. Nothing was applied to a cluster or loaded by Prometheus."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
K8S_TEXT = (ROOT / "infrastructure" / "kubernetes" / "eaop.yaml").read_text(encoding="utf-8")
K8S = list(yaml.safe_load_all(K8S_TEXT))
SENSITIVE = re.compile(r"PASSWORD|SECRET|KEY|TOKEN", re.I)


def pods() -> list[tuple[str, dict]]:
    return [(doc["metadata"]["name"], doc["spec"]["template"]["spec"]) for doc in K8S if (doc.get("spec") or {}).get("template", {}).get("spec")]


def test_the_expected_kinds_exist_in_one_namespace():
    kinds = [d["kind"] for d in K8S]
    assert kinds.count("Deployment") == 3 and kinds.count("Service") == 2 and {"Namespace", "ConfigMap", "Job"} <= set(kinds)
    assert {d["metadata"].get("namespace", "eaop") for d in K8S} == {"eaop"}
    assert "Secret" not in kinds  # secrets are created by the operator, never committed


def test_no_secret_value_is_written_in_the_manifests():
    config = next(d for d in K8S if d["kind"] == "ConfigMap")["data"]
    assert not any(SENSITIVE.search(k) for k in config)
    for _, spec in pods():
        for container in spec["containers"]:
            assert not any(SENSITIVE.search(e["name"]) and "value" in e for e in container.get("env", []))
            assert {"secretRef": {"name": "eaop-secrets"}} in container.get("envFrom", []) or container["name"] == "ui"


def test_containers_follow_basic_hardening_and_have_resource_limits():
    for name, spec in pods():
        assert not spec.get("hostNetwork") and not spec.get("hostPID")
        for container in spec["containers"]:
            assert container["resources"]["limits"] and container["resources"]["requests"], name
            assert not container.get("securityContext", {}).get("privileged")
            if container["name"] != "ui":  # the backend image runs as uid 10001; the nginx image keeps its own user
                security = container["securityContext"]
                assert security["runAsNonRoot"] is True and security["allowPrivilegeEscalation"] is False and security["capabilities"] == {"drop": ["ALL"]}


def test_the_examples_say_they_were_never_applied_and_claim_no_cloud_deployment():
    assert "NEVER applied to a cluster" in K8S_TEXT and "Nothing here claims a cloud deployment" in K8S_TEXT
    monitoring = (ROOT / "infrastructure" / "monitoring" / "prometheus.yml").read_text(encoding="utf-8")
    assert "never loaded by a Prometheus server" in monitoring
    scrape = yaml.safe_load(monitoring)["scrape_configs"][0]
    assert scrape["metrics_path"] == "/metrics" and "credentials_file" in scrape["authorization"] and "credentials" not in scrape["authorization"]


def test_replicas_greater_than_one_are_only_used_where_state_is_shared():
    replicas = {d["metadata"]["name"]: d["spec"]["replicas"] for d in K8S if d["kind"] == "Deployment"}
    assert replicas == {"api": 2, "worker": 2, "ui": 1}  # safe for api and worker because limits and metrics live in PostgreSQL and jobs use fenced leases
