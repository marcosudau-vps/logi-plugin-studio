"""Unabhängige negative Kontrollen für den lokalen Agenten-Rückweg."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from zurueck import ROOT, verify_zip

RUN = "RUN-AP-BRIDGE-SMOKE-01"
ORIGINAL = ROOT / "work" / "runs" / RUN / "outputs" / (RUN + ".zip")


class AgentBridgeReview(unittest.TestCase):
    def test_valid_smoke_zip(self):
        result = verify_zip(ORIGINAL, RUN)
        self.assertEqual(result["file_count"], 1)
        self.assertEqual(result["crc"], "PASS")
        self.assertEqual(result["manifest"], "PASS")

    def test_wrong_run_id_rejected(self):
        with self.assertRaisesRegex(ValueError, "Run-ID"):
            verify_zip(ORIGINAL, "RUN-AP-BRIDGE-OTHER-01")

    def test_modified_file_content_rejected(self):
        with tempfile.TemporaryDirectory(prefix="bridge-check-", dir=ROOT / "work" / "agent_bridge") as tmp:
            modified = Path(tmp) / "changed.zip"
            with zipfile.ZipFile(ORIGINAL) as zin, zipfile.ZipFile(modified, "w") as zout:
                for member in zin.namelist():
                    raw = zin.read(member)
                    if member.endswith("/05_abschlussbericht.md"):
                        raw += b"\nUNAPPROVED CHANGE\n"
                    zout.writestr(member, raw)
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                verify_zip(modified, RUN)

    def test_extra_file_rejected(self):
        with tempfile.TemporaryDirectory(prefix="bridge-check-", dir=ROOT / "work" / "agent_bridge") as tmp:
            modified = Path(tmp) / "extra.zip"
            with zipfile.ZipFile(ORIGINAL) as zin, zipfile.ZipFile(modified, "w") as zout:
                for member in zin.namelist():
                    zout.writestr(member, zin.read(member))
                zout.writestr("PluginStudioArchitecture/extra.txt", "not declared")
            with self.assertRaisesRegex(ValueError, "ZIP-Dateien"):
                verify_zip(modified, RUN)

    def test_duplicate_file_rejected(self):
        with tempfile.TemporaryDirectory(prefix="bridge-check-", dir=ROOT / "work" / "agent_bridge") as tmp:
            modified = Path(tmp) / "duplicate.zip"
            with zipfile.ZipFile(ORIGINAL) as zin, zipfile.ZipFile(modified, "w") as zout:
                for member in zin.namelist():
                    zout.writestr(member, zin.read(member))
                zout.writestr(zin.namelist()[0], "repeated")
            with self.assertRaisesRegex(ValueError, "Doppelte"):
                verify_zip(modified, RUN)

    def test_inbox_consistency(self):
        msg = json.loads((ROOT / "work" / "agent_bridge" / "results" / (RUN + ".json")).read_text(encoding="utf-8"))
        self.assertEqual(msg["status"], "REVIEW_READY")
        self.assertFalse(msg["review_approved"])
        self.assertEqual(msg["verification"]["sha256"], verify_zip(ORIGINAL, RUN)["sha256"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
