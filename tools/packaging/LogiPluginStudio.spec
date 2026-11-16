# PyInstaller spec – portable Windows onedir edition (free tooling only).
# Build with: python tools/packaging/build_portable.py
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parents[1]
SRC = ROOT / "src"
PACKAGING = ROOT / "tools" / "packaging"
import sys
sys.path[:0] = [str(SRC), str(PACKAGING)]  # collect_submodules imports from here

PYWIN32 = ["win32api", "win32evtlog", "win32evtlogutil", "win32con", "win32com", "pythoncom", "pywintypes",
           "win32timezone", "winerror", "win32security", "win32process", "win32file"]
hidden = []
for package in ("studio", "adapters", "core", "runtime", "extensions", "library", "symbol_designer", "delivery"):
    found = collect_submodules(package)
    if len(found) < 2:
        raise SystemExit(f"collect_submodules found nothing for {package}")
    hidden += found

# Source files and templates that the generator embeds into plugins at runtime
# (zipapps, C# templates) plus GUI resources. Logitech binaries are NOT included.
datas = [
    (str(SRC / "adapters/logitech/templates"), "adapters/logitech/templates"),
    (str(SRC / "adapters/logitech/native.py"), "adapters/logitech"),
    (str(SRC / "adapters/logitech/native_host_main.py"), "adapters/logitech"),
    (str(SRC / "extensions/shared_folders/templates"), "extensions/shared_folders/templates"),
    (str(SRC / "symbol_designer/assets"), "symbol_designer/assets"),
    (str(SRC / "studio/context_help/resources"), "studio/context_help/resources"),
]
for package in ("core", "runtime"):
    for file in sorted((SRC / package).glob("*.py")):
        datas.append((str(file), package))
for file in sorted((SRC / "extensions/shared_folders").glob("*.py")):
    datas.append((str(file), "extensions/shared_folders"))

studio = Analysis(
    [str(PACKAGING / "studio_main.py")],
    pathex=[str(SRC), str(PACKAGING)],
    hiddenimports=hidden + ["portable_selftest", "automation"],
    datas=datas,
    # pywin32 is not used; PyInstaller would collect it only through the optional
    # NTEventLogHandler import in logging.handlers (AP-POLISH-001 license review).
    excludes=["tkinter", "test", "pytest", "IPython", "matplotlib", "numpy", "PyQt5", "PyQt6"] + PYWIN32,
    noarchive=False,
)
studio_pyz = PYZ(studio.pure)
studio_exe = EXE(studio_pyz, studio.scripts, [], exclude_binaries=True, name="LogiPluginStudio",
                 console=False, disable_windowed_traceback=False, upx=False)

# Frozen stdlib packages cannot load submodules from stdlib.zip, so bundle the
# submodules of the common stdlib packages a trusted handler may use.
RUNNER_STDLIB = ("logging", "email", "http", "urllib", "xml", "json", "concurrent", "asyncio", "importlib",
                 "encodings", "ctypes", "html", "zoneinfo", "multiprocessing", "wsgiref", "xmlrpc", "collections",
                 "sqlite3", "dbm", "unittest")
runner_hidden = []
for package in RUNNER_STDLIB:
    runner_hidden += collect_submodules(package, filter=lambda name: ".test" not in name and "tests" not in name)
runner = Analysis(
    [str(PACKAGING / "host_runner.py")],
    pathex=[],
    hiddenimports=runner_hidden,
    # tzdata (site-packages, ~600 files) is not part of the standard library;
    # zoneinfo stays available and uses the system/IANA data a handler provides.
    excludes=["tkinter", "PySide6", "shiboken6", "studio", "adapters", "core", "runtime", "extensions",
               "library", "symbol_designer", "delivery", "test", "unittest.test", "tzdata"] + PYWIN32,
    noarchive=False,
)
runner_pyz = PYZ(runner.pure)
runner_exe = EXE(runner_pyz, runner.scripts, [], exclude_binaries=True, name="LogiPluginStudioHost",
                 console=True, upx=False)

# The Qt hook collects this GPL-only input method through QtGui. Studio uses
# Qt Widgets and has no dependency on Qt Virtual Keyboard.
studio_binaries = [entry for entry in studio.binaries if "virtualkeyboard" not in entry[0].lower()]
COLLECT(studio_exe, studio_binaries, studio.datas, name="LogiPluginStudio", upx=False)
# AP-POLISH-001: the stdlib-only host runner is its OWN self-contained onedir
# (no Qt, no Studio modules). build_release.py places it at
# LogiPluginStudio/hostruntime and every Studio-built plugin receives a
# verified copy of exactly this directory (plugin-local host runtime).
COLLECT(runner_exe, runner.binaries, runner.datas, name="hostruntime", upx=False)
