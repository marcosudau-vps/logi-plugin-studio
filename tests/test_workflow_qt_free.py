"""Die als Qt-frei beschriebenen Module des Ablaufs und der Wartung laden kein PySide6 (eigener Prozess)."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = """
import builtins, sys
sys.path.insert(0, {src!r})
real = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] == 'PySide6':
        raise ImportError('Qt geladen: ' + name)
    return real(name, *args, **kwargs)
builtins.__import__ = guarded
import studio.workflow, studio.workflow.model, studio.workflow.store, studio.workflow.facts
import studio.handler_inspector.lifecycle, studio.maintenance.model
from studio.workflow.store import WorkflowStore
from studio.maintenance.model import DeactivationStore
WorkflowStore(); DeactivationStore()
print('ok')
"""


class QtFreeModulesTests(unittest.TestCase):
    def test_model_modules_do_not_import_qt(self):
        result = subprocess.run([sys.executable, "-c", PROBE.format(src=str(ROOT / "src"))],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_settings_dir_matches_the_build_mode_store(self):
        import os
        from unittest.mock import patch
        sys.path.insert(0, str(ROOT / "src"))
        from studio.native_shell.build_mode_store import settings_dir as original
        from studio.workflow.paths import settings_dir as copy
        self.assertEqual(copy(), original())
        with patch.dict(os.environ, {"LOGI_STUDIO_DATA": str(ROOT / "x")}):
            self.assertEqual(copy(), original())
        with patch.object(sys, "frozen", True, create=True), patch.dict(os.environ, {"LOCALAPPDATA": str(ROOT)}):
            os.environ.pop("LOGI_STUDIO_DATA", None)
            self.assertEqual(copy(), original())


if __name__ == "__main__":
    unittest.main()
