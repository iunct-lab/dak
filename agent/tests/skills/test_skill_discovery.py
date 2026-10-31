
import os
import shutil
import tempfile
import unittest
from dak_agent.skill_registry import SkillRegistry

class TestSkillDiscovery(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.registry = SkillRegistry([self.test_dir])

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_load_standard_skill_md(self):
        """Test loading a standard skill defined in SKILL.md"""
        skill_dir = os.path.join(self.test_dir, "standard_skill")
        os.makedirs(skill_dir)
        
        skill_md_content = """---
name: standard_skill_explicit
description: A standard skill
tools:
  - tool_a
---
# Instructions
Do standard things.
"""
        with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
            f.write(skill_md_content)

        self.registry.load_skills()
        
        self.assertIn("standard_skill_explicit", self.registry.skills)
        skill = self.registry.skills["standard_skill_explicit"]
        self.assertEqual(skill["description"], "A standard skill")
        self.assertEqual(skill["tools"], ["tool_a"])
        self.assertIn("# Instructions", skill["instructions"])

    def test_load_standard_skill_implicit_name(self):
        """Test loading a standard skill where name is inferred from directory"""
        skill_dir = os.path.join(self.test_dir, "implicit_name_skill")
        os.makedirs(skill_dir)
        
        skill_md_content = """---
description: Implicit name skill
tools: []
---
Instructions
"""
        with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
            f.write(skill_md_content)

        self.registry.load_skills()
        
        self.assertIn("implicit_name_skill", self.registry.skills)

    def test_ignore_other_md_files(self):
        """Test that other .md files are ignored"""
        skill_dir = os.path.join(self.test_dir, "ignored_skill")
        os.makedirs(skill_dir)
        
        md_content = """---
name: ignored_skill
description: Should be ignored
tools: []
---
Instructions
"""
        with open(os.path.join(skill_dir, "other.md"), "w") as f:
            f.write(md_content)

        self.registry.load_skills()
        
        self.assertNotIn("ignored_skill", self.registry.skills)

    def test_legacy_yaml_ignored(self):
        """Test that legacy YAML files are ignored"""
        skill_dir = os.path.join(self.test_dir, "legacy_skill")
        os.makedirs(skill_dir)
        
        yaml_content = """
name: legacy_skill
description: Legacy YAML skill
tools: []
instructions: Legacy instructions
"""
        with open(os.path.join(skill_dir, "skill.yaml"), "w") as f:
            f.write(yaml_content)

        self.registry.load_skills()
        
        self.assertNotIn("legacy_skill", self.registry.skills)

if __name__ == "__main__":
    unittest.main()
