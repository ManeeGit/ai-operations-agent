from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from ops_agent.cli import main


class CLITests(unittest.TestCase):
    def test_bounded_demo_outputs_parseable_report(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            status = main(["demo", "--scenario", "cascade"])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(stdout.getvalue())["stats"]["incidents_open"], 3)

    def test_bounded_demo_file(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            output = Path(tmp) / "nested" / "demo.json"
            self.assertEqual(main(["demo", "--output", str(output)]), 0)
            self.assertEqual(json.loads(output.read_text())["mode"], "demo")

    def test_invalid_port_has_friendly_error(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            status = main(["serve", "--port", "99999"])
        self.assertEqual(status, 2)
        self.assertIn("port must be", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_missing_config_has_friendly_error(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stderr(io.StringIO()):
            self.assertEqual(main(["monitor", "--config", str(Path(tmp) / "missing.toml"), "--cycles", "1"]), 2)
