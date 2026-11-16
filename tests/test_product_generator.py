from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from adapters.logitech.codegen import DEFAULT_SDK_DLL
from adapters.logitech.errors import GenerationError
from adapters.logitech.product import build_product, generate_product, read_asset, validate_product
from core.io import load_raw


class ProductGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio-product-")
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.raw = load_raw(ROOT / "examples" / "project_v0_1_draft.json")

    def test_unknown_presentation_fields_missing_asset_and_multiple_selectors_block(self):
        for alter in (
            lambda r: r["presentations"][0]["variants"]["variant_0"].update({"script": "unsafe"}),
            lambda r: r["presentations"][0]["variants"]["variant_0"].update({"image": "missing"}),
            lambda r: r["bindings"].append(copy.deepcopy(r["bindings"][-1])),
        ):
            raw = copy.deepcopy(self.raw)
            alter(raw)
            with self.assertRaises(GenerationError):
                validate_product(raw, self.directory)

    def test_asset_traversal_and_non_png_block(self):
        for path in ("../foreign.png", "C:/foreign.png", "bad.png"):
            raw = copy.deepcopy(self.raw)
            raw["assets"] = [{"id": "image", "path": path}]
            (self.directory / "bad.png").write_bytes(b"not a PNG")
            with self.assertRaises(GenerationError):
                validate_product(raw, self.directory)

    def test_scope_and_capability_gate(self):
        for alter in (
            lambda r: r["states"][0].update({"scope": "session"}),
            lambda r: r["components"][0].update({"type": "not.implemented"}),
            lambda r: r["views"][0].update({"type": "not.implemented"}),
        ):
            raw = copy.deepcopy(self.raw)
            alter(raw)
            with self.assertRaises(GenerationError):
                validate_product(raw, self.directory)

    def test_crc_valid_but_invalid_png_raster_is_rejected(self):
        import struct
        import zlib
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
        header = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        for data in (b"invalid zlib", zlib.compress(b"\0\0"), zlib.compress(b"\x09\0\0\0\0")):
            (self.directory / "bad.png").write_bytes(b"\x89PNG\r\n\x1a\n" + header + chunk(b"IDAT", data) + chunk(b"IEND", b""))
            with self.assertRaises(GenerationError):
                read_asset(self.directory, {"id": "bad", "path": "bad.png"})

    @unittest.skipUnless(DEFAULT_SDK_DLL.is_file(), "Real installed SDK required")
    def test_modified_generated_source_blocks_build_before_dotnet(self):
        project = self.directory / "project.json"
        project.write_text(json.dumps(self.raw), encoding="utf-8")
        output = self.directory / "product"
        plan = generate_product(project, output_dir=output, assembly_name="ProductGuard")
        (output / "src" / "Bridge.cs").write_text("foreign code")
        with self.assertRaises(GenerationError):
            build_product(plan, output)

    @unittest.skipUnless(DEFAULT_SDK_DLL.is_file(), "Real installed SDK required")
    def test_reproducible_generation_has_no_secrets_and_no_logical_slot_limit(self):
        for index in range(20):
            self.raw["views"][0]["placements"].append({
                "id": f"placement.extra.{index}", "component": "action.primary",
                "presentation": "visual.primary", "position": index + 10})
        project = self.directory / "project.json"
        project.write_text(json.dumps(self.raw), encoding="utf-8")
        first = generate_product(project, output_dir=self.directory / "one", assembly_name="ProductTest")
        second = generate_product(project, output_dir=self.directory / "two", assembly_name="ProductTest")
        self.assertEqual(first.files, second.files)
        folder = next(v for k, v in first.files.items() if k.startswith("src/folders"))
        self.assertIn("placement.extra.19", folder)
        self.assertIn("PluginDynamicFolderNavigation.ButtonArea", folder)
        self.assertNotIn("studio.connection.json", first.files)
        self.assertEqual(first.manifest["product"]["hardware_status"], "HARDWARE_PENDING")
        self.assertIn("src/Application.cs", first.files)
        self.assertIn("ClientApplication", first.files["src/Application.cs"])
        self.assertIn("ProductTestApplication", first.files["src/Application.cs"])
        self.assertIn("Bridge.StartFromPluginAssembly(this.AssemblyFilePath)", first.files["src/Plugin.cs"])
        self.assertNotIn("Bridge.Start();", first.files["src/Plugin.cs"])
        self.assertIn("Path.IsPathFullyQualified(assemblyFilePath)", first.files["src/Bridge.cs"])
        self.assertIn('Log("CONNECTION_PATH_UNAVAILABLE")', first.files["src/Bridge.cs"])
        self.assertIn('name: "ProductTest"', first.files["metadata/LoupedeckPackage.yaml"])
        self.assertEqual(first.manifest["plugin"]["sdk_name"], "ProductTest")
        self.assertNotIn('name: "test.', first.files["metadata/LoupedeckPackage.yaml"])


if __name__ == "__main__":
    unittest.main()
