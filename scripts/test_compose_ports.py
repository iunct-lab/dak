"""Every published port in the compose files is bound to loopback, and the development API is off by default
(run: `uv run --no-project --with pytest pytest scripts -q`)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = sorted([*ROOT.glob("docker-compose*.yml"), *ROOT.glob("compose/*/*.yml")])  # compose/test/: scripts/compose_files.sh


def _published_ports(text: str) -> list[str]:
    ports, in_ports, indent = [], False, 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "ports:":
            in_ports, indent = True, len(line) - len(line.lstrip())
            continue
        if in_ports:
            if stripped.startswith("- "):
                ports.append(stripped[2:].split("#")[0].strip().strip('"\''))
            elif stripped and not stripped.startswith("#") and len(line) - len(line.lstrip()) <= indent:
                in_ports = False
    return ports


def test_compose_files_are_found():
    assert COMPOSE


def test_feature_compose_files_are_checked():
    assert ROOT / "compose/test/web-search.yml" in COMPOSE


def test_every_published_port_is_bound_to_loopback():
    for path in COMPOSE:
        for port in _published_ports(path.read_text(encoding="utf-8")):
            assert re.match(r"127\.0\.0\.1:\d+:\d+", port), f"{path.name}: {port} is not bound to 127.0.0.1"


def test_development_api_is_off_in_the_default_compose():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert not re.search(r"DAK_DEV_API=1", text)
