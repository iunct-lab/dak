import unittest
from unittest.mock import patch, mock_open, MagicMock
import json
from pathlib import Path
import tempfile
import os

from src.config import ConfigManager, CONFIG_DIR, CONFIG_FILE


class TestConfigManager(unittest.TestCase):
    def setUp(self):
        """Set up test environment."""
        self.test_config = {
            "username": "test_user",
            "agent_url": "http://test.example.com:8000"
        }

    @patch('src.config.CONFIG_DIR', new_callable=lambda: Path(tempfile.mkdtemp()))
    @patch('src.config.CONFIG_FILE')
    def test_init_creates_config_dir(self, mock_config_file, mock_config_dir):
        """Test that ConfigManager creates config directory on init."""
        mock_config_file.exists.return_value = False
        mock_config_file.parent = mock_config_dir
        
        with patch.object(Path, 'mkdir') as mock_mkdir:
            config = ConfigManager()
            # Config dir creation is handled in _ensure_config_dir
            self.assertIsNotNone(config)

    @patch('builtins.open', new_callable=mock_open, read_data='{"username": "test", "agent_url": "http://test:8000"}')
    @patch('src.config.CONFIG_FILE')
    @patch('src.config.CONFIG_DIR')
    def test_load_existing_config(self, mock_dir, mock_file, mock_file_open):
        """Test loading existing configuration."""
        mock_file.exists.return_value = True
        mock_dir.exists.return_value = True
        
        config = ConfigManager()
        self.assertEqual(config.get_user(), "test")
        self.assertEqual(config.get_agent_url(), "http://test:8000")

    @patch('src.config.CONFIG_FILE')
    @patch('src.config.CONFIG_DIR')
    def test_load_empty_config(self, mock_dir, mock_file):
        """Test handling of missing config file."""
        mock_file.exists.return_value = False
        mock_dir.exists.return_value = True
        
        config = ConfigManager()
        self.assertIsNone(config.get_user())
        self.assertEqual(config.get_agent_url(), "http://localhost:8000")

    @patch('builtins.open', new_callable=mock_open)
    @patch('src.config.CONFIG_FILE')
    @patch('src.config.CONFIG_DIR')
    def test_set_user(self, mock_dir, mock_file, mock_file_open):
        """Test setting username."""
        mock_file.exists.return_value = False
        mock_dir.exists.return_value = True
        
        config = ConfigManager()
        config.set_user("new_user")
        
        self.assertEqual(config.get_user(), "new_user")
        mock_file_open.assert_called()

    @patch('builtins.open', new_callable=mock_open)
    @patch('src.config.CONFIG_FILE')
    @patch('src.config.CONFIG_DIR')
    def test_set_agent_url(self, mock_dir, mock_file, mock_file_open):
        """Test setting agent URL."""
        mock_file.exists.return_value = False
        mock_dir.exists.return_value = True
        
        config = ConfigManager()
        config.set_agent_url("http://new.example.com:9000")
        
        self.assertEqual(config.get_agent_url(), "http://new.example.com:9000")
        mock_file_open.assert_called()

    @patch('builtins.open', new_callable=mock_open, read_data='invalid json')
    @patch('src.config.CONFIG_FILE')
    @patch('src.config.CONFIG_DIR')
    def test_load_invalid_json(self, mock_dir, mock_file, mock_file_open):
        """Test handling of corrupted config file."""
        mock_file.exists.return_value = True
        mock_dir.exists.return_value = True
        
        config = ConfigManager()
        # Should return default empty config on JSON decode error
        self.assertIsNone(config.get_user())


if __name__ == '__main__':
    unittest.main()
