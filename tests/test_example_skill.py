import unittest
from pathlib import Path

from mcp_to_skills.config import load_config, parse_yaml_subset


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "examples" / "blender-project" / ".agents" / "skills" / "blender"


class ExampleSkillTests(unittest.TestCase):
    def test_skill_frontmatter_and_mcp_config_names_match_directory(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        _, frontmatter, body = text.split("---", 2)
        metadata = parse_yaml_subset(frontmatter)
        self.assertEqual(metadata["name"], SKILL.name)
        self.assertIsInstance(metadata.get("description"), str)
        self.assertTrue(metadata["description"].strip())
        self.assertTrue(body.strip())
        config = load_config(SKILL / "mcp.yaml", expected_name=SKILL.name)
        self.assertEqual(config.lifecycle_mode, "session")

    def test_skill_has_no_unfinished_template_tokens(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        for token in ("TODO", "<REPO_ROOT>", "skill-name", "PLACEHOLDER"):
            self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()

