"""The root ops.config.json is in the shared kit's shape (run: `uv run --no-project --with pytest pytest scripts -q`)."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _config():
    return json.loads((ROOT / "ops.config.json").read_text(encoding="utf-8"))


def test_ops_config_has_the_kit_shape():
    config = _config()

    assert set(config) == {"envPrefix", "fields", "milestone", "sections", "storyPoints", "publicSync"}
    assert set(config["fields"]) == {"area", "kind", "priority", "phase"}
    assert config["envPrefix"] == "DAK"
    assert "projectUrl" not in config  # the private Project's URL comes from the variable DAK_PROJECT_URL, not from the public tree


def test_public_sync_targets_the_public_repository():
    sync = _config()["publicSync"]

    assert set(sync) == {"target", "exclude", "rewrite"}
    assert sync["target"] == "iunct-lab/dak"
    for rel in sync["exclude"] + sync["rewrite"]:
        assert (ROOT / rel).exists(), rel


def test_area_labels_are_options_of_the_area_field():
    labels = re.findall(r'name: "area:([^"]+)"', (ROOT / ".github/labels.yml").read_text(encoding="utf-8"))

    assert labels
    assert set(labels) <= set(_config()["fields"]["area"])


def test_phase_options_are_the_milestone_phases():
    phases = _config()["fields"]["phase"]

    assert phases == [f"Phase {n}" for n in range(5)]  # Milestones are "Phase 1 — …" … "Phase 4 — …"; Phase 0 is the groundwork
