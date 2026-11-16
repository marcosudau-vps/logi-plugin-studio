"""Hinweg: Auftrag an Paseo/OpenCode vorbereiten oder ausdrücklich starten.

Standard: nur Vorschau.  --start ist die explizite Freigabe zur Agentenausführung.
"""
import argparse
from datetime import datetime, timezone
import json
import socket
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "work" / "agent_bridge"
ID_PATTERN = re.compile(r"^RUN-AP-[A-Z0-9-]+-\d{2}$")
LOCAL_PASEO = "127.0.0.1:6767"
EXPECTED_HOSTNAME = "CSL-DESKTOP-PC"


def atomic_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def checked_project_file(name: str):
    path = (ROOT / name).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
        raise ValueError(f"Prompt-Datei ist nicht im Projekt vorhanden: {name}")
    if path.suffix.lower() not in {".md", ".txt"}:
        raise ValueError("Prompt muss Markdown oder Text sein.")
    return path


def main():
    parser = argparse.ArgumentParser(description="Paseo/OpenCode-Agentenübergabe")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--prompt-file", required=True, help="Relativ zu PluginStudioArchitecture oder absolut darin")
    parser.add_argument("--provider", default="opencode/opencode/deepseek-v4.1-flash-free", help="Paseo-Provider/Modell; Standard: explizites kostenloses OpenCode-Modell")
    parser.add_argument("--resume-id", help="Paseo-Agent-ID für Korrekturlauf; ohne Angabe neue Session")
    parser.add_argument("--start", action="store_true", help="Agent jetzt wirklich starten/fortsetzen")
    args = parser.parse_args()
    if not ID_PATTERN.fullmatch(args.run_id):
        parser.error("Ungültige Run-ID, erwartet z.B. RUN-AP-CORE-003-02")
    try:
        prompt = checked_project_file(args.prompt_file)
        paseo = shutil.which("paseo")
        if args.start and paseo is None:
            raise RuntimeError("paseo CLI ist nicht im PATH.")
        if args.start and socket.gethostname().casefold() != EXPECTED_HOSTNAME.casefold():
            raise RuntimeError(f"Falscher Rechner: {socket.gethostname()} != {EXPECTED_HOSTNAME}; Start verweigert.")
        run_dir = ROOT / "work" / "runs" / args.run_id
        result_script = ROOT / "tools" / "agent_bridge" / "zurueck.py"
        handoff = BRIDGE / "requests" / (args.run_id + ".prompt.md")
        request_path = BRIDGE / "requests" / (args.run_id + ".json")
        existing = json.loads(request_path.read_text(encoding="utf-8")) if request_path.exists() else {}
        if args.start and existing.get("status") in {"STARTED", "START_REQUESTED"}:
            if not (args.resume_id and args.resume_id == existing.get("agent_id")):
                raise RuntimeError("Dieser Run wurde bereits gestartet. Nur dieselbe Agent-ID darf fortgesetzt werden.")
        cover = (
            f"Du bist Coding-Agent für das Projekt {ROOT}.\n"
            f"Bearbeite ausschließlich {args.run_id} in diesem Projekt.\n"
            f"Lies und befolge den vollständigen Arbeitsauftrag in:\n{prompt}\n"
            f"Lege die Arbeitsakte unter {run_dir} ab.\n"
            f"Erstelle das verlangte Delta-ZIP, prüfe Tests, CRC und Hashes.\n"
            f"Wichtig: Wenn REVIEW_READY, rufe am Ende folgenden lokalen Rückkanal auf "
            f"(ZIP-Pfad auf die tatsächlich erstellte Datei setzen):\n"
            f'python "{result_script}" --run-id {args.run_id} --status REVIEW_READY '
            f'--zip "{run_dir / "outputs" / (args.run_id + ".zip")}"\n'
            f"Wenn BLOCKED, rufe stattdessen auf:\n"
            f'python "{result_script}" --run-id {args.run_id} --status BLOCKED\n'
            f"Schreibe vorher die vollständige Arbeitsakte. Keine Selbstabnahme oder Folgepakete.\n"
        )
        handoff.parent.mkdir(parents=True, exist_ok=True)
        handoff.write_text(cover, encoding="utf-8")
        if args.resume_id:
            cmd = [paseo or "paseo", "send", "--host", LOCAL_PASEO, "--no-wait", "--json",
                   "--prompt-file", str(handoff), args.resume_id]
            kind = "resume"
        else:
            # Windows .cmd-Wrapper kann mehrzeilige Argumente auf die erste Zeile kuerzen.
            # Daher nur einen einzeiligen Startverweis uebergeben; Volltext liegt als Datei vor.
            short = (f"VERBINDLICHER AUFTRAG: Lies zuerst die gesamte UTF-8-Datei {handoff} "
                     f"und fuehre sie vollstaendig aus. Run-ID: {args.run_id}. "
                     "Nicht auf eine allgemeine Projektinventur ausweichen. "
                     "Arbeitsakte, ZIP, Tests und Rueckkanal sind dort vorgeschrieben.")
            cmd = [paseo or "paseo", "run", "--host", LOCAL_PASEO, "--no-wait", "--json",
                   "--provider", args.provider, "--cwd", str(ROOT),
                   "--title", args.run_id, short]
            kind = "new"
        record = {
            "schema_version": 1, "run_id": args.run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "PREPARED", "mode": kind, "prompt_file": str(prompt),
            "handoff_prompt": str(handoff), "provider": args.provider if kind == "new" else None,
            "resume_id": args.resume_id,
            "cwd": str(ROOT), "command_preview": cmd[:-1] + (["<cover prompt>"] if kind == "new" else [args.resume_id]),
        }
        atomic_json(request_path, record)
        if not args.start:
            print(json.dumps({"status": "PREPARED", "request": str(request_path),
                              "message": "Trockenlauf. Mit --start wird der Agent tatsächlich ausgelöst.",
                              "mode": kind}, ensure_ascii=False, indent=2))
            return 0
        if args.resume_id:
            inspector = subprocess.run([paseo, "inspect", "--host", LOCAL_PASEO, "--json", args.resume_id],
                                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                                       errors="replace", timeout=15, shell=False)
            if inspector.returncode != 0:
                raise RuntimeError("Paseo-Agent-ID nicht im lokalen Daemon lesbar; Fortsetzung verweigert.")
            try:
                info = json.loads(inspector.stdout)
            except json.JSONDecodeError as err:
                raise RuntimeError("Ungültige Paseo-Inspect-Antwort.") from err
            if Path(info.get("Cwd", info.get("cwd", ""))).resolve() != ROOT.resolve():
                raise RuntimeError("Paseo-Agent gehört zu einem anderen Projekt; Fortsetzung verweigert.")
        record["daemon_host"] = LOCAL_PASEO
        record["computer"] = socket.gethostname()
        record["status"] = "START_REQUESTED"
        atomic_json(request_path, record)
        process = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=60, shell=False)
        record["exit_code"] = process.returncode
        record["paseo_output"] = process.stdout[-16000:]
        record["paseo_error"] = process.stderr[-6000:]
        record["status"] = "STARTED" if process.returncode == 0 else "START_FAILED"
        if process.returncode == 0:
            try:
                obj = json.loads(process.stdout)
                record["agent_id"] = obj.get("id") or obj.get("agentId") or obj.get("agent_id")
            except (json.JSONDecodeError, AttributeError):
                pass
        atomic_json(request_path, record)
        print(json.dumps({"status": record["status"], "request": str(request_path),
                          "agent_id": record.get("agent_id"), "details": process.stdout[-3000:],
                          "error": process.stderr[-1500:]}, ensure_ascii=False, indent=2))
        return 0 if process.returncode == 0 else 1
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"Übergabe fehlgeschlagen: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
