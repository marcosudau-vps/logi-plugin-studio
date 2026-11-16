"""AP-POLISH-001 / AP-09: capture the real Studio window in typical states.

Offscreen Qt (no desktop interaction). Writes PNG screenshots and a JSON list
of technical observations (window size, disabled actions, empty-state texts,
clipped labels heuristics) for the technical GUI review. It does not judge UX.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main(out: Path) -> int:
    from PySide6.QtWidgets import QApplication, QLabel, QAbstractButton
    app = QApplication.instance() or QApplication([])
    temp = Path(tempfile.mkdtemp(prefix="gui-capture-"))
    os.environ["LOGI_STUDIO_DATA"] = str(temp / "data")
    os.environ["LOGI_SHARED_HOME"] = str(temp / "shared")
    from studio.native_shell import NativeStudioShell
    out.mkdir(parents=True, exist_ok=True)
    findings = {"states": {}}

    def survey(window, name):
        window.resize(1280, 820)
        app.processEvents()
        window.grab().save(str(out / f"{name}.png"))
        clipped = []
        for widget in window.findChildren(QLabel) + window.findChildren(QAbstractButton):
            if not widget.isVisible() or widget.wordWrap() if isinstance(widget, QLabel) else not widget.isVisible():
                continue
            text = widget.text()
            if text and widget.width() > 0 and widget.fontMetrics().horizontalAdvance(text.split("\n")[0]) > widget.width() + 2:
                clipped.append({"type": type(widget).__name__, "name": widget.objectName(), "text": text[:80],
                                "needed": widget.fontMetrics().horizontalAdvance(text.split("\n")[0]),
                                "width": widget.width()})
        toolbar = [{"text": a.text(), "enabled": a.isEnabled()} for a in window.findChildren(type(window.save_action))
                   if a.text()]
        findings["states"][name] = {"title": window.windowTitle(), "status": window.statusBar().currentMessage(),
                                    "tab": window.tabs.tabText(window.tabs.currentIndex()),
                                    "tabs": [window.tabs.tabText(i) for i in range(window.tabs.count())],
                                    "minimum": [window.minimumSizeHint().width(), window.minimumSizeHint().height()],
                                    "clipped_single_line_widgets": clipped[:30], "actions": toolbar[:40]}

    empty = NativeStudioShell()
    empty.show()
    survey(empty, "01_start_ohne_projekt")
    sample = json.loads((ROOT / "examples/project_logitech_native_v1.json").read_text(encoding="utf-8"))
    project = temp / "projekt" / "project.json"
    project.parent.mkdir()
    project.write_text(json.dumps(sample), encoding="utf-8")
    assert empty.open_project(str(project))
    survey(empty, "02_projekt_geoeffnet")
    for index in range(empty.tabs.count()):
        empty.tabs.setCurrentIndex(index)
        app.processEvents()
        label = empty.tabs.tabText(index).replace("/", "-").replace(" ", "_")
        survey(empty, f"03_tab_{index:02d}_{label}")
    empty.resize(900, 600)
    app.processEvents()
    empty.grab().save(str(out / "04_kleines_fenster_900x600.png"))
    findings["small_window_minimum_hint"] = [empty.minimumSizeHint().width(), empty.minimumSizeHint().height()]
    empty.close()
    (out / "gui_findings.json").write_text(json.dumps(findings, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: {"tab": v["tab"], "clipped": len(v["clipped_single_line_widgets"])}
                      for k, v in findings["states"].items()}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
