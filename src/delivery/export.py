from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


class ExportError(ValueError):
    pass


SOURCE_ROOTS = ("src", "tests", "tools", "docs", "component_types", "schemas", "examples")
ROOT_FILES = ("README.md", "STATUS.md", "CHANGELOG.md", "start_studio.ps1", ".gitignore",
              "requirements.txt", "requirements-dev.txt")
SOURCE_SUFFIXES = {".py", ".cs", ".in", ".json", ".md", ".png", ".ps1", ".schema", ".yaml", ".yml",
                   ".html", ".css", ".js", ".svg", ".ict"}
EXCLUDED_DIRS = {"bin", "obj", "__pycache__", ".git", ".venv", "node_modules",
                 "delivery", "build", "generated", "backups", "backup", "private", "secrets", "credentials"}
EXCLUDED_SUFFIXES = {".dll", ".exe", ".pdb", ".pyc", ".zip", ".7z", ".bak", ".backup",
                     ".old", ".key", ".pem", ".pfx", ".p12", ".log", ".env"}
PRIVATE_NAME = re.compile(r"(^|[._-])(secret|secrets|credential|credentials|token|tokens|password|passwd|id_rsa|id_ed25519)([._-]|$)", re.I)
SENSITIVE_CONTENT = re.compile(
    rb"(?m:^-----BEGIN (?:[A-Z ]*PRIVATE KEY|OPENSSH PRIVATE KEY)-----)|"
    rb"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b|"
    rb"""(?i:["']?(?:secret|api[_-]?key|access[_-]?token|password)["']?\s*[:=]\s*["'])([A-Za-z0-9_+/=-]{20,})|"""
    rb"(?i:\bBearer\s+[A-Za-z0-9_+/=-]{20,})"
)
MAX_FILE = 8 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_FILES = 10000


