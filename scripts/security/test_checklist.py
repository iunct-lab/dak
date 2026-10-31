"""The security review checklist is the single source of the items a reviewer
(or an LLM) must look at. Run: `uv run --no-project --with pytest pytest scripts -q`."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKLIST = ROOT / "docs" / "security" / "review-checklist.md"
HEADING = "## LLM が見る項目"


def checklist_items():
    """The bullet items under HEADING (up to the next heading)."""
    lines = CHECKLIST.read_text(encoding="utf-8").splitlines()
    start = lines.index(HEADING) + 1
    items = []
    for line in lines[start:]:
        if line.startswith("#"):
            break
        if line.startswith("- "):
            items.append(line[2:].strip())
    return items


def test_checklist_has_items():
    items = checklist_items()
    assert len(items) >= 6
    assert all(items)


def test_claude_md_points_to_the_checklist():
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "docs/security/review-checklist.md" in text
