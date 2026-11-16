from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if Path("C:/Windows/Fonts").is_dir():
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
FIXTURE = ROOT / "tests" / "fixtures" / "symbol_designer" / "native_style.ict"

from symbol_designer.ict import (BLACK, IMAGE, LAYOUTS, TEXT, IconTemplate, IctError, apply_layout,
                                 content_fingerprint, detect_layout, editor_px, font_units, image_info,
                                 parse_argb, recolor_svg, svg_colors, transfer_style)
from symbol_designer.library import (BUNDLED_ROOT, ENV_VAR, default_library_root, read_metadata,
                                     scan_library)

try:
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication
    from symbol_designer import render
    HAS_QT = True
except ModuleNotFoundError as exc:
    if exc.name != "PySide6":
        raise
    HAS_QT = False

MONO_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect x="2" y="2" width="6" height="6" fill="#E2E2E2"/></svg>'
MULTI_SVG = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="5" height="10" fill="#ff0000"/>'
             b'<rect x="5" width="5" height="10" style="fill:#0000ff"/></svg>')
RASTER_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><image href="data:image/png;base64,AAAA" width="10" height="10"/></svg>'


def animated_gif() -> bytes:
    frame = b"\x21\xf9\x04\x00\x0a\x00\x00\x00" + b"\x2c" + struct.pack("<HHHH", 0, 0, 1, 1) + b"\x00\x02\x02\x44\x01\x00"
    return b"GIF89a" + struct.pack("<HH", 1, 1) + b"\x80\x00\x00" + b"\x00\x00\x00\xff\xff\xff" + frame * 2 + b"\x3b"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class IctModelTests(unittest.TestCase):
    def test_font_scale_matches_options_plus_editor(self):
        self.assertEqual([editor_px(s) for s in range(1, 10)], [6, 12, 15, 21, 27, 33, 38, 42, 48])
        self.assertEqual(font_units(5), 14)

    def test_new_template_is_native_and_round_trips(self):
        template = IconTemplate()
        self.assertEqual(set(template.data), {"backgroundColor", "items"})
        self.assertEqual([i["itemType"] for i in template.items], [IMAGE, TEXT])
        self.assertTrue(all("$type" in i for i in template.items))
        with tempfile.TemporaryDirectory() as tmp:
            path = template.save(Path(tmp) / "neu.ict")
            again = IconTemplate.load(path)
        self.assertEqual(again.data, template.data)
        self.assertEqual(again.background, BLACK)

    def test_native_file_round_trip_is_byte_identical_and_keeps_unknown_fields(self):
        raw = FIXTURE.read_bytes()
        template = IconTemplate.from_bytes(raw)
        self.assertEqual(template.to_bytes(), raw)
        self.assertEqual(template.style.indent, 4)
        self.assertEqual(template.style.newline, "\r\n")
        notes = " ".join(template.notices())
        self.assertIn("futureTemplateField", notes)
        self.assertIn("futureTextOption", notes)
        template.text = "Neu"
        template.set_area(IMAGE, 10, 10, 50, 50)
        data = json.loads(template.to_bytes())
        self.assertEqual(data["futureTemplateField"], "bleibt erhalten")
        self.assertEqual(data["items"][1]["futureTextOption"], {"shadow": True})
        self.assertIsNone(data["items"][1]["originalText"])
        self.assertFalse(data["items"][0]["area"]["isFullScreen"])
        self.assertEqual(list(data["items"][0]), list(json.loads(raw)["items"][0]))

    def test_invalid_inputs_raise_readable_errors(self):
        for raw in (b"{", b"[1,2]", b'{"items": 5}', b"\xff\xfe\x00"):
            with self.assertRaises(IctError):
                IconTemplate.from_bytes(raw)
        template = IconTemplate()
        with self.assertRaises(IctError):
            template.font_size = 12
        with self.assertRaises(IctError):
            parse_argb("blau")
        self.assertEqual(parse_argb("#123456"), 0xFF123456)
        broken = IconTemplate({"backgroundColor": "x", "items": [{"itemType": "Image", "image": "@@@"},
                                                                 {"itemType": "Sound"}]})
        self.assertIsNone(broken.image_bytes())
        self.assertEqual(broken.background, BLACK)
        self.assertTrue(any("Sound" in n for n in broken.notices()))

    def test_file_reference_without_embedded_image_is_reported(self):
        template = IconTemplate()
        template.item(IMAGE)["imageFileName"] = "extern.svg"
        self.assertTrue(any("extern.svg" in n for n in template.notices()))

    def test_image_classification_follows_logitech_tint_rule(self):
        mono = image_info(MONO_SVG)
        self.assertTrue(mono.tintable)
        self.assertEqual(mono.svg_color, 0xFFE2E2E2)
        self.assertFalse(image_info(MULTI_SVG).tintable)
        self.assertFalse(image_info(RASTER_SVG).tintable)
        self.assertTrue(image_info(animated_gif()).animated)
        self.assertEqual(image_info(b"\x89PNG\r\n\x1a\n....").format, "png")
        self.assertEqual(svg_colors(MULTI_SVG.decode()), {"#ff0000", "#0000ff"})
        self.assertEqual(svg_colors(recolor_svg(MONO_SVG.decode(), 0xFF00FF00)), {"#00ff00"})

    def test_set_image_takes_svg_colour_like_options_plus(self):
        template = IconTemplate()
        template.set_image(MONO_SVG, "mono.svg")
        self.assertEqual(template.image_color, 0xFFE2E2E2)
        self.assertEqual(template.image_bytes(), MONO_SVG)
        with self.assertRaises(IctError):
            template.set_image(b"kein bild", "x.txt")

    def test_layouts_change_geometry_only(self):
        template = IconTemplate.from_bytes(FIXTURE.read_bytes())
        template.set_visible(TEXT, False)
        protected = content_fingerprint(template)
        for layout in LAYOUTS[:4]:
            apply_layout(template, layout.key)
            self.assertEqual(template.area(IMAGE), layout.image)
            self.assertEqual(template.area(TEXT), layout.text)
            self.assertEqual(detect_layout(template), layout.key)
            self.assertEqual(content_fingerprint(template), protected)
            self.assertFalse(template.visible(TEXT))
        template.set_area(TEXT, 1, 2, 3, 4)
        self.assertIsNone(detect_layout(template))

    def test_style_transfer_never_touches_content(self):
        source = IconTemplate()
        source.set_image(MONO_SVG, "quelle.svg")
        source.background = 0xFF112233
        source.text_color = 0xFFFF0000
        source.font_size = 7
        source.image_color = 0xFF00FF00
        source.rotation = 90
        apply_layout(source, "text_top")
        mono_target = IconTemplate()
        mono_target.set_image(MONO_SVG.replace(b"E2E2E2", b"FFFFFF"), "ziel.svg")
        mono_target.text = "Ziel A"
        raster_target = IconTemplate.from_bytes(FIXTURE.read_bytes())
        raster_target.set_image(b"\x89PNG\r\n\x1a\nfake", "foto.png")
        for target in (mono_target, raster_target):
            before = content_fingerprint(target)
            result = transfer_style(source, target, ["background", "layout", "font", "text_color", "symbol_format"])
            self.assertEqual(content_fingerprint(target), before)
            self.assertEqual(target.background, 0xFF112233)
            self.assertEqual(target.area(TEXT), source.area(TEXT))
            self.assertEqual(target.font_size, 7)
            self.assertEqual(target.rotation, 90)
            self.assertTrue(result.changes)
        self.assertEqual(mono_target.image_color, 0xFF00FF00)
        self.assertNotEqual(raster_target.image_color, 0xFF00FF00)
        self.assertTrue(any("nicht einfärbbar" in s for s in result.skipped))
        self.assertEqual(json.loads(raster_target.to_bytes())["futureTemplateField"], "bleibt erhalten")
        with self.assertRaises(IctError):
            transfer_style(source, mono_target, ["inhalt"])


