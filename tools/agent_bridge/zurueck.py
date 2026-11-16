"""Rückweg: Agenten-Ergebnis prüfen und als lokale, lesbare Nachricht hinterlegen.

Kein Netzwerkversand und kein fingiertes Posten in einen Chat.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "work" / "agent_bridge" / "results"
ID_PATTERN = re.compile(r"^RUN-AP-[A-Z0-9-]+-\d{2}$")


def verify_zip(path: Path, expected_run: str):
    if not path.is_file() or path.suffix.lower() != ".zip":
        raise ValueError("Ergebnis-ZIP fehlt.")
    if not path.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError("Ergebnis-ZIP liegt außerhalb des Projektverzeichnisses.")
    with zipfile.ZipFile(path, "r") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Doppelte ZIP-Einträge.")
        for name in names:
            parts = PurePosixPath(name).parts
            if name.startswith("/") or ".." in parts or "\\" in name:
                raise ValueError(f"Unsicherer ZIP-Pfad: {name}")
        invalid = archive.testzip()
        if invalid:
            raise ValueError(f"ZIP-CRC fehlerhaft: {invalid}")
        manifests = [name for name in names if name.endswith("/outputs/CHANGESET.json")]
        if len(manifests) != 1:
            raise ValueError("CHANGESET.json muss genau einmal im ZIP enthalten sein.")
        manifest = json.loads(archive.read(manifests[0]))
        if manifest.get("run_id") != expected_run:
            raise ValueError("Run-ID im Änderungsmanifest stimmt nicht überein.")
        files = manifest.get("files")
        if not isinstance(files, dict) or not files:
            raise ValueError("Manifest enthält keine Datei-Hashes.")
        declared = set(manifest.get("added", [])) | set(manifest.get("modified", []))
        if declared != set(files):
            raise ValueError("Manifest-Deklaration stimmt nicht mit den Datei-Hashes überein.")
        allowed = {"PluginStudioArchitecture/" + key for key in files}
        non_manifest = {name for name in names if not name.endswith("/") and name != manifests[0]}
        if non_manifest != allowed:
            raise ValueError("ZIP-Dateien stimmen nicht mit dem Manifest überein.")
        for relative, expected_hash in files.items():
            if not re.fullmatch(r"[a-fA-F0-9]{64}", str(expected_hash)):
                raise ValueError("Ungültige SHA-256 im Manifest.")
            digest = hashlib.sha256(archive.read("PluginStudioArchitecture/" + relative)).hexdigest()
            if digest.lower() != expected_hash.lower():
                raise ValueError(f"SHA-256 stimmt nicht: {relative}")
    return {"zip": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "file_count": len(files), "crc": "PASS", "manifest": "PASS"}


def main():
    p = argparse.ArgumentParser(description="Rückmeldung von einem lokalen Coding-Agenten")
    p.add_argument("--run-id", required=True)
    p.add_argument("--status", required=True, choices=("REVIEW_READY", "BLOCKED"))
    p.add_argument("--zip", help="Pfad zum Ergebnis-ZIP (zwingend bei REVIEW_READY)")
    p.add_argument("--summary", default="")
    p.add_argument("--check-only", action="store_true", help="Nur validieren, keine Rückmeldung speichern")
    args = p.parse_args()
    try:
        if not ID_PATTERN.fullmatch(args.run_id):
            raise ValueError("Ungültige Run-ID.")
        if args.status == "REVIEW_READY" and not args.zip:
            raise ValueError("REVIEW_READY erfordert ein Ergebnis-ZIP.")
        package = (ROOT / args.zip).resolve() if args.zip else None
        verification = verify_zip(package, args.run_id) if package else None
        report = ROOT / "work" / "runs" / args.run_id / "05_abschlussbericht.md"
        if not args.check_only and not report.is_file():
            raise ValueError("Der Abschlussbericht fehlt; Rückmeldung nicht gespeichert.")
        result = {
            "schema_version": 1, "run_id": args.run_id,
            "status": args.status, "received_at": datetime.now(timezone.utc).isoformat(),
            "summary": args.summary, "report": str(report) if report.is_file() else None,
            "verification": verification,
            "delivery": "LOCAL_INBOX_ONLY", "review_approved": False
        }
        if not args.check_only:
            OUTPUT.mkdir(parents=True, exist_ok=True)
            dest = OUTPUT / (args.run_id + ".json")
            tmp = dest.with_name(dest.name + "." + uuid.uuid4().hex + ".tmp")
            tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            tmp.replace(dest)
        print(json.dumps({**result, "bridge_status": "VERIFIED" if args.check_only else "RECEIVED"},
                         ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, json.JSONDecodeError) as e:
        print(f"Rückgabe abgelehnt: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
