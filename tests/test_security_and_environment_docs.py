"""Final deliverable 21 (security documentation) and the Part 34 environment verification: the index references only files that exist, keeps open defects and partial requirements
visible, and the environment record covers the eleven listed items without recording private details."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "docs" / "security" / "README.md").read_text(encoding="utf-8")
ENV = json.loads((ROOT / "evaluation" / "environment" / "verification.json").read_text(encoding="utf-8"))
ENV_TEXT = (ROOT / "evaluation" / "environment" / "verification.json").read_text(encoding="utf-8") + (ROOT / "evaluation" / "environment" / "verification.md").read_text(encoding="utf-8")


def test_every_file_the_security_index_names_exists():
    for path in re.findall(r"`((?:backend|scripts|tests)/[^`]+)`", INDEX):
        assert (ROOT / path).exists(), path
    for target in re.findall(r"\]\(([^)#]+)\)", INDEX):
        assert ((ROOT / "docs" / "security") / target).resolve().exists(), target


def test_the_index_covers_the_controls_the_specification_lists_and_hides_nothing_open():
    for control in ("Tenant isolation", "Authentication", "Authorization", "Secrets", "Input and upload restrictions", "Rate and concurrency limits", "Audit", "Prompt-injection",
                    "Connector egress", "Webhook authentication", "Numeric trust boundary", "Git provenance"):
        assert control in INDEX, control
    assert "V41-14.02 is **Partial**" in INDEX and "PROV-01 is open" in INDEX and "## Not covered" in INDEX
    assert "No independent penetration test" in INDEX


def test_the_environment_record_covers_the_eleven_items():
    for key in ("git", "github_authentication", "git_identity", "python", "node", "docker", "cpu", "ram_gb", "gpu", "disk", "local_model_compatibility"):
        assert ENV.get(key) not in (None, "", {}), key
    assert ENV["git"]["remotes_configured"] == 0 and ENV["git_identity"]["author_name_is_owner"] is True
    assert ENV["gpu"]["cuda_capable"] is False and ENV["local_model_compatibility"]["ram_sufficient_for_model"] is True


def test_the_environment_record_holds_no_private_detail():
    assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}", ENV_TEXT)  # no e-mail address
    assert not re.search(r"gh[pousr]_[A-Za-z0-9]{20,}|Bearer ", ENV_TEXT)  # no token
    assert ENV["git_identity"]["email"] == "not recorded (private)"
