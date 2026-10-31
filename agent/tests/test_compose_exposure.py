"""The default compose publishes every service on the loopback (#731, #932).

mcp-server has no auth (run_command, file tools), the agent and the BFF have none either, and the DB
holds the conversation history, so the default stack publishes them on 127.0.0.1 only
and takes the DB password from .env instead of a value written in the repo.
docs/quickstart.md uses them through localhost. These checks read repo-root files and skip when agent/ is
tested on its own (e.g. copied out of the monorepo).
"""

import glob
import os
import re
import unittest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _read(test: unittest.TestCase, relpath: str) -> str:
    path = os.path.join(_REPO_ROOT, relpath)
    if not os.path.exists(path):
        test.skipTest(f"{relpath} not available (not a repo checkout)")
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestDefaultComposeExposure(unittest.TestCase):
    def setUp(self):
        self.compose = _read(self, "docker-compose.yml")

    def test_mcp_server_and_postgres_publish_on_loopback_only(self):
        self.assertRegex(self.compose, r'(?m)^\s*-\s*"127\.0\.0\.1:8001:8000"')
        self.assertRegex(self.compose, r'(?m)^\s*-\s*"127\.0\.0\.1:5432:5432"')
        self.assertNotRegex(self.compose, r'(?m)^\s*-\s*"(8001:8000|5432:5432)"')

    def test_agent_and_bff_publish_on_loopback_only(self):
        self.assertRegex(self.compose, r'(?m)^\s*-\s*"127\.0\.0\.1:8000:8000"')
        self.assertRegex(self.compose, r'(?m)^\s*-\s*"127\.0\.0\.1:8002:8000"')
        self.assertNotRegex(self.compose, r'(?m)^\s*-\s*"(8000:8000|8002:8000)"')

    def test_demo_keeps_mcp_server_and_postgres_on_loopback(self):
        demo = _read(self, "docker-compose.demo.yml")
        self.assertRegex(demo, r'(?m)^\s*-\s*"127\.0\.0\.1:8000:8000"')
        self.assertRegex(demo, r'(?m)^\s*-\s*"127\.0\.0\.1:5432:5432"')
        self.assertNotRegex(demo, r'(?m)^\s*-\s*"(8000:8000|5432:5432)"')

    def test_db_password_comes_from_env(self):
        # compose/test/: the features' test services (scripts/compose_files.sh)
        features = sorted(glob.glob("compose/*/*.yml", root_dir=_REPO_ROOT))
        self.assertIn("compose/test/ap2.yml", features)
        for relpath in ("docker-compose.yml", "docker-compose.test.yml", "docker-compose.demo.yml", *features):
            text = _read(self, relpath)
            self.assertNotIn(":password@", text, relpath)
            self.assertNotRegex(text, r"POSTGRES_PASSWORD\s*[=:]\s*password\b", relpath)
        # No fallback value: without .env the stack stops and says how to make one
        self.assertRegex(
            self.compose,
            r"POSTGRES_PASSWORD=\$\{POSTGRES_PASSWORD:\?[^}$]*openssl rand -hex 32\}",
        )


class TestEnvExampleLeavesPasswordEmpty(unittest.TestCase):
    def test_postgres_password_line_is_empty(self):
        text = _read(self, "env.example.d/00-postgres.env")
        self.assertRegex(text, r"(?m)^POSTGRES_PASSWORD=$")
        self.assertIn("openssl rand -hex 32", text)


if __name__ == "__main__":
    unittest.main()
