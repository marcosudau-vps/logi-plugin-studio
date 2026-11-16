from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import secrets
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from delivery.export import ExportError, collect_sources, export_sources, verify_archive


class SafeExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="safe-export-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "src" / "nested"
        self.source.mkdir(parents=True)
        (self.source / "program.py").write_text("print('safe source')\n")
        self.run = "FINAL-PRODUCT-02"
        self.out = self.root / "work" / "autopilot" / self.run / "delivery"
        self.key = secrets.token_hex(32)

    def private(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"secret": self.key}))
        return path

    def test_nested_connections_build_vendor_backup_and_full_zip_never_selected(self):
        for name in ("work/deep/bin/Debug/studio.connection.json",
                     "src/nested/studio.connection.json", "src/nested/private/studio.connection.json"):
            self.private(name)
        for name in ("src/nested/bin/PluginApi.dll", "src/nested/obj/secret.py",
                     "src/nested/dump.zip", "src/nested/code.py.bak", "src/nested/.env"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.key)
        result = export_sources(self.root, self.out)
        manifest = verify_archive(Path(result["archive"]))
        self.assertEqual(manifest["count"], 1)
        self.assertNotIn(self.key.encode(), Path(result["archive"]).read_bytes())
        with zipfile.ZipFile(result["archive"]) as zipped:
            self.assertFalse(any("studio.connection.json" in name or name.endswith(".dll") for name in zipped.namelist()))

    def test_known_connection_secret_copied_to_innocent_file_blocks_export(self):
        self.private("work/arbitrary/install/studio.connection.json")
        (self.source / "notes.md").write_text("Accidental disclosure " + self.key)
        with self.assertRaises(ExportError) as raised:
            export_sources(self.root, self.out)
        self.assertNotIn(self.key, str(raised.exception))
        self.assertFalse(self.out.exists())

    def test_encoded_binary_key_copy_also_blocks(self):
        self.private("work/hidden/studio.connection.json")
        (self.source / "image.png").write_bytes(bytes.fromhex(self.key))
        with self.assertRaises(ExportError):
            export_sources(self.root, self.out)

    def test_unknown_secret_credentials_token_and_private_key_fail_closed(self):
        for name, content in (("credentials.json", "{}"), ("note.md", "-----BEGIN PRIVATE KEY-----"),
                              ("normal.json", '{"access_token":"' + secrets.token_urlsafe(32) + '"}'),
                              ("normal.py", "password = '" + secrets.token_urlsafe(32) + "'"),
                              ("normal.md", "ghp_" + secrets.token_hex(24))):
            path = self.source / name
            path.write_text(content)
            with self.assertRaises(ExportError):
                collect_sources(self.root, run=self.run)
            path.unlink()

    def test_malformed_private_configuration_refused_without_contents(self):
        path = self.private("work/hidden/studio.connection.json")
        path.write_text('{"secret":"' + self.key)
        with self.assertRaises(ExportError) as raised:
            export_sources(self.root, self.out)
        self.assertNotIn(self.key, str(raised.exception))

    def test_unknown_source_extension_refuses_full_project_style_export(self):
        (self.source / "uncategorized.dat").write_bytes(b"unknown data")
        with self.assertRaises(ExportError):
            export_sources(self.root, self.out)
        with self.assertRaises(ExportError):
            collect_sources(self.root, run="full-project")

    def test_symlink_escape_and_linked_directory_refused(self):
        target = self.root / "outside"
        target.mkdir()
        for link, destination, is_dir in ((self.source / "linked.py", self.source / "program.py", False),
                                          (self.source / "linked", target, True)):
            try:
                link.symlink_to(destination, target_is_directory=is_dir)
            except OSError:
                self.skipTest("Windows symlink privilege unavailable")
            with self.assertRaises(ExportError):
                export_sources(self.root, self.out)
            link.unlink()

    def test_zip_crc_and_hash_verification_and_live_bytes(self):
        result = export_sources(self.root, self.out)
        manifest = verify_archive(Path(result["archive"]))
        for name, digest in manifest["files"].items():
            self.assertEqual(hashlib.sha256((self.root / name).read_bytes()).hexdigest(), digest)
        archive = self.out / "tampered.zip"
        with zipfile.ZipFile(result["archive"]) as original, zipfile.ZipFile(archive, "w") as altered:
            for name in original.namelist():
                altered.writestr(name, b"changed source" if name.endswith("program.py") else original.read(name))
        with self.assertRaises(ExportError):
            verify_archive(archive)
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zipped:
            zipped.writestr("broken.py", "unique bytes to corrupt")
        data = archive.read_bytes().replace(b"unique bytes to corrupt", b"unique bytes to CORRUPT")
        archive.write_bytes(data)
        with self.assertRaises(ExportError):
            verify_archive(archive)
        archive.write_bytes(b"not a ZIP")
        with self.assertRaises(ExportError):
            verify_archive(archive)

    def test_unclassified_full_project_zip_never_verifies_share_safe(self):
        archive = self.root / "full-project.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("work/bin/studio.connection.json", json.dumps({"secret": self.key}))
        with self.assertRaises(ExportError):
            verify_archive(archive)

    def test_duplicate_and_extra_archive_members_refused(self):
        result = export_sources(self.root, self.out)
        for duplicate in (False, True):
            bad = self.root / ("duplicate.zip" if duplicate else "extra.zip")
            with zipfile.ZipFile(result["archive"]) as source, zipfile.ZipFile(bad, "w") as target:
                for name in source.namelist():
                    target.writestr(name, source.read(name))
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    target.writestr("source-hashes.json" if duplicate else "extra.bin", "{}")
            with self.assertRaises(ExportError):
                verify_archive(bad)

    def test_foreign_output_not_overwritten(self):
        self.out.mkdir(parents=True)
        (self.out / "foreign.txt").write_text("preserve")
        with self.assertRaises(ExportError):
            export_sources(self.root, self.out)
        self.assertEqual((self.out / "foreign.txt").read_text(), "preserve")

    def test_own_reexport_works_and_no_secret_output(self):
        self.private("work/private/studio.connection.json")
        log = io.StringIO()
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            first = export_sources(self.root, self.out)
            second = export_sources(self.root, self.out)
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertNotIn(self.key, log.getvalue())

    def test_linked_output_sidecar_is_never_overwritten(self):
        export_sources(self.root, self.out)
        sidecar = self.out / "source-hashes.json"
        outside = self.root / "preserve.txt"
        outside.write_text("preserve")
        sidecar.unlink()
        try:
            sidecar.symlink_to(outside)
        except OSError:
            self.skipTest("Windows symlink privilege unavailable")
        with self.assertRaises(ExportError):
            export_sources(self.root, self.out)
        self.assertEqual(outside.read_text(), "preserve")

    def test_forged_manifest_build_scope_and_zip_symlink_fail_closed(self):
        import stat
        for name, linked in (("work/autopilot/FINAL-PRODUCT-02/build/unsafe.py", False),
                             ("src/nested/program.py", True)):
            content = b"innocent.py"
            manifest = {"format": "studio-safe-source-2", "share_scope": "REVIEW_SOURCE_ONLY", "run": self.run,
                        "count": 1, "files": {name: hashlib.sha256(content).hexdigest()}}
            bad = self.root / "forged.zip"
            with zipfile.ZipFile(bad, "w") as zipped:
                info = zipfile.ZipInfo("PluginStudioArchitecture/" + name)
                if linked:
                    info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                zipped.writestr(info, content)
                zipped.writestr("source-hashes.json", json.dumps(manifest))
            with self.assertRaises(ExportError):
                verify_archive(bad)

    def test_delivery_source_module_is_included_but_private_connection_is_not(self):
        module = self.root / "src" / "delivery" / "export.py"
        module.parent.mkdir()
        module.write_text("print('safe delivery implementation')")
        result = export_sources(self.root, self.out)
        self.assertIn("src/delivery/export.py", verify_archive(Path(result["archive"]))["files"])
        self.private("src/delivery/studio.connection.json")
        (self.source / "copied.md").write_text(self.key)
        with self.assertRaises(ExportError):
            collect_sources(self.root, run=self.run)


if __name__ == "__main__":
    unittest.main()
