"""R3: native assets and portable contract fixtures in the real source scope."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from delivery.export import collect_sources, export_sources, verify_archive, ExportError

class ReviewExportTests(unittest.TestCase):
    def test_native_asset_roundtrip_and_fixture_inclusion(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); (root/'src/assets').mkdir(parents=True); (root/'tests/fixtures').mkdir(parents=True)
            (root/'src/assets/icon.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
            (root/'src/assets/default.ict').write_text('{"items":[]}')
            (root/'tests/fixtures/contract.json').write_text('{"version":1}')
            result=export_sources(root,root/'work/autopilot/FINAL-PRODUCT-02/delivery')
            m=verify_archive(Path(result['archive']))
            self.assertEqual(m['count'],3)
            with zipfile.ZipFile(result['archive']) as z:
                self.assertEqual(z.testzip(),None)
                self.assertEqual(z.read('PluginStudioArchitecture/src/assets/default.ict'),b'{"items":[]}')
    def test_secret_scan_still_applies_to_native_assets(self):
        for ext in ('svg','ict'):
            with self.subTest(ext=ext), tempfile.TemporaryDirectory() as temp:
                root=Path(temp);(root/'src').mkdir()
                (root/f'src/icon.{ext}').write_text('api_key = "'+'x'*32+'"')
                with self.assertRaisesRegex(ExportError,'EXPORT_SECRET_CONTENT'):
                    collect_sources(root,run='FINAL-PRODUCT-02')
    def test_unknown_asset_still_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'src').mkdir();(root/'src/file.bin').write_bytes(b'unknown')
            with self.assertRaisesRegex(ExportError,'EXPORT_UNKNOWN_FILE'):
                collect_sources(root,run='FINAL-PRODUCT-02')
    def test_portable_contract_fixtures_are_available(self):
        for name in ('inspector-coverage','lifecycle-coverage','help-coverage','studio-connections'):
            self.assertTrue(json.loads((ROOT/f'tests/fixtures/contracts/{name}.json').read_text(encoding='utf-8')))
    def test_dependency_manifests_and_gitignore_are_explicit_root_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in ('.gitignore','requirements.txt','requirements-dev.txt'):
                (root/name).write_text('# explicit reviewed root file\n')
            result=export_sources(root,root/'work/autopilot/FINAL-PRODUCT-02/delivery')
            self.assertEqual(verify_archive(Path(result['archive']))['count'],3)
