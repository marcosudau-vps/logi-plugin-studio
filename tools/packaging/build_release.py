"""ONE release command for both Windows editions (AP-POLISH-001 / AP-01).

    python tools/packaging/build_release.py [--out DIR] [--skip-setup]

1. PyInstaller (free) builds the Studio onedir and – separately – the
   stdlib-only host runtime onedir from ``LogiPluginStudio.spec``.
2. One application payload is assembled (Studio + ``hostruntime/`` + docs +
   licenses); its file hashes are recorded once.
3. Portable edition: ``LogiPluginStudio-Portable-<v>.zip`` contains exactly
   that payload under ``LogiPluginStudio-<v>/``.
4. Setup edition: Inno Setup (free) packs exactly the same payload into
   ``LogiPluginStudio-Setup-<v>.exe``; the installer adds only the marker file
   ``studio-edition.json`` and the Windows integration (Start menu, uninstall).
5. ``release_manifest.json`` records versions, toolchain, source hash,
   payload hash list, artifact SHA-256 values and the edition difference.

The version comes from ``src/studio/version.py`` only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGING = ROOT / "tools" / "packaging"
sys.path.insert(0, str(ROOT / "src"))

from studio.version import PRODUCT_NAME, VERSION, VERSION_NUMERIC  # noqa: E402
from adapters.logitech.host_runtime import (DISTRIBUTION_FILE, RUNTIME_DIR_NAME, load_distribution,  # noqa: E402
                                            write_distribution)

DEFAULT_OUT = ROOT / "work" / "polish" / "AP-POLISH-001" / "outputs"
STDLIB_EXCLUDE = {"test", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3", "site-packages",
                  "__pycache__", "venv", "pydoc_data", "unittest"}
SOURCE_TREES = ("src", "tools/packaging", "component_types", "docs/ANWENDERHANDBUCH.md")
PORTABLE_NAME = f"LogiPluginStudio-Portable-{VERSION}.zip"
SETUP_NAME = f"LogiPluginStudio-Setup-{VERSION}.exe"
PAYLOAD_DIR = f"LogiPluginStudio-{VERSION}"
INNO_CANDIDATES = (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
                   Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
                   Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe")

NOTICE = """# Drittanbieter-Hinweise – {product} {version}

Gilt gleichermaßen für die Setup- und die Portable-Fassung (identischer Programminhalt).

| Komponente | Lizenz | Hinweis |
|---|---|---|
| CPython {python} (Laufzeit, Standardbibliothek, `stdlib.zip`) | PSF License | `licenses/Python-LICENSE.txt` |
| Qt 6 / PySide6 / shiboken6 {pyside} | LGPL-3.0-only (Community-Lizenz) | Austauschbare DLLs/PYDs in `_internal`. Volltexte: `licenses/LGPL-3.0-only.txt` und `licenses/GPL-3.0-only.txt`. Quellcode: https://code.qt.io und https://download.qt.io/official_releases/QtForPython/ |
| PyInstaller-Bootloader {pyinstaller} | GPL-2.0 mit Bootloader-Ausnahme | `licenses/PyInstaller-COPYING.txt` |
| Microsoft Visual C++ Laufzeit (`VCRUNTIME140*.dll`, von CPython mitgeliefert) | Microsoft Visual C++ Redistributable (Distributable Code) | unverändert aus der CPython-Distribution |
| OpenSSL (`libcrypto-3`, `libssl-3`, von CPython mitgeliefert) | Apache-2.0 | in `licenses/Python-LICENSE.txt` (Abschnitt OpenSSL) |
| Inno Setup {inno} (nur Setup-Fassung: Installer/Deinstaller) | Inno Setup License (kostenlos, auch kommerziell) | https://jrsoftware.org/files/is/license.txt |

**Pluginlokale Host-Laufzeit (`hostruntime/`).** Jedes mit dem Studio gebaute Plugin erhält eine
geprüfte Kopie dieses Ordners (nur CPython-Standardbibliothek, PyInstaller-Bootloader, VC-Laufzeit,
OpenSSL – kein Qt/PySide6). Die zugehörigen Lizenztexte liegen in `hostruntime/licenses/` und
werden mit kopiert.

