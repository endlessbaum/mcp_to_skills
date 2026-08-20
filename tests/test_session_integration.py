import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
FAKE_SERVER = ROOT / "tests" / "fake_mcp_server.py"


class SessionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.runtime = self.directory / "runtime"
        self.environment = os.environ.copy()
        self.environment["PYTHONPATH"] = str(SOURCE)
        self.environment["MCP_TO_SKILLS_RUNTIME_DIR"] = str(self.runtime)

    def tearDown(self):
        self.run_cli("session", "stop", "--all", check=False)
        deadline = time.monotonic() + 3
        while (self.runtime / "broker.json").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        # On Windows the detached broker can remove its state file just before
        # the OS releases the inherited broker.log handle. Retry that short
        # shutdown window so teardown does not make successful tests flaky.
        cleanup_deadline = time.monotonic() + 3
        while True:
            try:
                self.temporary.cleanup()
                break
            except PermissionError:
                if time.monotonic() >= cleanup_deadline:
                    raise
                time.sleep(0.05)

    def config(self, name="demo", idle_timeout=30, modern=False):
        path = self.directory / (name + ".yaml")
        path.write_text(
            "name: %s\ntransport: stdio\ncommand: \"%s\"\nargs:\n  - \"%s\"%s\nlifecycle:\n  mode: session\n  idle_timeout: %s\n"
            % (
                name,
                sys.executable.replace("\\", "\\\\"),
                str(FAKE_SERVER).replace("\\", "\\\\"),
                "\n  - --modern" if modern else "",
                idle_timeout,
            ),
            encoding="utf-8",
        )
        return path

    def run_cli(self, *arguments, check=True):
        result = subprocess.run(
            [sys.executable, "-m", "mcp_to_skills"] + list(arguments),
            cwd=str(self.directory),
            env=self.environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if check and result.returncode != 0:
            self.fail("CLI failed (%s): %s" % (result.returncode, result.stderr))
        return result

    @staticmethod
    def tool_payload(result):
        outer = json.loads(result.stdout)
        return json.loads(outer["content"][0]["text"])

    def test_start_reuse_call_list_and_stop(self):
        config = self.config()
        first = self.run_cli("session", "start", "demo", "--config", str(config))
        self.assertIn("Session started.", first.stdout)
        second = self.run_cli("session", "start", "demo", "--config", str(config))
        self.assertIn("Session already running.", second.stdout)
        self.assertEqual(first.stdout.split("PID: ")[1].strip(), second.stdout.split("PID: ")[1].strip())

        one = self.tool_payload(self.run_cli("session", "call", "demo", "echo", "--json", '{"value": 1}'))
        two = self.tool_payload(self.run_cli("session", "call", "demo", "echo", "--json", '{"value": 2}'))
        self.assertEqual(one["pid"], two["pid"])
        self.assertEqual((one["calls"], two["calls"]), (1, 2))
        self.assertEqual(two["arguments"], {"value": 2})

        listing = self.run_cli("session", "list")
        self.assertIn("demo", listing.stdout)
        self.assertIn("ready", listing.stdout)
        stopped = self.run_cli("session", "stop", "demo")
        self.assertIn("Session stopped.", stopped.stdout)
        self.assertIn("No active MCP sessions.", self.run_cli("session", "list").stdout)

    def test_idle_timeout_removes_session_and_broker(self):
        config = self.config(idle_timeout=0.4)
        self.run_cli("session", "start", "demo", "--config", str(config))
        deadline = time.monotonic() + 4
        while (self.runtime / "broker.json").exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertFalse((self.runtime / "broker.json").exists())
        self.assertIn("STATE: off", self.run_cli("session", "status", "demo").stdout)

    def test_modern_mcp_discovery_and_call(self):
        config = self.config(modern=True)
        self.run_cli("session", "start", "demo", "--config", str(config))
        payload = self.tool_payload(self.run_cli("session", "call", "demo", "echo"))
        self.assertEqual(payload["calls"], 1)

    def test_zero_idle_timeout_stays_running(self):
        config = self.config(idle_timeout=0)
        self.run_cli("session", "start", "demo", "--config", str(config))
        time.sleep(0.8)
        payload = self.tool_payload(self.run_cli("session", "call", "demo", "echo"))
        self.assertEqual(payload["calls"], 1)

    def test_stop_all(self):
        first = self.config("first")
        second = self.config("second")
        self.run_cli("session", "start", "first", "--config", str(first))
        self.run_cli("session", "start", "second", "--config", str(second))
        result = self.run_cli("session", "stop", "--all")
        self.assertIn("first", result.stdout)
        self.assertIn("second", result.stdout)
        self.assertIn("No active MCP sessions.", result.stdout)

    def test_tool_error_is_reported(self):
        config = self.config()
        self.run_cli("session", "start", "demo", "--config", str(config))
        result = self.run_cli("session", "call", "demo", "fail", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("requested failure", result.stderr)


if __name__ == "__main__":
    unittest.main()
