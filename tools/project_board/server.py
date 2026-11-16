"""Local read-only dashboard for PluginStudioArchitecture. stdlib only."""
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PORT = 18766
PHASES = [
    {"id":"P0","title":"Architektur & Metamodell","description":"Systemprinzipien, P0-ADRs und Runtime-Grundsätze","state":"done"},
    {"id":"P1","title":"Fachneutrales Core Model","description":"Projektmodell, Schema, Referenzen und Validator","state":"done"},
    {"id":"P2","title":"Runtime & Datenfluss","description":"Dispatcher, StateStore, Synchronisierung und Reconnect (In-Memory/Fake)","state":"done"},
    {"id":"P3","title":"Logitech-Adapter & Python-API","description":"SDK-Bibliothek, generischer Plugin-Build und später Hardware-Durchstich","state":"active"},
    {"id":"P4","title":"Produktiver Studio-Editor","description":"Freie Aktionen, Zustände, Bindings, Layouts und Build","state":"planned"},
    {"id":"P5","title":"SDK-Funktionsausbau","description":"Weitere Features gezielt im SDK Lab verifizieren","state":"later"},
]
TASKS = [
    ("AP-CORE-001","P1","Core Model & Validator","Stabiles Projektmodell, Typen, Bindings, CLI"),
    ("AP-CORE-002","P2","Runtime-Dispatcher","Command-/Event-Fluss, In-Memory-Spike"),
    ("AP-CORE-003","P2","StateStore & Snapshots","Scopes, Schreibhoheit, Revisionen"),
    ("AP-CORE-004","P2","Sync & Reconnect","Fake-Transport, Snapshot-/Delta-Synchronisierung und Reconnect"),
    ("AP-LOGI-001","P3","Generischer Logitech-Plugin-Build","Validiertes Core-Projekt → generiertes C#-Plugin; Build-only ohne Installation"),
]
def relative_link(path):
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return None

def state_from_report(report):
    if not report.exists():
        return "running"
    s = report.read_text(encoding="utf-8", errors="replace").upper()
    if "BLOCKED" in s and "REVIEW_READY" not in s:
        return "blocked"
    if "REVIEW_READY" in s:
        return "review"
    if "APPROVED" in s:
        return "review"  # self-claims never constitute independent approval
    return "running"

