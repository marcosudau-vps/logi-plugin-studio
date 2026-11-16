"""Read-only discovery of installed Logitech/Loupedeck icon packages.

Only directory listings and the small ``metadata/LoupedeckPackage.yaml`` files
are read while scanning; image data is decoded lazily by the GUI. Nothing in a
package directory is ever written.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ENV_VAR = "LOGI_ICON_LIBRARY_ROOT"
FORMATS = {".svg": "svg", ".png": "png", ".gif": "gif", ".jpg": "jpeg", ".jpeg": "jpeg",
           ".webp": "webp", ".bmp": "bmp"}
SKIP_DIRS = {"metadata", "__macosx", ".git"}
BUNDLED_ROOT = Path(__file__).resolve().parent / "assets" / "symbols"
BUNDLED_ID = "studio-startsymbole"


@dataclass(frozen=True)
class IconEntry:
    name: str
    path: Path
    format: str
    package_id: str
    category: str = ""

    @property
    def search_text(self) -> str:
        return ("%s %s %s %s" % (self.name, self.category, self.package_id, self.format)).lower()


@dataclass
class IconPackage:
    id: str
    display_name: str
    root: Path
    metadata: dict = field(default_factory=dict)
    entries: list[IconEntry] = field(default_factory=list)
    unsupported: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    bundled: bool = False

    def meta(self, key: str) -> str:
        value = self.metadata.get(key)
        return value if isinstance(value, str) else ""

    @property
    def license_text(self) -> str:
        license_name = self.meta("license") or "keine Lizenzangabe im Paket"
        return license_name + (" (%s)" % self.meta("licenseUrl") if self.meta("licenseUrl") else "")

    def formats(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.entries:
            counts[entry.format] = counts.get(entry.format, 0) + 1
        return counts


@dataclass
class LibraryScan:
    root: Path | None
    packages: list[IconPackage] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def icon_count(self) -> int:
        return sum(len(p.entries) for p in self.packages)

    def search(self, query: str) -> list[IconEntry]:
        words = query.lower().split()
        return [e for p in self.packages for e in p.entries if all(w in e.search_text for w in words)]

    def summary(self) -> dict:
        return {"root": str(self.root) if self.root else None, "packages": len(self.packages),
                "icons": self.icon_count, "errors": list(self.errors) + [
                    "%s: %s" % (p.display_name, e) for p in self.packages for e in p.errors],
                "by_package": {p.display_name: {"id": p.id, "icons": len(p.entries), "formats": p.formats(),
                                                "unsupported": len(p.unsupported)} for p in self.packages}}


def default_library_root(environ=None) -> Path | None:
    """``LOGI_ICON_LIBRARY_ROOT`` or ``%LOCALAPPDATA%\\Logi\\LogiPluginService\\Media\\Icons``."""
    environ = os.environ if environ is None else environ
    configured = environ.get(ENV_VAR, "").strip()
    if configured:
        return Path(os.path.expandvars(configured))
    local = environ.get("LOCALAPPDATA", "").strip()
    return Path(local) / "Logi" / "LogiPluginService" / "Media" / "Icons" if local else None


def read_metadata(path: Path) -> dict:
    """Flat ``key: value`` YAML as written by Logitech packages (no external YAML dependency)."""
    result: dict[str, str] = {}
    text = path.read_bytes().decode("utf-8-sig", "replace")
    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or line[:1] in (" ", "\t", "-"):
            continue
        if ":" not in stripped:
            raise ValueError("Zeile %d ist kein 'Schlüssel: Wert'-Eintrag" % line_no)
        key, value = stripped.split(":", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        result[key.strip()] = value
    return result


def _walk(directory: Path, base: Path, package: IconPackage) -> None:
    try:
        children = sorted(directory.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        package.errors.append("Ordner nicht lesbar: %s (%s)" % (directory, exc.strerror or exc))
        return
    for child in children:
        if child.name.startswith((".", "._")):
            continue
        if child.is_dir():
            if child.name.lower() not in SKIP_DIRS:
                _walk(child, base, package)
            continue
        fmt = FORMATS.get(child.suffix.lower())
        if fmt is None:
            package.unsupported.append(child)
            continue
        category = "/".join(child.parent.relative_to(base).parts)
        package.entries.append(IconEntry(child.stem, child, fmt, package.id, category))


def scan_package(directory: Path, bundled: bool = False) -> IconPackage:
    package = IconPackage(directory.name, directory.name, directory, bundled=bundled)
    meta_file = directory / "metadata" / "LoupedeckPackage.yaml"
    if meta_file.is_file():
        try:
            package.metadata = read_metadata(meta_file)
        except (OSError, ValueError) as exc:
            package.errors.append("Metadaten fehlerhaft: %s" % exc)
    else:
        package.errors.append("metadata/LoupedeckPackage.yaml fehlt – Ordnername wird angezeigt")
    kind = package.meta("type")
    if kind and kind.lower() != "iconlibrary":
        package.errors.append("Pakettyp '%s' ist keine Icon-Bibliothek; Bilder werden trotzdem angezeigt" % kind)
    package.display_name = package.meta("displayName") or package.meta("name") or directory.name
    package.id = package.meta("name") or directory.name
    _walk(directory, directory, package)
    return package


def scan_library(root: str | Path | None = None, include_bundled: bool = True) -> LibraryScan:
    root_path = Path(root) if root is not None else default_library_root()
    scan = LibraryScan(root_path)
    if include_bundled and BUNDLED_ROOT.is_dir():
        bundled = scan_package(BUNDLED_ROOT, bundled=True)
        bundled.id = BUNDLED_ID
        bundled.errors = [e for e in bundled.errors if "fehlt" not in e]
        bundled.entries = [IconEntry(e.name, e.path, e.format, BUNDLED_ID, e.category) for e in bundled.entries]
        scan.packages.append(bundled)
    if root_path is None:
        scan.errors.append("Kein Bibliothekspfad: %s ist nicht gesetzt und LOCALAPPDATA fehlt" % ENV_VAR)
        return scan
    if not root_path.is_dir():
        scan.errors.append("Bibliothekspfad nicht gefunden: %s" % root_path)
        return scan
    try:
        directories = sorted((p for p in root_path.iterdir() if p.is_dir() and not p.name.startswith(".")),
                             key=lambda p: p.name.lower())
    except OSError as exc:
        scan.errors.append("Bibliothekspfad nicht lesbar: %s" % exc)
        return scan
    installed = []
    for directory in directories:
        try:
            installed.append(scan_package(directory))
        except Exception as exc:  # one broken package must never hide the others
            scan.errors.append("Paket %s übersprungen: %s" % (directory.name, exc))
    scan.packages.extend(sorted(installed, key=lambda p: p.display_name.lower()))
    return scan
