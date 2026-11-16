"""Shared fixtures for AP-RELEASE-FINAL-001 tests (not a test module itself)."""
from __future__ import annotations

import json
import shutil
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def png(width: int, height: int, rgba: tuple[int, int, int, int]) -> bytes:
    raw = b"".join(b"\0" + bytes(rgba) * width for _ in range(height))
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
       '<rect x="2" y="2" width="20" height="20" fill="{color}"/></svg>')
ICT = {"version": 1, "items": [{"type": "text", "text": "{name}", "color": "#FFFFFF"}]}


def resource_project(directory: Path, plugin_id: str, *, display: str = "Release-Test") -> Path:
    """Native project with icons, symbols, ICTs, state images and a license."""
    directory.mkdir(parents=True, exist_ok=True)
    assets = directory / "assets"
    assets.mkdir(exist_ok=True)
    (assets / "command.png").write_bytes(png(80, 80, (30, 120, 220, 255)))
    (assets / "state-off.png").write_bytes(png(80, 80, (60, 60, 60, 255)))
    (assets / "state-on.png").write_bytes(png(80, 80, (20, 200, 80, 255)))
    (assets / "command.svg").write_text(SVG.format(color="#1E78DC"), encoding="utf-8")
    (assets / "first.svg").write_text(SVG.format(color="#DC781E"), encoding="utf-8")
    (assets / "adjust.svg").write_text(SVG.format(color="#8E44AD"), encoding="utf-8")
    (assets / "command.ict").write_text(json.dumps(ICT), encoding="utf-8")
    (assets / "default.ict").write_text(json.dumps({"version": 1, "items": []}), encoding="utf-8")
    (directory / "LICENSE-TEST.txt").write_text("test license", encoding="utf-8")
    raw = json.loads((ROOT / "examples/project_logitech_native_v1.json").read_text(encoding="utf-8"))
    raw["plugin"]["id"] = plugin_id
    raw["plugin"]["display_name"] = display
    raw["plugin"]["default_icon_template"] = "assets/default.ict"
    raw["licenses"] = ["LICENSE-TEST.txt"]
    command, multistate, adjustment = raw["actions"][0], raw["actions"][1], raw["actions"][2]
    command.update(icon="assets/command.png", icon_template="assets/command.ict", symbol="assets/command.svg",
                   parameter_symbols={"first": "assets/first.svg"})
    multistate["states"][0]["image"] = "assets/state-off.png"
    multistate["states"][1]["image"] = "assets/state-on.png"
    adjustment["symbol"] = "assets/adjust.svg"
    path = directory / "project.json"
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return path


def copy_tree(source: Path, target: Path) -> Path:
    shutil.copytree(source, target)
    return target