def _linked(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _walk(directory: Path, *, prune: set[str] = frozenset()):
    if _linked(directory):
        raise ExportError("EXPORT_LINK: linked directory refused")
    if not directory.exists():
        return
    with os.scandir(directory) as entries:
        for entry in sorted(entries, key=lambda e: e.name):
            path = Path(entry.path)
            if _linked(path):
                raise ExportError("EXPORT_LINK: linked file/directory refused")
            if entry.is_dir(follow_symlinks=False):
                if entry.name.casefold() not in prune:
                    yield from _walk(path, prune=prune)
            elif entry.is_file(follow_symlinks=False):
                yield path
            else:
                raise ExportError("EXPORT_SPECIAL_FILE: non-regular input refused")


def _secret_material(root: Path) -> set[bytes]:
    """Inspect private connection files locally, never return their values to callers."""
    material: set[bytes] = set()
    count = 0
    for path in _walk(root, prune={".git", ".venv", "node_modules", "__pycache__"}):
        count += 1
        if count > MAX_FILES:
            raise ExportError("EXPORT_LIMIT: secret discovery file limit reached")
        if path.name.casefold().startswith("studio.connection.json"):
            if path.stat().st_size > MAX_FILE:
                raise ExportError("EXPORT_SECRET_CONFIG: oversized private configuration")
            try:
                value = json.loads(path.read_bytes())
                secret = value["secret"]
                if not isinstance(secret, str) or not re.fullmatch("[a-f0-9]{64}", secret):
                    raise ValueError()
                material.add(secret.encode("ascii"))
                material.add(bytes.fromhex(secret))
            except (ValueError, KeyError, TypeError, UnicodeError):
                raise ExportError("EXPORT_SECRET_CONFIG: unreadable or malformed private configuration") from None
    return material


def _select(root: Path, run: str):
    for folder in SOURCE_ROOTS:
        yield from _walk(root / folder, prune=EXCLUDED_DIRS - {"delivery"})
    for name in ROOT_FILES:
        path = root / name
        if path.exists():
            yield path
    roadmap = root / "work" / "planning" / "roadmap.md"
    if roadmap.exists():
        yield roadmap
    # Export written evidence, never runtime logs/JSON, receipts or build products.
    for folder in (root / "work" / "autopilot" / run, root / "work" / "autopilot" / "reviews"):
        for path in _walk(folder, prune=EXCLUDED_DIRS | {"build", "plugin", "probe", "process-check", "example-check"}):
            if path.suffix.casefold() in {".md", ".png"}:
                yield path


def collect_sources(root: Path, *, run: str) -> dict[str, bytes]:
    if _linked(root):
        raise ExportError("EXPORT_LINK: linked project root refused")
    root = root.resolve(strict=True)
    if not re.fullmatch(r"FINAL-PRODUCT-[0-9]{2}", run):
        raise ExportError("EXPORT_SCOPE: use a named product review run, never a full-project archive")
    material = _secret_material(root)
    result = {}
    total = 0
    for file in _select(root, run):
        if _linked(file) or not file.resolve(strict=True).is_relative_to(root):
            raise ExportError("EXPORT_LINK: source escapes project root")
        name = file.name.casefold()
        if name.startswith("studio.connection.json") or name == ".env" or file.suffix.casefold() in EXCLUDED_SUFFIXES:
            continue
        if PRIVATE_NAME.search(name):
            raise ExportError("EXPORT_SUSPECT_FILE: private-looking source file refused")
        if file.suffix.casefold() not in SOURCE_SUFFIXES and file.relative_to(root).as_posix() not in ROOT_FILES:
            raise ExportError("EXPORT_UNKNOWN_FILE: unclassified source file refused")
        if file.stat().st_size > MAX_FILE:
            raise ExportError("EXPORT_LIMIT: source exceeds file limit")
        content = file.read_bytes()
        if any(secret in content for secret in material) or SENSITIVE_CONTENT.search(content):
            raise ExportError("EXPORT_SECRET_CONTENT: potentially private content refused")
        total += len(content)
        if total > MAX_TOTAL or len(result) >= MAX_FILES:
            raise ExportError("EXPORT_LIMIT: source snapshot budget exceeded")
        result[file.relative_to(root).as_posix()] = content
    if not result:
        raise ExportError("EXPORT_EMPTY: no reviewed source files")
    return dict(sorted(result.items()))


def verify_archive(archive: Path) -> dict:
    try:
        with zipfile.ZipFile(archive) as zipped:
            names = zipped.namelist()
            if len(names) > MAX_FILES + 1 or any(e.file_size > MAX_FILE for e in zipped.infolist()) or sum(
                    e.file_size for e in zipped.infolist()) > MAX_TOTAL + MAX_FILE:
                raise ExportError("EXPORT_LIMIT: archive exceeds budget")
            if any(stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG) for entry in zipped.infolist()):
                raise ExportError("EXPORT_LINK: ZIP non-regular member refused")
            if len(names) != len({name.casefold() for name in names}) or zipped.testzip() is not None:
                raise ExportError("EXPORT_CRC: duplicate entry or CRC failure")
            manifest = json.loads(zipped.read("source-hashes.json"))
            if not isinstance(manifest, dict) or manifest.get("format") != "studio-safe-source-2" or manifest.get("share_scope") != "REVIEW_SOURCE_ONLY":
                raise ExportError("EXPORT_MANIFEST: full-project/unclassified ZIP is not share-safe")
            files = manifest.get("files")
            run = manifest.get("run")
            if not isinstance(run, str) or not re.fullmatch(r"FINAL-PRODUCT-[0-9]{2}", run):
                raise ExportError("EXPORT_SCOPE: invalid review run")
            if not isinstance(files, dict) or not files or type(manifest.get("count")) is not int or manifest.get("count") != len(files):
                raise ExportError("EXPORT_MANIFEST: invalid file index")
            expected = {"source-hashes.json"} | {"PluginStudioArchitecture/" + name for name in files}
            if set(names) != expected:
                raise ExportError("EXPORT_EXTRA: archive contains unclassified files")
            for name, digest in files.items():
                path = PurePosixPath(name)
                if path.as_posix() != name or path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
                    raise ExportError("EXPORT_PATH: unsafe ZIP name")
                source_path = len(path.parts) > 1 and path.parts[0] in SOURCE_ROOTS
                evidence_path = name.startswith(f"work/autopilot/{run}/") or name.startswith("work/autopilot/reviews/")
                evidence_path = evidence_path and path.suffix.casefold() in {".md", ".png"} and not (
                    set(path.parts) & {"build", "plugin", "probe", "process-check", "example-check"})
                if not (source_path or name in ROOT_FILES or name == "work/planning/roadmap.md" or evidence_path):
                    raise ExportError("EXPORT_SCOPE: ZIP member is outside reviewed source scope")
                if (path.name.casefold().startswith(("studio.connection.json", ".env")) or
                        PRIVATE_NAME.search(path.name) or (path.suffix.casefold() not in SOURCE_SUFFIXES and name not in ROOT_FILES) or
                        set(part.casefold() for part in path.parts) & (EXCLUDED_DIRS - {"delivery"} if source_path else EXCLUDED_DIRS)):
                    raise ExportError("EXPORT_PRIVATE_FILE: private ZIP member refused")
                content = zipped.read("PluginStudioArchitecture/" + name)
                if SENSITIVE_CONTENT.search(content) or hashlib.sha256(content).hexdigest() != digest:
                    raise ExportError("EXPORT_HASH: altered or potentially private ZIP content")
            return manifest
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        if isinstance(exc, ExportError):
            raise
        raise ExportError("EXPORT_INVALID: archive validation failed") from None


