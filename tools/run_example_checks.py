"""Bounded standalone-host/CLI check. Real HTTP, no device or installation."""
from __future__ import annotations

import argparse
import json
import queue
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--connection", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "work" / "autopilot" / "FINAL-PRODUCT-02" / "example-check")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "src"))
    from adapters.logitech.codegen import check_output_dir
    directory = check_output_dir(args.out)
    directory.mkdir(parents=True, exist_ok=True)
    lines: queue.Queue[str] = queue.Queue()
    process = subprocess.Popen([sys.executable, str(ROOT / "examples" / "first_plugin" / "host.py"),
                                "--connection", str(args.connection), "--run-for", "8"],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    log = []

    def collect():
        for line in process.stdout:
            log.append(line)
            lines.put(line)

    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    evidence = {"level": "STANDALONE_PYTHON_CLI_REAL_HTTP", "hardware_test": False, "checks": []}
    try:
        ready = lines.get(timeout=10)
        if not ready.startswith("HOST_READY"):
            # Logging may precede readiness; still bounded by the host's own lifetime.
            while not ready.startswith("HOST_READY"):
                ready = lines.get(timeout=10)
        for action, placement in (("action.first", "placement.first"), ("action.second", "placement.second")):
            command = [sys.executable, str(ROOT / "tools" / "run_product.py"), "press",
                       "--connection", str(args.connection), "--action", action, "--placement", placement]
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=12)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            data = json.loads(result.stdout)
            assert data["result"]["status"] == "COMPLETED"
            slot = "state.mode@component:" + action
            assert data["state"]["snapshot"]["states"][slot]["value"] == "active"
            assert data["state"]["snapshot"]["states"][slot]["quality"] == "fresh"
            evidence["checks"].append(f"explicit_callback_state_and_placement:{action}")
            (directory / (action + ".json")).write_text(result.stdout, encoding="utf-8")
        diagnosis = subprocess.run([sys.executable, str(ROOT / "tools" / "run_product.py"), "diagnose",
                                    "--connection", str(args.connection)],
                                   capture_output=True, text=True, encoding="utf-8", timeout=10)
        assert diagnosis.returncode == 0, diagnosis.stderr
        (directory / "diagnose.json").write_text(diagnosis.stdout, encoding="utf-8")
        assert process.wait(timeout=12) == 0
        reader.join(timeout=2)
        evidence["checks"].append("host_runs_without_studio_and_exits_cleanly")
        evidence["ok"] = True
        print(json.dumps(evidence, indent=2))
        return 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        reader.join(timeout=2)
        process.stdout.close()
        (directory / "host.log").write_text("".join(log), encoding="utf-8")
        (directory / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