@unittest.skipUnless(HAS_QT, "PySide6 required")
class RenderAndExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="symbol-render-")
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def template(self, image: bytes = MONO_SVG) -> IconTemplate:
        template = IconTemplate()
        template.set_image(image, "bild")
        template.text = "Test"
        return template

    def test_render_sizes_tint_visibility_and_rotation(self):
        template = self.template()
        apply_layout(template, "image_full")
        template.set_visible(TEXT, False)
        template.image_color = 0xFF00FF00
        for size in (50, 80, 116):
            image = render.render_template(template, size)
            self.assertEqual((image.width(), image.height()), (size, size))
        center = QColor(render.render_template(template, 116).pixel(58, 58))
        self.assertEqual((center.red(), center.green(), center.blue()), (0, 255, 0))
        template.set_visible(IMAGE, False)
        hidden = render.render_template(template, 116)
        self.assertEqual(QColor(hidden.pixel(58, 58)).rgb() & 0xFFFFFF, 0)
        self.assertEqual(template.image_bytes(), MONO_SVG)
        multi = self.template(MULTI_SVG)
        apply_layout(multi, "image_full")
        multi.set_visible(TEXT, False)
        left = QColor(render.render_template(multi, 100).pixel(20, 50))
        self.assertGreater(left.red(), 200)
        multi.rotation = 180
        left = QColor(render.render_template(multi, 100).pixel(20, 50))
        self.assertGreater(left.blue(), 200)

    def test_png_exports_are_written_in_sdk_sizes(self):
        template = self.template()
        paths = render.export_pngs(template, self.dir, "icon")
        self.assertEqual([QImage(str(p)).width() for p in paths], [50, 80, 116])
        reference = render.render_template(template, 116)
        self.assertEqual(QImage(str(paths[-1])).convertToFormat(QImage.Format.Format_ARGB32),
                         reference.convertToFormat(QImage.Format.Format_ARGB32))
        with self.assertRaises(IctError):
            render.export_png(template, self.dir / "x.png", 64)

    def test_svg_export_keeps_vectors_and_labels_raster(self):
        report = render.export_svg(self.template(), self.dir / "vector.svg")
        root = ET.parse(report.path).getroot()
        self.assertTrue(report.vector_image)
        self.assertFalse(report.raster_embedded)
        self.assertEqual(root.findall(".//{http://www.w3.org/2000/svg}image"), [])
        self.assertTrue(root.findall(".//{http://www.w3.org/2000/svg}text"))
        png = render.render_template(self.template(), 64)
        png_bytes = render._png_bytes(png)
        report = render.export_svg(self.template(png_bytes), self.dir / "raster.svg")
        self.assertTrue(report.raster_embedded)
        self.assertTrue(any("keine Vektorisierung" in n for n in report.notes))
        from PySide6.QtSvg import QSvgRenderer
        self.assertTrue(QSvgRenderer(str(report.path)).isValid())
        image = QImage(116, 116, QImage.Format.Format_ARGB32)
        image.fill(0)
        from PySide6.QtGui import QPainter
        painter = QPainter(image)
        QSvgRenderer(str(self.dir / "vector.svg")).render(painter)
        painter.end()
        bright = sum(1 for y in range(70, 116) for x in range(116) if QColor(image.pixel(x, y)).red() > 128)
        self.assertGreater(bright, 20, "Text muss im SVG sichtbar gerendert werden")

    def test_action_symbol_requires_monochrome_svg(self):
        path = render.export_action_symbol(MONO_SVG, self.dir / "actionsymbols" / "Demo.Action.svg")
        self.assertEqual(svg_colors(path.read_text()), {"#000000"})
        for data in (MULTI_SVG, b"\x89PNG\r\n\x1a\n", RASTER_SVG):
            with self.assertRaises(IctError):
                render.action_symbol_svg(data)

    def test_import_conversions_and_errors(self):
        big = QImage(1400, 900, QImage.Format.Format_ARGB32)
        big.fill(QColor(10, 20, 30, 128))
        for y in range(0, 900, 3):
            for x in range(0, 1400, 7):
                big.setPixel(x, y, (x * y) & 0xFFFFFFFF)
        big.save(str(self.dir / "gross.png"))
        prepared = render.prepare_file(self.dir / "gross.png")
        self.assertLessEqual(len(prepared.data), 150 * 1024)
        self.assertLessEqual(QImage.fromData(prepared.data).width(), 512)
        self.assertTrue(prepared.notes)
        QImage(40, 30, QImage.Format.Format_RGB32).save(str(self.dir / "bild.bmp"))
        converted = render.prepare_file(self.dir / "bild.bmp")
        self.assertEqual(converted.info.format, "png")
        self.assertEqual(converted.filename, "bild.png")
        self.assertTrue(any("BMP" in n for n in converted.notes))
        still = render.prepare_image(animated_gif(), "anim.gif")
        self.assertEqual(still.info.format, "png")
        original = render.prepare_image(animated_gif(), "anim.gif", render.GIF_ORIGINAL)
        self.assertEqual(original.info.format, "gif")
        self.assertTrue(any("nicht verifiziert" in n for n in original.notes))
        (self.dir / "kaputt.png").write_bytes(b"\x89PNG\r\n\x1a\nkaputt")
        (self.dir / "text.png").write_text("kein Bild")
        (self.dir / "leer.svg").write_bytes(b"")
        (self.dir / "riesig.svg").write_bytes(MONO_SVG[:-6] + b"<!--" + b"x" * 160_000 + b"--></svg>")
        for name in ("kaputt.png", "text.png", "leer.svg", "riesig.svg", "fehlt.png"):
            with self.assertRaises(IctError, msg=name):
                render.prepare_file(self.dir / name)
        prepared = render.prepare_file(BUNDLED_ROOT / "Medien" / "Wiedergabe.svg")
        self.assertTrue(prepared.info.tintable)

    def test_corrupt_embedded_image_renders_without_crash(self):
        template = IconTemplate()
        template.item(IMAGE)["image"] = base64.b64encode(b"\x89PNG\r\n\x1a\ndefekt").decode()
        notes = []
        image = render.render_template(template, 80)
        self.assertFalse(image.isNull())
        self.assertIsNotNone(render.build_svg(template)[0])
        self.assertEqual(notes, [])


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="symbol-library-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        good = self.root / "GoodPack"
        (good / "metadata").mkdir(parents=True)
        (good / "metadata" / "LoupedeckPackage.yaml").write_text(
            "type: iconLibrary\nname: GoodPack\ndisplayName: Gute Symbole\ndescription: Test\n"
            "author: Tester\nversion: 1.0\nlicense: CC0\n", encoding="utf-8")
        (good / "Play.svg").write_bytes(MONO_SVG)
        (good / "Foto.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (good / "Anim.gif").write_bytes(animated_gif())
        (good / "liesmich.txt").write_text("x")
        (good / "Unter").mkdir()
        (good / "Unter" / "Tief.svg").write_bytes(MONO_SVG)
        (good / "__MACOSX").mkdir()
        (good / "__MACOSX" / "._Play.svg").write_bytes(b"junk")
        (good / "._Play.svg").write_bytes(b"junk")
        bare = self.root / "OhneMetadaten"
        bare.mkdir()
        (bare / "Icon.svg").write_bytes(MONO_SVG)
        broken = self.root / "Kaputt"
        (broken / "metadata").mkdir(parents=True)
        (broken / "metadata" / "LoupedeckPackage.yaml").write_bytes(b"\x00\x01 kein yaml")
        (broken / "Ok.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        other = self.root / "Plugin"
        (other / "metadata").mkdir(parents=True)
        (other / "metadata" / "LoupedeckPackage.yaml").write_text("type: plugin4\nname: X\n")

    def test_packages_metadata_formats_and_errors(self):
        hashes = {p: sha(p) for p in self.root.rglob("*") if p.is_file()}
        scan = scan_library(self.root, include_bundled=False)
        packages = {p.id: p for p in scan.packages}
        good = packages["GoodPack"]
        self.assertEqual(good.display_name, "Gute Symbole")
        self.assertEqual(good.formats(), {"svg": 2, "png": 1, "gif": 1})
        self.assertEqual([p.name for p in good.unsupported], ["liesmich.txt"])
        self.assertEqual(next(e for e in good.entries if e.name == "Tief").category, "Unter")
        self.assertEqual(packages["OhneMetadaten"].display_name, "OhneMetadaten")
        self.assertTrue(packages["OhneMetadaten"].errors)
        self.assertEqual(len(packages["Kaputt"].entries), 1)
        self.assertTrue(any("Metadaten" in e for e in packages["Kaputt"].errors))
        self.assertTrue(any("plugin4" in e for e in packages["X"].errors))
        self.assertEqual([e.name for e in scan.search("tief")], ["Tief"])
        self.assertEqual(len(scan.search("gif goodpack")), 1)
        self.assertEqual({p: sha(p) for p in self.root.rglob("*") if p.is_file()}, hashes)

    def test_root_resolution_and_missing_root(self):
        self.assertEqual(default_library_root({ENV_VAR: str(self.root)}), self.root)
        self.assertEqual(default_library_root({"LOCALAPPDATA": "C:/Daten"}),
                         Path("C:/Daten/Logi/LogiPluginService/Media/Icons"))
        self.assertIsNone(default_library_root({}))
        scan = scan_library(self.root / "fehlt")
        self.assertTrue(scan.errors)
        self.assertEqual([p.bundled for p in scan.packages], [True])
        self.assertGreaterEqual(scan.packages[0].formats().get("svg", 0), 30)

    def test_metadata_reader(self):
        path = self.root / "meta.yaml"
        path.write_text('\ufefftype: IconLibrary\ndisplayName: "Mit: Doppelpunkt"\n# Kommentar\n  eingerueckt: x\n',
                        encoding="utf-8")
        self.assertEqual(read_metadata(path), {"type": "IconLibrary", "displayName": "Mit: Doppelpunkt"})


INSTALLED = default_library_root()


@unittest.skipUnless(INSTALLED is not None and INSTALLED.is_dir(), "keine installierte Logitech-Icon-Bibliothek")
class InstalledLibraryTests(unittest.TestCase):
    def test_installed_packages_are_read_only_and_complete(self):
        files = [p for p in INSTALLED.rglob("*") if p.is_file()]
        stamps = {p: p.stat().st_mtime_ns for p in files}
        scan = scan_library(INSTALLED)
        installed = [p for p in scan.packages if not p.bundled]
        self.assertTrue(installed)
        self.assertEqual(scan.errors, [])
        for package in installed:
            self.assertTrue(package.display_name)
            supported = [p for p in package.root.rglob("*") if p.is_file() and p.suffix.lower() in
                         (".svg", ".png", ".gif", ".jpg", ".jpeg", ".webp", ".bmp") and "metadata" not in p.parts
                         and "__MACOSX" not in p.parts and not p.name.startswith("._")]
            self.assertEqual(len(package.entries), len(supported), package.display_name)
        self.assertEqual({p: p.stat().st_mtime_ns for p in files}, stamps)


if __name__ == "__main__":
    unittest.main()