def export_sources(root: Path, output: Path, *, run: str = "FINAL-PRODUCT-02") -> dict:
    sources = collect_sources(root, run=run)
    root = root.resolve()
    for parent in (output, *output.parents):
        if _linked(parent):
            raise ExportError("EXPORT_OUTPUT: linked output directory refused")
    output = output.resolve()
    if not output.is_relative_to(root / "work" / "autopilot" / run):
        raise ExportError("EXPORT_OUTPUT: output must remain within the current review run")
    marker = output / "export.owner.json"
    if output.exists() and any(output.iterdir()):
        try:
            owner = json.loads(marker.read_bytes())
        except (OSError, ValueError):
            raise ExportError("EXPORT_OUTPUT: unowned non-empty output refused") from None
        if owner != {"format": "studio-export-owner-1", "run": run} or any(
                _linked(p) or not p.is_file() or p.name not in {"export.owner.json", "source-snapshot.zip", "source-hashes.json", "source-snapshot.sha256"}
                for p in output.iterdir()):
            raise ExportError("EXPORT_OUTPUT: foreign contents refused")
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"format": "studio-safe-source-2", "share_scope": "REVIEW_SOURCE_ONLY",
                "run": run, "status": "READY_FOR_REVIEW", "hardware_test": False,
                "excluded": ["connections", "credentials", "backups", "archives", "builds", "runtime_logs", "vendor_files"],
                "count": len(sources),
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in sources.items()}}
    encoded = json.dumps(manifest, indent=2, ensure_ascii=True).encode("ascii")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output, prefix=".safe-export-", suffix=".zip", delete=False) as handle:
            temporary = Path(handle.name)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
            for name, data in sources.items():
                zipped.writestr("PluginStudioArchitecture/" + name, data)
            zipped.writestr("source-hashes.json", encoded)
        verify_archive(temporary)
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        os.replace(temporary, output / "source-snapshot.zip")
        temporary = None
        (output / "source-hashes.json").write_bytes(encoded)
        (output / "source-snapshot.sha256").write_text(digest + "  source-snapshot.zip\n", encoding="ascii")
        marker.write_text(json.dumps({"format": "studio-export-owner-1", "run": run}), encoding="ascii")
        return {"archive": str(output / "source-snapshot.zip"), "count": len(sources), "sha256": digest,
                "crc_and_hashes_verified": True, "share_scope": "REVIEW_SOURCE_ONLY",
                "private_connections_included": False}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
