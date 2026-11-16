"""Independent integrity check of the release candidate (AP-POLISH-001 / AP-10).

    python tools/packaging/verify_release.py [--rc <release_candidate>] [--out <report.json>]

Recomputes every SHA-256 from the artifacts themselves and compares with
``release_manifest.json``, ``SHA256SUMS.txt`` and the payload hash list;
checks every ZIP entry, the host-runtime manifest inside the ZIP, the license
texts, the absence of Logitech binaries / Qt Virtual Keyboard, and the Setup
EXE version resource. Exit code 0 only if every check passed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RC = ROOT / "work" / "polish" / "AP-POLISH-001" / "outputs" / "release_candidate"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def version_resource(exe: Path) -> dict:
    import ctypes
    from ctypes import wintypes
    version = ctypes.WinDLL("version")
    size = version.GetFileVersionInfoSizeW(str(exe), None)
    if not size:
        return {}
    data = ctypes.create_string_buffer(size)
    version.GetFileVersionInfoW(str(exe), 0, size, data)
    result = {}
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if version.VerQueryValueW(data, "\\VarFileInfo\\Translation", ctypes.byref(pointer), ctypes.byref(length)):
        lang, codepage = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_ushort * 2)).contents
        for key in ("ProductVersion", "FileDescription", "ProductName"):
            query = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\{key}"
            if version.VerQueryValueW(data, query, ctypes.byref(pointer), ctypes.byref(length)) and length.value:
                result[key] = ctypes.wstring_at(pointer, length.value - 1)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rc", type=Path, default=DEFAULT_RC)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    rc = args.rc.resolve()
    checks = []

    def check(name, ok, **detail):
        checks.append({"check": name, "result": "PASS" if ok else "FAIL", **detail})

    manifest = json.loads((rc / "release_manifest.json").read_text(encoding="utf-8"))
    payload = json.loads((rc / manifest["payload"]["sha256_list"]).read_text(encoding="utf-8"))
    sums = dict(reversed(line.split("  ", 1)) for line in (rc / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines())
    for key, artifact in manifest["artifacts"].items():
        path = rc / artifact["file"]
        actual = sha256(path) if path.is_file() else None
        check(f"artifact_sha256:{key}", actual == artifact["sha256"] == sums.get(artifact["file"]),
              file=artifact["file"], sha256=actual, bytes=path.stat().st_size if path.is_file() else None)
    tree = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    check("payload_tree_sha256", tree == manifest["payload"]["tree_sha256"], files=len(payload))
    with zipfile.ZipFile(rc / manifest["artifacts"]["portable_zip"]["file"]) as archive:
        crc = archive.testzip()
        entries = {n.split("/", 1)[1]: hashlib.sha256(archive.read(n)).hexdigest()
                   for n in archive.namelist() if not n.endswith("/")}
        runtime_manifest = json.loads(archive.read(f"{manifest['payload']['directory']}/hostruntime/studio-host-runtime.json"))
    check("zip_crc", crc is None, first_bad=crc)
    mismatched = sorted(k for k in set(entries) | set(payload) if entries.get(k) != payload.get(k))
    check("zip_entries_equal_payload_hashes", not mismatched, entries=len(entries), mismatched=mismatched[:20])
    runtime_bad = [n for n, d in runtime_manifest["files"].items() if entries.get(f"hostruntime/{n}") != d]
    check("host_runtime_manifest_matches_zip", not runtime_bad, files=len(runtime_manifest["files"]),
          runtime_id=runtime_manifest["runtime_id"], bad=runtime_bad[:10])
    qt_in_runtime = [n for n in runtime_manifest["files"] if "qt" in n.lower() or "pyside" in n.lower()]
    check("host_runtime_without_qt", not qt_in_runtime, offending=qt_in_runtime)
    forbidden = [n for n in entries if n.lower().endswith("pluginapi.dll") or "virtualkeyboard" in n.lower()
                 or ("logiplugin" in n.lower() and n.lower().endswith(".dll"))]
    check("no_logitech_binaries_or_qt_virtual_keyboard", not forbidden, offending=forbidden)
    pywin32 = [n for n in entries if "pywin32" in n.lower() or "/win32/" in n.lower()]
    check("no_undeclared_pywin32", not pywin32, offending=pywin32)
    required = ["licenses/LGPL-3.0-only.txt", "licenses/GPL-3.0-only.txt", "licenses/Python-LICENSE.txt",
                "licenses/PyInstaller-COPYING.txt", "hostruntime/licenses/Python-LICENSE.txt",
                "hostruntime/licenses/PyInstaller-COPYING.txt", "THIRD_PARTY_NOTICES.md", "ANWENDERHANDBUCH.md",
                "README.txt", "LogiPluginStudio.exe", "hostruntime/LogiPluginStudioHost.exe"]
    missing = [n for n in required if n not in entries]
    check("license_and_documentation_files", not missing, missing=missing)
    check("license_notices_beside_artifacts", (rc / "THIRD_PARTY_NOTICES.md").is_file() and
          (rc / "licenses" / "LGPL-3.0-only.txt").is_file())
    setup = manifest["artifacts"].get("setup_exe")
    if setup:
        info = version_resource(rc / setup["file"])
        check("setup_version_resource", info.get("ProductVersion", "").startswith(manifest["version_numeric"][:5])
              or manifest["version"] in str(info), resource=info)
    check("not_published", manifest.get("publication", "").startswith("none") and manifest.get("signed") is False,
          publication=manifest.get("publication"), signed=manifest.get("signed"))
    report = {"format": "release-verification-1", "version": manifest["version"], "release_candidate": str(rc),
              "passed": sum(c["result"] == "PASS" for c in checks), "failed": sum(c["result"] == "FAIL" for c in checks),
              "checks": checks}
    text = json.dumps(report, indent=2)
    (rc / "release_verification.json").write_text(text, encoding="utf-8")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "failed": report["failed"],
                      "failures": [c for c in checks if c["result"] == "FAIL"]}, indent=1))
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