def current_data():
    runs_root = ROOT / "work" / "runs"
    run_dirs = sorted((x for x in runs_root.glob("RUN-AP-*-*") if x.is_dir()), key=lambda x: x.name) if runs_root.exists() else []
    runs = []
    for folder in run_dirs:
        report = folder / "05_abschlussbericht.md"
        runs.append({"name":folder.name, "state":state_from_report(report),
                     "file":relative_link(report) if report.exists() else None})
    tasks = []
    for id,phase,title,description in TASKS:
        matches = [r for r in runs if r["name"].startswith("RUN-"+id+"-")]
        package = ROOT / "work" / "packages" / id
        prompt = package / "02_agentenprompt.md"
        if id == "AP-CORE-001":
            # Independently documented approval in project
            approved = (package / "14_abnahme_RUN-AP-CORE-001-04.md").exists()
            state = "done" if approved else ("review" if matches else "planned")
            source = "Abnahmeakte im Projekt" if approved else "Projektdateien"
        elif id == "AP-CORE-002":
            # Independently approved during the review; local acceptance delta may not yet be installed
            approved = (package / "06_abnahme_RUN-AP-CORE-002-02.md").exists()
            state = "done"
            source = "Projektakte" if approved else "Abnahme in dieser Unterhaltung; Delta auf dem PC noch nicht nachgewiesen"
        elif id == "AP-CORE-003" and (package / "06_abnahme_RUN-AP-CORE-003-02.md").exists():
            state = "done"
            source = "Unabhängige Abnahmeakte im Projekt"
        elif id == "AP-CORE-004" and (package / "06_abnahme_RUN-AP-CORE-004-02.md").exists():
            state = "done"
            source = "Unabhängige Abnahmeakte im Projekt"
        elif id == "AP-LOGI-001" and (package / "04_abnahme_RUN-AP-LOGI-001-01.md").exists():
            state = "done"
            source = "Unabhängige BUILD_ONLY-Abnahme im Projekt"
        elif matches:
            state = matches[-1]["state"]
            source = "Arbeitsakte auf dem PC"
        elif prompt.exists():
            request_file = ROOT / "work" / "agent_bridge" / "requests" / ("RUN-" + id + "-01.json")
            try:
                started = json.loads(request_file.read_text(encoding="utf-8")).get("status") == "STARTED"
            except (OSError, ValueError, json.JSONDecodeError):
                started = False
            state = "running" if started else "ready"
            source = "Lokaler Paseo-Auftrag gestartet" if started else "Agentenprompt im Projekt"
        else:
            state = "planned"
            source = "Roadmap"
        tasks.append({"id":id,"phase":phase,"title":title,"description":description,
                      "state":state,"source":source,
                      "prompt":relative_link(prompt) if prompt.exists() else None,
                      "runs":matches, "latest_run":matches[-1] if matches else None})
    alerts = []
    if not (ROOT/"work/packages/AP-CORE-003/02_agentenprompt.md").exists():
        alerts.append("AP-CORE-003-Prompt fehlt lokal noch: aktuelles Delta-Paket wurde offenbar noch nicht eingespielt.")
    if not (ROOT/"docs/decisions/RT-ADR-001.md").exists():
        alerts.append("Runtime-ADRs T1–T6 fehlen noch im lokalen docs/decisions-Ordner.")
    if (ROOT/"STATUS.md").exists() and "AP-CORE-001 | `READY_TO_START" in (ROOT/"STATUS.md").read_text(encoding="utf-8",errors="replace"):
        alerts.append("STATUS.md ist älter als die abgenommenen Agentenläufe; Arbeitsakten sind hier maßgeblicher.")
    handoffs = []
    for file in sorted((ROOT / "work" / "agent_bridge" / "results").glob("*.json")):
        try:
            item = json.loads(file.read_text(encoding="utf-8"))
            if item.get("run_id") and item.get("status") in {"REVIEW_READY", "BLOCKED"}:
                review_file = ROOT / "work" / "agent_bridge" / "reviews" / (item["run_id"] + "_review.md")
                reviewed = review_file.is_file() and "APPROVED" in review_file.read_text(encoding="utf-8", errors="replace")
                handoffs.append({"run_id":item["run_id"], "status":"APPROVED" if reviewed else item["status"],
                                 "received_at":item.get("received_at"),
                                 "report":relative_link(Path(item["report"])) if item.get("report") else None,
                                 "verified": bool(item.get("verification"))})
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return {"title":"Logi Plugin Studio","phases":PHASES,"tasks":tasks,"runs":runs[-12:],
            "handoffs":handoffs[-12:], "alerts":alerts,"generated":datetime.now().astimezone().isoformat(timespec="seconds"),
            "root":str(ROOT),"server_port":PORT}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def send(self, payload, content_type, status=200):
        raw=payload.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type",content_type+"; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Length",str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def do_GET(self):
        u=urlsplit(self.path)
        if u.path=="/":
            return self.send((HERE/"index.html").read_text(encoding="utf-8"),"text/html")
        if u.path=="/api/status":
            return self.send(json.dumps(current_data(),ensure_ascii=False),"application/json")
        if u.path=="/doc":
            candidate=parse_qs(u.query).get("path",[""])[0]
            file=(ROOT/candidate).resolve()
            if not file.is_relative_to(ROOT.resolve()) or file.suffix.lower() not in {".md",".json",".txt"} or not file.is_file():
                return self.send("Datei nicht gefunden","text/plain",404)
            return self.send(file.read_text(encoding="utf-8",errors="replace"),"text/plain")
        return self.send("Nicht gefunden","text/plain",404)

if __name__=="__main__":
    ThreadingHTTPServer(("127.0.0.1",PORT),Handler).serve_forever()
