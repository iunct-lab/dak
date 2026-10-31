"""The test stack's agent serves no development API (DAK_DEV_API is cleared in docker-compose.test.yml, #729)."""
import httpx
import pytest

from conftest import AGENT_URL


@pytest.mark.parametrize("path", ["/dev-ui/", "/dev/apps/dak_agent/tests", "/openapi.json", "/docs", "/redoc"])
def test_dev_api_is_404(path):
    assert httpx.get(f"{AGENT_URL}{path}").status_code == 404


def test_agent_api_still_answers():
    assert httpx.get(f"{AGENT_URL}/list-apps").status_code == 200
