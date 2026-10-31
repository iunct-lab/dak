
import os
import shutil
import tempfile
import unittest
from dak_agent.skill_registry import SkillRegistry

class TestSkillRegistryStandard(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.registry = SkillRegistry([self.test_dir])

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_load_skill_md(self):
        # Create a skill directory
        skill_dir = os.path.join(self.test_dir, "standard_skill")
        os.makedirs(skill_dir)
        
        # Create SKILL.md with frontmatter
        skill_md_content = """---
name: standard_skill
description: A skill defined using SKILL.md
tools:
  - some_tool
---
# Standard Skill Instructions

This is a standard skill.
"""
        with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
            f.write(skill_md_content)

        # Try to load skills
        self.registry.load_skills()

        # Check if the skill was loaded
        # Currently expected to fail (be empty) because SKILL.md is not supported
        self.assertIn("standard_skill", self.registry.skills)
        skill = self.registry.skills["standard_skill"]
        self.assertEqual(skill["name"], "standard_skill")
        self.assertEqual(skill["description"], "A skill defined using SKILL.md")
        self.assertIn("some_tool", skill["tools"])
        self.assertIn("This is a standard skill.", skill["instructions"])

if __name__ == "__main__":
    unittest.main()
