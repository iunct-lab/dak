import json
import os
from pathlib import Path
from typing import Optional, Dict

CONFIG_DIR = Path.home() / ".dak-cli"
CONFIG_FILE = CONFIG_DIR / "config.json"

class ConfigManager:
    def __init__(self):
        self._ensure_config_dir()
        self.config = self._load_config()

    def _ensure_config_dir(self):
        if not CONFIG_DIR.exists():
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    def _load_config(self) -> Dict:
        if not CONFIG_FILE.exists():
            return {}
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}

    def save_config(self):
        with open(CONFIG_FILE, "w") as f:
            json.dump(self.config, f, indent=2)

    def set_user(self, username: str):
        self.config["username"] = username
        self.save_config()

    def get_user(self) -> Optional[str]:
        return self.config.get("username")

    def set_agent_url(self, url: str):
        self.config["agent_url"] = url
        self.save_config()

    def get_agent_url(self) -> str:
        # DAK_AGENT_URL overrides the stored config (used by tests/CI and headless runs)
        env_url = os.getenv("DAK_AGENT_URL")
        if env_url:
            return env_url
        return self.config.get("agent_url", "http://localhost:8000")