**Nicht enthalten (werden lokal erkannt, nie mitgeliefert):** Logitech `PluginApi.dll`, Logi Plugin Service,
Logi Options+, LogiPluginTool, Logitech-Keypad-Grafiken, .NET SDK. Diese sind vom Anwender kostenlos bei
Logitech bzw. Microsoft zu beziehen; das Studio prüft ihr Vorhandensein (`Diagnose.cmd`).

Qt Virtual Keyboard ist ausgeschlossen. Die beiden GNU-Lizenztexte stammen aus dem Verzeichnis
`LICENSES` des offiziellen Qt-Base-Repositorys. Die Programmdateien sind nicht digital signiert;
Windows SmartScreen kann beim ersten Start bzw. bei der Installation warnen.
"""

README = """{product} {version}
{line}

Start:        LogiPluginStudio.exe   (optional Projektdatei als Argument)
Diagnose:     Diagnose.cmd           (Logi Plugin Service, PluginApi.dll, .NET SDK, Host-Laufzeit)
Selbsttest:   Selbsttest.cmd         (baut Testplugins in einem Temp-Ordner; keine Installation)

Diese Datei liegt in beiden Fassungen bei:
  * Portable: ZIP entpacken, LogiPluginStudio.exe starten. Kein Setup, keine Adminrechte.
    Der Ordner darf verschoben werden; das Studio findet seine Bestandteile neben der EXE.
  * Setup: über LogiPluginStudio-Setup-{version}.exe installiert (Standard ohne Adminrechte nach
    %LOCALAPPDATA%\\Programs\\LogiPluginStudio), Deinstallation über Windows-Einstellungen.

Voraussetzungen auf dem Zielrechner (kostenlos, nicht enthalten):
  * Logi Options+ mit Logi Plugin Service (stellt PluginApi.dll bereit)
  * .NET SDK 8 oder neuer (nur zum Erzeugen/Bauen von Plugins)
Python, PySide6 oder eine IDE werden NICHT benötigt.

Plugins und Studio-Ort: Jedes gebaute Plugin enthält seine eigene, geprüfte Host-Laufzeit
(bin\\hostruntime-<id>). Installierte Plugins laufen daher ohne geöffnetes Studio weiter – auch
wenn dieser Ordner verschoben, aktualisiert oder entfernt wird.

Benutzerdaten (beide Fassungen, NICHT im Programmordner): %LOCALAPPDATA%\\LogiPluginStudio
  builds\\      Build-Ausgaben, Pakete und Installationsbelege
  SharedFolders\\  Pairing-/Berechtigungsdaten (Schlüssel DPAPI-geschützt), Status, Protokolle
  HostLogs\\    Protokolle der pluginlokalen Hosts
  settings\\    Plugin-Typ (Buildmodus) je Projekt
Installierte Plugins: %LOCALAPPDATA%\\Logi\\LogiPluginService\\Plugins\\<Name>
Die Portable-Fassung ist deshalb NICHT rückstandsfrei: Diese Daten bleiben nach dem Löschen des
Programmordners erhalten und werden nur auf ausdrücklichen Wunsch entfernt.
Ausführliche Anleitung: ANWENDERHANDBUCH.md
"""

HOSTRUNTIME_README = """Logitech Plugin Studio – Host-Laufzeit {version}

