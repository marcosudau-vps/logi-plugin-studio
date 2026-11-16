"""Automated GUI walkthrough of the Symbol Designer Lab (AP-WIDGET-001).

Drives the real SymbolDesignerWidget inside the Lab with mouse/keyboard events,
uses the installed Logitech icon library read-only, writes screenshots, sample
outputs and a JSON report. Usage:

    python tools\\symbol_designer_gui_check.py [--out DIR] [--onscreen]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
DEFAULT_OUT = ROOT / "work" / "widget-lab" / "icon-designer-v1" / "evidence"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--onscreen", action="store_true", help="echtes Fenster statt offscreen")
    args = parser.parse_args()
    if not args.onscreen:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        if Path("C:/Windows/Fonts").is_dir():
            os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QImage, QPainter, QColor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from symbol_designer.dialogs import ExportOptions, StyleTransferDialog
    from symbol_designer.ict import IMAGE, LAYOUTS, TEXT, IconTemplate, content_fingerprint
    from symbol_designer.lab import LabWindow, dark_palette
    from symbol_designer.library import ENV_VAR, default_library_root, scan_library
    from symbol_designer.render import render_template

    out = Path(args.out)
    shots = out / "screenshots"
    samples = out / "beispielausgaben"
    for folder in (shots, samples):
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
    work = Path(tempfile.mkdtemp(prefix="symbol-gui-check-"))
    report: dict = {"date": time.strftime("%Y-%m-%d %H:%M:%S"), "platform": os.environ.get("QT_QPA_PLATFORM", "windows"),
                    "checks": {}, "screenshots": [], "notes": []}

    def check(name: str, ok: bool, detail=None):
        report["checks"][name] = {"ok": bool(ok), "detail": detail}
        print(("OK   " if ok else "FAIL ") + name + ("" if detail is None else " – %s" % detail))

    library_root = default_library_root()
    installed_files = sorted(p for p in library_root.rglob("*") if p.is_file()) if library_root and library_root.is_dir() else []
    hashes_before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in installed_files}

    app = QApplication.instance() or QApplication(sys.argv[:1])
    dark_palette(app)
    lab = LabWindow(work / "lab-output")
    designer = lab.designer
    designer.ask_user = False
    lab.resize(1600, 1000)
    lab.show()

    def pump(seconds: float = 0.15):
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            time.sleep(0.01)

    def shot(name: str, widget=None):
        pump(0.2)
        path = shots / (name + ".png")
        (widget or lab).grab().save(str(path))
        report["screenshots"].append(path.relative_to(out).as_posix())

    def drag(start: QPoint, end: QPoint):
        canvas = designer.canvas
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        for step in range(1, 8):
            QTest.mouseMove(canvas, start + (end - start) * step / 7)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
        pump(0.05)

    pump(0.8)
    scan = designer.library.scan
    summary = scan.summary()
    report["library"] = summary
    check("Bibliothek: installierte Pakete mit Anzeigenamen", len(scan.packages) > 1,
          {p.display_name: len(p.entries) for p in scan.packages})
    formats = {f for p in scan.packages for f in p.formats()}
    check("Bibliothek: SVG, PNG und GIF gefunden", {"svg", "png", "gif"} <= formats, sorted(formats))
    shot("01_start_leere_vorlage")

    designer.library.search.setText("mute")
    designer.library.apply_filter()
    pump(0.8)
    hits = sum(s.matches for s in designer.library.sections if s.isVisible())
    check("Bibliothek: paketübergreifende Suche 'mute'", hits > 0, hits)
    shot("02_bibliothek_suche")

    svg_entry = designer.library.find_entry(lambda e: e.package_id == "DefaultIcons" and e.name == "MediaMuteMic") or \
        designer.library.find_entry(lambda e: e.format == "svg" and e.package_id != "studio-startsymbole")
    designer._library_icon(svg_entry)
    designer.set_text("Mikro aus")
    designer.apply_layout("image_top")
    designer.select(IMAGE)
    check("SVG aus installiertem Paket im Designer", designer.template.image_info().format == "svg",
          "%s / %s" % (svg_entry.package_id, svg_entry.path.name))
    designer.library.search.setText("")
    designer.library.apply_filter()
    shot("03_symbol_ausgewaehlt_mit_anfassern")

    rect = designer.canvas.item_rect(IMAGE)
    before = designer.template.area(IMAGE)
    drag(rect.center().toPoint(), rect.center().toPoint() + QPoint(-30, 20))
    corner = designer.canvas.handle_rects(IMAGE)["br"].center().toPoint()
    drag(corner, corner + QPoint(-50, -50))
    after = designer.template.area(IMAGE)
    designer.select(TEXT)
    top = designer.canvas.handle_rects(TEXT)["t"].center().toPoint()
    text_before = designer.template.area(TEXT)
    drag(top, top + QPoint(0, -30))
    check("Bild per Maus verschoben und skaliert", after != before and after[2] < before[2], [before, after])
    check("Text unabhängig skaliert", designer.template.area(TEXT) != text_before and
          designer.template.area(IMAGE) == after, [text_before, designer.template.area(TEXT)])
    shot("04_bild_und_text_verschoben_skaliert")

    designer.apply_layout("text_over")
    designer.select(TEXT)
    QTest.mouseClick(designer.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier,
                     designer.canvas.item_rect(TEXT).center().toPoint())
    check("Überlagerung: Alt+Klick wählt das verdeckte Symbol", designer.canvas.selected == IMAGE)
    designer.select(TEXT)
    shot("05_ueberlagerung_text_ueber_symbol")

    tiles = QImage(4 * 132 + 8, 150, QImage.Format.Format_ARGB32)
    tiles.fill(QColor("#101010"))
    painter = QPainter(tiles)
    painter.setPen(QColor("#e0e0e0"))
    layout_ok = True
    for index, layout in enumerate(LAYOUTS[:4]):
        QTest.mouseClick(designer.layout_buttons[layout.key], Qt.MouseButton.LeftButton)
        layout_ok &= designer.template.area(IMAGE) == layout.image and designer.template.area(TEXT) == layout.text
        painter.drawImage(8 + index * 132, 8, render_template(designer.template, 116))
        painter.drawText(8 + index * 132, 142, layout.label[:22])
    painter.end()
    tiles.save(str(shots / "06_vier_layoutvorlagen.png"))
    report["screenshots"].append("screenshots/06_vier_layoutvorlagen.png")
    check("Alle vier Grundlayouts angewendet", layout_ok)

    QTest.mouseClick(designer.layout_buttons["image_top"], Qt.MouseButton.LeftButton)
    QTest.mouseClick(designer.eye_buttons[TEXT], Qt.MouseButton.LeftButton)
    check("Text ausgeblendet, Inhalt erhalten", not designer.template.visible(TEXT) and
          designer.template.text == "Mikro aus")
    shot("07_text_ausgeblendet")
    QTest.mouseClick(designer.eye_buttons[TEXT], Qt.MouseButton.LeftButton)

    designer.set_background(0xFF0B3D91)
    designer.set_image_color(0xFFFFD54F)
    designer.set_text_color(0xFFFFFFFF)
    designer.set_font_size(4)
    designer.set_font_name("Segoe UI")
    check("Farben und Schrift geändert", (designer.template.background, designer.template.image_color,
                                          designer.template.font_size) == (0xFF0B3D91, 0xFFFFD54F, 4))
    designer.set_preview_mode(True)
    shot("08_vorschaumodus_ohne_rahmen")
    designer.set_preview_mode(False)

    undo_count = designer.undo_stack.index()
    snapshot = designer.template.snapshot()
    for _ in range(3):
        designer.undo_stack.undo()
    for _ in range(3):
        designer.undo_stack.redo()
    check("Undo/Redo", designer.template.snapshot() == snapshot and designer.undo_stack.index() == undo_count,
          undo_count)

    lab.output_edit.setText(str(samples))
    lab.output = samples
    lab.stem_edit.setText("mikro_aus")
    lab.symbol_name.setText("Loupedeck.BeispielPlugin.MikroAusCommand")
    result = lab.export(ict=True, png=True, svg=True, symbol=True)
    check("Export ICT/PNG/SVG/Action-Symbol", not result.errors and len(result.files) == 6,
          [p.name for p in result.files] + result.errors)
    check("Exportierte ICT erneut geöffnet: identisch", "identisch" in lab.ict_result.text(), lab.ict_result.text())
    check("PNG 116 entspricht Editoransicht", "0.000 %" in lab.compare_text.text(), lab.compare_text.text())
    lab.tabs.setCurrentIndex(0)
    shot("09_lab_export_ergebnisvorschau")
    lab.tabs.setCurrentIndex(1)
    shot("10_lab_ict_pruefung")

    png_entry = designer.library.find_entry(lambda e: e.package_id == "Windows11SamplePack" and e.format == "png") or \
        designer.library.find_entry(lambda e: e.format == "png" and e.package_id != "studio-startsymbole")
    designer._library_icon(png_entry)
    designer.apply_layout("image_center")
    check("PNG aus anderem Paket im Designer", designer.template.image_info().format == "png" and
          png_entry.package_id != svg_entry.package_id, "%s / %s" % (png_entry.package_id, png_entry.path.name))
    designer.select(IMAGE)
    shot("11_png_aus_windows11_paket")

    gif_entry = designer.library.find_entry(lambda e: e.format == "gif")
    if gif_entry:
        for section in designer.library.sections:
            if section.package.id == gif_entry.package_id:
                section.header.setChecked(True)
        designer.library.show_preview(gif_entry)
        frames = []
        for _ in range(4):
            pump(0.35)
            movie = designer.library._movie
            frames.append((movie.currentFrameNumber() if movie else -1, movie.currentImage().copy() if movie else QImage()))
        strip = QImage(4 * 80, 80, QImage.Format.Format_ARGB32)
        strip.fill(QColor("#202020"))
        painter = QPainter(strip)
        for index, (_, image) in enumerate(frames):
            if not image.isNull():
                painter.drawImage(index * 80, 0, image.scaled(80, 80))
        painter.end()
        strip.save(str(shots / "12_gif_vorschau_einzelbilder.png"))
        report["screenshots"].append("screenshots/12_gif_vorschau_einzelbilder.png")
        numbers = [n for n, _ in frames]
        check("Animiertes GIF in der Bibliotheksvorschau (QMovie läuft)", len(set(numbers)) > 1, numbers)
        shot("13_gif_paket_bibliothek")
        sizes = sorted(p.stat().st_size for p in gif_entry.path.parent.glob("*.gif"))
        report["gif_sizes_kb"] = {"min": round(sizes[0] / 1024), "max": round(sizes[-1] / 1024), "count": len(sizes)}
        refused = designer.import_image(gif_entry.path, gif_mode="original", origin=gif_entry.package_id)
        check("Installiertes GIF > 150 KB: Original-Einbettung begründet abgelehnt",
              refused is None and "150-KB-Grenze" in designer.last_error, designer.last_error)
        sys.path.insert(0, str(ROOT / "tests"))
        from test_symbol_designer_core import animated_gif
        small = work / "klein_animiert.gif"
        small.write_bytes(animated_gif())
        designer.import_image(small, gif_mode="original")
        gif_dir = work / "gif-export"
        gif_report = designer.export_bundle(ExportOptions(gif_dir, "animiert", True, (116,), True))
        embedded = IconTemplate.load(gif_dir / "animiert.ict").image_info()
        check("GIF ≤ 150 KB: ICT behält Original-GIF, PNG/SVG Standbild mit Hinweis",
              embedded.format == "gif" and embedded.animated and any("erste Bild" in n for n in gif_report.notes),
              gif_report.notes)
        designer.import_image(gif_entry.path, gif_mode="still", origin=gif_entry.package_id)
        check("GIF bewusst als Standbild (PNG) übernommen", designer.template.image_info().format == "png")
    designer.import_image(svg_entry.path, origin=svg_entry.package_id)

    lab.add_samples()
    targets = designer.style_targets
    fingerprints = [content_fingerprint(t.template) for t in targets]
    dialog = StyleTransferDialog(designer.template, targets, designer)
    dialog.resize(1000, 600)
    dialog.show()
    dialog.list.setCurrentRow(2)
    shot("14_fuer_mehrere_uebernehmen_dialog", dialog)
    aspects = dialog.aspects()
    selected = dialog.selected_targets()
    dialog.close()
    index = designer.undo_stack.index()
    designer.apply_style_to(selected, aspects)
    lab.refresh_targets()
    intact = all(content_fingerprint(t.template) == f for t, f in zip(targets, fingerprints))
    check("Gestaltung auf 4 Ziele übertragen, Inhalte unverändert", intact and designer.undo_stack.index() == index + 1,
          lab.content_check.text())
    lab.tabs.setCurrentIndex(2)
    shot("15_stiluebertragung_ergebnis")
    for number, target in enumerate(targets, 1):
        target.template.save(samples / "stilziele" / ("%02d_%s.ict" % (number, target.name.split(": ")[-1].replace(" ", "_"))))
        render_template(target.template, 116).save(str(samples / "stilziele" / ("%02d_vorschau.png" % number)))
    designer.undo_stack.undo()
    check("Stilübertragung als ein Schritt rückgängig", all(not t.modified for t in targets))
    designer.undo_stack.redo()

    lab.tabs.setCurrentIndex(3)
    lab.refresh_library_report()
    shot("16_bibliothek_bericht")
    (out / "library_report.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    for name, size in (("17_skalierung_klein", (1100, 760)), ("18_skalierung_gross", (1900, 1150))):
        lab.resize(*size)
        pump(0.3)
        designer.select(IMAGE)
        shot(name)
    lab.resize(1600, 1000)

    real = []
    for base in [Path(os.path.expandvars(r"%LOCALAPPDATA%\Logi\LogiPluginService"))]:
        if base.is_dir():
            real += [p for p in base.rglob("*.ict")]
    identical, semantic, failed = 0, 0, []
    for path in real:
        raw = path.read_bytes()
        try:
            template = IconTemplate.from_bytes(raw)
            if template.to_bytes() == raw:
                identical += 1
            elif json.loads(template.to_bytes()) == json.loads(raw.decode("utf-8-sig")):
                semantic += 1
            render_template(template, 116)
        except Exception as exc:
            failed.append("%s: %s" % (path.name, exc))
    check("Echte ICT-Dateien importiert und wieder exportiert (nur lesend)", not failed and real,
          {"dateien": len(real), "byte_identisch": identical, "inhaltlich_identisch_andere_einrueckung": semantic,
           "fehler": failed})
    if real:
        sample = next((p for p in real if "AddDesktop" in p.name), real[0])
        designer.load_ict(sample)
        copy = work / "echte_vorlage.ict"
        designer.save_ict(copy)
        check("Echte Vorlage im Designer geöffnet und unverändert gespeichert",
              copy.read_bytes() == sample.read_bytes(), sample.name)
        shot("19_echte_logitech_vorlage_geoeffnet")

    env_root = work / "env-library"
    for package in scan.packages:
        if not package.bundled and package.entries:
            target = env_root / ("Kopie_" + package.id)
            target.mkdir(parents=True)
            shutil.copy(package.entries[0].path, target / package.entries[0].path.name)
            break
    (env_root / "Defekt" / "metadata").mkdir(parents=True)
    (env_root / "Defekt" / "metadata" / "LoupedeckPackage.yaml").write_bytes(b"\x00\xff kaputt")
    (env_root / "Defekt" / "kaputt.png").write_bytes(b"\x89PNG\r\n\x1a\nkaputt")
    os.environ[ENV_VAR] = str(env_root)
    env_scan = scan_library(default_library_root())
    del os.environ[ENV_VAR]
    check("Bibliothekspfad per %s austauschbar; defektes Paket isoliert" % ENV_VAR,
          env_scan.root == env_root and len([p for p in env_scan.packages if not p.bundled]) == 2,
          env_scan.summary())

    hashes_after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in installed_files}
    check("Keine Originaldateien der Icon-Bibliothek verändert", hashes_before == hashes_after,
          "%d Dateien geprüft" % len(installed_files))
    from symbol_designer.widget import SymbolDesignerWidget
    standalone = SymbolDesignerWidget()
    standalone.ask_user = False
    standalone.resize(1440, 880)
    standalone.show()
    pump(0.8)
    standalone._library_icon(svg_entry)
    standalone.set_text("Mikro aus")
    standalone.set_background(0xFF0B3D91)
    standalone.set_image_color(0xFFFFD54F)
    standalone.select(IMAGE)
    shot("00_symbol_designer_widget_eigenstaendig", standalone)
    standalone.close()
    report["ok"] = all(c["ok"] for c in report["checks"].values())
    (out / "gui_check_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str),
                                               encoding="utf-8")
    lab.close()
    shutil.rmtree(work, ignore_errors=True)
    print("Bericht:", out / "gui_check_report.json", "–", "ALLE PRÜFUNGEN OK" if report["ok"] else "FEHLER")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
