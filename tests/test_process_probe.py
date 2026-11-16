"""Regression coverage for the local .NET SDK-process probe environment and failures."""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from probe_helpers import ProcessProbe


class FakeDotnetProcess:
    def __init__(self, output: str = "", exit_code: int = 17):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(output)
        self.exit_code = exit_code
        self.finished = False

    def poll(self):
        return self.exit_code if self.finished else None

    def wait(self, timeout=None):
        self.finished = True
        return self.exit_code

    def kill(self):
        self.finished = True


class ProcessProbeRegressions(unittest.TestCase):
    def test_sdk_native_search_path_is_only_set_for_child(self):
        sdk = Path(r"C:\Program Files\Logi\LogiPluginService\PluginApi.dll")
        fake = FakeDotnetProcess('JSON:{"ok":true}\n')
        with tempfile.TemporaryDirectory() as temp, \
                patch.dict(os.environ, {"PATH": r"C:\Windows\System32"}), \
                patch("probe_helpers.subprocess.Popen", return_value=fake) as start:
            original_path = os.environ["PATH"]
            with ProcessProbe(Path(temp) / "Probe.dll", Path(temp) / "connection.json",
                              Path(temp) / "csharp.log", sdk_dll=sdk) as probe:
                self.assertEqual(probe.rpc("inspect"), {"ok": True})
            env = start.call_args.kwargs["env"]
            self.assertEqual(env["PATH"], str(sdk.parent.resolve()) + os.pathsep + original_path)
            self.assertEqual(os.environ["PATH"], original_path)
            self.assertEqual(start.call_args.args[0][0], "dotnet")

    def test_early_eof_reports_process_exit_not_queue_empty(self):
        fake = FakeDotnetProcess(exit_code=42)
        with tempfile.TemporaryDirectory() as temp, \
                patch("probe_helpers.subprocess.Popen", return_value=fake):
            with ProcessProbe(Path(temp) / "Probe.dll", Path(temp) / "connection.json",
                              Path(temp) / "csharp.log") as probe:
                with self.assertRaisesRegex(RuntimeError, "exit code 42") as caught:
                    probe.rpc("visual sensitive-test-token")
                self.assertIn("csharp.log", str(caught.exception))
                self.assertNotIn("sensitive-test-token", str(caught.exception))

    def test_probe_without_sdk_reference_keeps_parent_path(self):
        fake = FakeDotnetProcess('JSON:{"ready":true}\n')
        with tempfile.TemporaryDirectory() as temp, \
                patch.dict(os.environ, {"PATH": r"C:\Windows\System32"}), \
                patch("probe_helpers.subprocess.Popen", return_value=fake) as start:
            with ProcessProbe(Path(temp) / "Probe.dll", Path(temp) / "connection.json",
                              Path(temp) / "csharp.log") as probe:
                self.assertEqual(probe.rpc("inspect"), {"ready": True})
            self.assertEqual(start.call_args.kwargs["env"]["PATH"], os.environ["PATH"])


if __name__ == "__main__":
    unittest.main()
