
import os
import unittest
from dak_agent.skill_registry import SkillRegistry

class TestRealSkillsLoading(unittest.TestCase):
    def test_load_real_skills(self):
        # Point to the real agent/skills and provider_skills directories
        current_dir = os.path.dirname(__file__)
        skills_dir = os.path.abspath(os.path.join(current_dir, "../..", "skills"))
        provider_skills_dir = os.path.abspath(os.path.join(current_dir, "../..", "provider_skills"))
        
        # SkillRegistry expects List[str], not a single string
        registry = SkillRegistry([skills_dir, provider_skills_dir])
        registry.load_skills()
        
        # Verify filesystem skill (in agent/skills/)
        self.assertIn("filesystem", registry.skills)
        self.assertEqual(registry.skills["filesystem"]["name"], "filesystem")
        self.assertIn("list_files", registry.skills["filesystem"]["tools"])
        
        # Verify premium_service skill (in agent/provider_skills/)
        self.assertIn("premium_service", registry.skills)
        self.assertEqual(registry.skills["premium_service"]["name"], "premium_service")
        
        # Verify solana_wallet skill (in agent/skills/)
        self.assertIn("solana_wallet", registry.skills)
        self.assertEqual(registry.skills["solana_wallet"]["name"], "solana_wallet")

if __name__ == "__main__":
    unittest.main()
