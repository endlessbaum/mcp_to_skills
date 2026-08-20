import os
import tempfile
import unittest
from pathlib import Path

from mcp_to_skills.config import ConfigError, find_config, load_config, parse_yaml_subset


class ConfigTests(unittest.TestCase):
    def test_parses_generated_shape(self):
        data = parse_yaml_subset(
            """name: blender
transport: stdio
command: uvx
args:
  - blender-mcp
lifecycle:
  mode: session
  idle_timeout: 600
"""
        )
        self.assertEqual(data["args"], ["blender-mcp"])
        self.assertEqual(data["lifecycle"]["idle_timeout"], 600)

    def test_loads_relative_cwd_and_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mcp.yaml"
            path.write_text("name: demo\ncommand: python\ncwd: work\n", encoding="utf-8")
            config = load_config(path)
            self.assertEqual(config.idle_timeout, 600)
            self.assertEqual(config.discovery_timeout, 1.5)
            self.assertEqual(config.lifecycle_mode, "on-demand")
            self.assertEqual(config.cwd, str((Path(directory) / "work").resolve()))

    def test_rejects_non_stdio_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mcp.yaml"
            path.write_text("name: demo\ntransport: http\ncommand: demo\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_finds_config_colocated_with_project_skill_from_nested_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            skill = root / ".agents" / "skills" / "blender"
            skill.mkdir(parents=True)
            config = skill / "mcp.yaml"
            config.write_text("name: blender\ncommand: uvx\n", encoding="utf-8")
            nested = root / "src" / "feature"
            nested.mkdir(parents=True)
            previous = Path.cwd()
            try:
                os.chdir(str(nested))
                self.assertEqual(find_config("blender"), config.resolve())
            finally:
                os.chdir(str(previous))


if __name__ == "__main__":
    unittest.main()
