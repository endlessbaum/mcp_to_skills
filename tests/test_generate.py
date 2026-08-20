import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mcp_to_skills.config import load_config


ROOT = Path(__file__).resolve().parents[1]
FAKE_SERVER = ROOT / "tests" / "fake_mcp_server.py"


class GenerateIntegrationTests(unittest.TestCase):
    def run_cli(self, *arguments, cwd=None, check=True):
        environment = os.environ.copy()
        source = str(ROOT / "src")
        environment["PYTHONPATH"] = source + os.pathsep + environment.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, "-m", "mcp_to_skills", *arguments],
            cwd=cwd or ROOT,
            env=environment,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=30,
        )
        if check and result.returncode != 0:
            self.fail("CLI failed:\nstdout:\n%s\nstderr:\n%s" % (result.stdout, result.stderr))
        return result

    def write_config(self, directory, modern=False):
        path = directory / "source.yaml"
        modern_arg = '\n  - "--modern"' if modern else ""
        path.write_text(
            'name: "demo"\ntransport: stdio\ncommand: "%s"\nargs:\n  - "%s"%s\nlifecycle:\n  mode: on-demand\n'
            % (sys.executable.replace("\\", "\\\\"), str(FAKE_SERVER).replace("\\", "\\\\"), modern_arg),
            encoding="utf-8",
        )
        return path

    def test_generate_session_skill_and_discover_tools(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.write_config(root, modern=True)
            target = root / ".agents" / "skills" / "demo"
            result = self.run_cli(
                "generate",
                "demo",
                "--session",
                "--config",
                str(source),
                "--output",
                str(target),
            )

            self.assertIn("Generated Codex Skill:", result.stdout)
            self.assertIn("Tools: 2", result.stdout)
            skill = (target / "SKILL.md").read_text(encoding="utf-8")
            tools = (target / "references" / "tools.md").read_text(encoding="utf-8")
            self.assertIn("name: demo", skill)
            self.assertIn("Keep the session running between related calls", skill)
            self.assertIn("## `echo`", tools)
            self.assertIn('"value"', tools)
            generated_config = load_config(target / "mcp.yaml", expected_name="demo")
            self.assertEqual(generated_config.lifecycle_mode, "session")
            self.assertEqual(generated_config.idle_timeout, 600)

    def test_default_location_and_on_demand_shape_without_inspection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self.run_cli("generate", "blender", "--no-inspect", cwd=root)
            target = root / ".agents" / "skills" / "blender"
            config = load_config(target / "mcp.yaml", expected_name="blender")
            self.assertEqual(config.command, "uvx")
            self.assertEqual(config.args, ["blender-mcp"])
            self.assertEqual(config.lifecycle_mode, "on-demand")
            self.assertIn("inspection skipped", result.stdout)
            self.assertIn("On-demand workflow", (target / "SKILL.md").read_text(encoding="utf-8"))

    def test_refuses_to_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.run_cli("generate", "demo", "--no-inspect", cwd=root)
            result = self.run_cli("generate", "demo", "--no-inspect", cwd=root, check=False)
            self.assertEqual(result.returncode, 2)
            self.assertIn("--force", result.stderr)
            forced = self.run_cli("generate", "demo", "--no-inspect", "--force", cwd=root)
            self.assertEqual(forced.returncode, 0)

    def test_rejects_invalid_skill_name(self):
        result = self.run_cli("generate", "Bad_Name", "--no-inspect", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("lowercase", result.stderr)


if __name__ == "__main__":
    unittest.main()