Stdlib-only Python-Laufzeit (CPython {python}) für die eingebetteten Python-Hosts der
mit dem Studio gebauten Plugins. Jedes Plugin erhält beim Build eine geprüfte Kopie
dieses Ordners (bin\\hostruntime-<id>); die Datei {manifest} listet SHA-256 je Datei.
Enthält kein Qt/PySide6 und keine Studio-Module. Lizenzen: licenses\\.
"""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hashes(directory: Path) -> dict[str, str]:
    return {p.relative_to(directory).as_posix(): sha256(p) for p in sorted(directory.rglob("*")) if p.is_file()}


def source_digest() -> tuple[str, int]:
    digest, count = hashlib.sha256(), 0
    for item in SOURCE_TREES:
        base = ROOT / item
        files = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.is_file()
                                                     and "__pycache__" not in p.parts)
        for file in files:
            digest.update(file.relative_to(ROOT).as_posix().encode() + b"\0" + sha256(file).encode() + b"\n")
            count += 1
    return digest.hexdigest(), count


def stdlib_zip(target: Path) -> int:
    lib = Path(sys.base_prefix) / "Lib"
    count = 0
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(lib.rglob("*.py")):
            relative = file.relative_to(lib)
            if relative.parts[0] in STDLIB_EXCLUDE or "__pycache__" in relative.parts or "tests" in relative.parts:
                continue
            info = zipfile.ZipInfo(relative.as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            archive.writestr(info, file.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
            count += 1
    return count


def pyinstaller(out: Path) -> Path:
    build, dist = out / "pyinstaller" / "build", out / "pyinstaller" / "dist"
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
               "--workpath", str(build), "--distpath", str(dist), str(PACKAGING / "LogiPluginStudio.spec")]
    # Dependency scanning must not resolve Windows DLL names to unrelated
    # binaries on the caller's PATH, e.g. a private ICU build from another app.
    windows = Path(os.environ["SystemRoot"])
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join(map(str, (windows / "System32", windows, Path(sys.executable).parent)))
    env.pop("PYTHONPATH", None)
    log = out / "pyinstaller-build.log"
    with log.open("w", encoding="utf-8") as handle:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=handle, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise SystemExit(f"PyInstaller failed ({result.returncode}); see {log}")
    return dist


def assemble(dist: Path, payload: Path) -> dict:
    import PyInstaller
    import PySide6
    if payload.exists():
        shutil.rmtree(payload)
    shutil.copytree(dist / "LogiPluginStudio", payload)
    runtime = payload / RUNTIME_DIR_NAME
    shutil.copytree(dist / "hostruntime", runtime)
    modules = stdlib_zip(runtime / "_internal" / "stdlib.zip")
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    pyi_license = next(Path(PyInstaller.__file__).parents[1].glob("pyinstaller-*.dist-info/licenses/COPYING.txt"), None)
    for licenses in (payload / "licenses", runtime / "licenses"):
        licenses.mkdir(exist_ok=True)
        shutil.copyfile(python_license, licenses / "Python-LICENSE.txt")
        if pyi_license:
            shutil.copyfile(pyi_license, licenses / "PyInstaller-COPYING.txt")
    for name in ("LGPL-3.0-only.txt", "GPL-3.0-only.txt"):
        shutil.copyfile(PACKAGING / "licenses" / name, payload / "licenses" / name)
    (runtime / "README-HOSTRUNTIME.txt").write_text(HOSTRUNTIME_README.format(
        version=VERSION, python=sys.version.split()[0], manifest=DISTRIBUTION_FILE), encoding="utf-8")
    distribution = write_distribution(runtime, version=VERSION, python=sys.version.split()[0])
    shutil.copytree(ROOT / "component_types", payload / "component_types", dirs_exist_ok=True)
    (payload / "THIRD_PARTY_NOTICES.md").write_text(NOTICE.format(
        product=PRODUCT_NAME, version=VERSION, python=sys.version.split()[0], pyside=PySide6.__version__,
        pyinstaller=PyInstaller.__version__, inno=inno_version() or "6"), encoding="utf-8")
    title = f"{PRODUCT_NAME} {VERSION}"
    (payload / "README.txt").write_text(README.format(product=PRODUCT_NAME, version=VERSION,
                                                       line="=" * len(title)), encoding="utf-8")
    shutil.copyfile(ROOT / "docs" / "ANWENDERHANDBUCH.md", payload / "ANWENDERHANDBUCH.md")
    (payload / "Diagnose.cmd").write_text(
        '@echo off\r\nset REPORT=%TEMP%\\LogiPluginStudio-diagnose.txt\r\n'
        '"%~dp0LogiPluginStudio.exe" --diagnose --out "%REPORT%"\r\n'
        'echo Ergebnis (Exitcode %ERRORLEVEL%):\r\ntype "%REPORT%"\r\npause\r\n', encoding="ascii")
    (payload / "Selbsttest.cmd").write_text(
        '@echo off\r\nset WORKDIR=%TEMP%\\LogiPluginStudio-selftest-%RANDOM%%RANDOM%\r\n'
        'echo Selbsttest laeuft (Arbeitsordner %WORKDIR%) ...\r\n'
        '"%~dp0LogiPluginStudio.exe" --selftest --work "%WORKDIR%" --out "%WORKDIR%\\report.json"\r\n'
        'echo Exitcode %ERRORLEVEL% - Bericht: %WORKDIR%\\report.json\r\ntype "%WORKDIR%\\report.json"\r\npause\r\n',
        encoding="ascii")
    forbidden = sorted(p for p in tree_hashes(payload) if p.lower().endswith("pluginapi.dll")
                       or ("logiplugin" in p.lower() and p.lower().endswith(".dll"))
                       or "virtualkeyboard" in p.lower())
    if forbidden:
        raise SystemExit(f"Forbidden binaries in payload: {forbidden}")
    qt_in_runtime = [name for name in distribution["files"] if "qt" in name.lower() or "pyside" in name.lower()]
    if qt_in_runtime:
        raise SystemExit(f"Host runtime must not contain Qt/PySide6: {qt_in_runtime}")
    third_party = [p for p in tree_hashes(payload) if "pywin32" in p.lower() or "/win32/" in p.lower()]
    if third_party:
        raise SystemExit(f"Unexpected non-stdlib binaries (pywin32) in payload: {third_party}")
    return {"stdlib_modules": modules, "runtime": {k: distribution[k] for k in ("runtime_id", "version", "python")},
            "runtime_files": len(distribution["files"]),
            "runtime_bytes": sum((runtime / n).stat().st_size for n in distribution["files"])}


def portable(payload: Path, candidate: Path) -> Path:
    archive = candidate / PORTABLE_NAME
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        for file in sorted(p for p in payload.rglob("*") if p.is_file()):
            handle.write(file, f"{PAYLOAD_DIR}/{file.relative_to(payload).as_posix()}")
    return archive


def inno_compiler() -> Path | None:
    return next((p for p in INNO_CANDIDATES if p.is_file()), None)


def inno_version() -> str | None:
    compiler = inno_compiler()
    if compiler is None:
        return None
    result = subprocess.run([str(compiler), "/?"], capture_output=True, text=True, errors="replace")
    first = (result.stdout or result.stderr).splitlines()
    return first[0].replace("Inno Setup ", "").replace(" Command-Line Compiler", "").strip() if first else None


def setup(payload: Path, candidate: Path, out: Path) -> Path:
    compiler = inno_compiler()
    if compiler is None:
        raise SystemExit("Inno Setup 6 (ISCC.exe) not found; install the free Inno Setup 6")
    script = PACKAGING / "LogiPluginStudio.iss"
    log = out / "inno-setup-build.log"
    command = [str(compiler), "/Q", f"/DAppVersion={VERSION}", f"/DAppVersionNumeric={VERSION_NUMERIC}",
               f"/DPayload={payload}", f"/DOutputDir={candidate}",
               f"/DOutputBaseFilename={Path(SETUP_NAME).stem}", str(script)]
    with log.open("w", encoding="utf-8") as handle:
        result = subprocess.run(command, cwd=PACKAGING, stdout=handle, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise SystemExit(f"Inno Setup failed ({result.returncode}); see {log}")
    return candidate / SETUP_NAME


def toolchain() -> dict:
    import PyInstaller
    import PySide6
    dotnet = None
    try:
        listed = subprocess.run(["dotnet", "--list-sdks"], capture_output=True, text=True, timeout=60).stdout
        dotnet = [line.split()[0] for line in listed.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        pass
    return {"python": sys.version.split()[0], "python_executable_name": Path(sys.executable).name,
            "pyside6": PySide6.__version__, "pyinstaller": PyInstaller.__version__, "inno_setup": inno_version(),
            "windows": platform.platform(), "dotnet_sdks_for_tests": dotnet,
            "cost": "free tooling only (PyInstaller, Inno Setup)"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--skip-setup", action="store_true", help="portable edition only")
    parser.add_argument("--reuse-dist", action="store_true", help="skip PyInstaller, reuse the previous dist")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    source_hash, source_files = source_digest()
    dist = out / "pyinstaller" / "dist" if args.reuse_dist else pyinstaller(out)
    payload = out / "payload" / PAYLOAD_DIR
    payload.parent.mkdir(parents=True, exist_ok=True)
    assembled = assemble(dist, payload)
    load_distribution(payload / RUNTIME_DIR_NAME)
    hashes = tree_hashes(payload)
    candidate = out / "release_candidate"
    candidate.mkdir(parents=True, exist_ok=True)
    (candidate / f"LogiPluginStudio-{VERSION}.payload.sha256.json").write_text(json.dumps(hashes, indent=1),
                                                                                 encoding="utf-8")
    archive = portable(payload, candidate)
    artifacts = {"portable_zip": {"file": archive.name, "sha256": sha256(archive), "bytes": archive.stat().st_size}}
    if not args.skip_setup:
        installer = setup(payload, candidate, out)
        artifacts["setup_exe"] = {"file": installer.name, "sha256": sha256(installer), "bytes": installer.stat().st_size}
    # License notices beside the artifacts (identical copies of the payload files).
    notices = candidate / "licenses"
    if notices.exists():
        shutil.rmtree(notices)
    shutil.copytree(payload / "licenses", notices)
    shutil.copyfile(payload / "THIRD_PARTY_NOTICES.md", candidate / "THIRD_PARTY_NOTICES.md")
    sums = "".join(f"{a['sha256']}  {a['file']}\n" for a in artifacts.values())
    (candidate / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")
    manifest = {
        "format": "logi-plugin-studio-release-1", "product": PRODUCT_NAME, "version": VERSION,
        "version_numeric": VERSION_NUMERIC, "status": "RELEASE_CANDIDATE_NOT_PUBLISHED",
        "built": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "seconds": round(time.time() - started, 1),
        "source": {"sha256": source_hash, "files": source_files, "trees": list(SOURCE_TREES)},
        "toolchain": toolchain(),
        "payload": {"directory": PAYLOAD_DIR, "files": len(hashes), "bytes": sum((payload / n).stat().st_size for n in hashes),
                    "sha256_list": f"LogiPluginStudio-{VERSION}.payload.sha256.json",
                    "tree_sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()},
        "host_runtime": assembled,
        "artifacts": artifacts,
        "editions": {
            "portable": {"artifact": PORTABLE_NAME, "payload": "identical", "adds": [],
                         "install": "unzip anywhere; no setup; no admin rights"},
            "setup": {"artifact": SETUP_NAME, "payload": "identical",
                      "adds": ["studio-edition.json (edition marker)", "Start menu / optional desktop shortcut",
                               "uninstall entry (HKCU)", "unins000.exe/.dat (Inno Setup uninstaller)"],
                      "install": "per-user, default %LOCALAPPDATA%\\Programs\\LogiPluginStudio, no admin rights"}},
        "logitech_binaries_included": [],
        "signed": False,
        "publication": "none (no upload, no tag)",
    }
    (candidate / "release_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    shutil.copyfile(candidate / "release_manifest.json", out / "release_manifest.json")
    print(json.dumps({k: manifest[k] for k in ("version", "seconds", "artifacts", "host_runtime")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
