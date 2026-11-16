"""AP-POLISH-001 / AP-08: automated stability and load run of the plugin host.

Runs the REAL host bundle (``native-host.pyz``) in the REAL host runtime
(``--runtime``: the frozen ``hostruntime`` of the release payload, or a dev
runtime) as a separate process, exactly like a self-hosted plugin, and drives
it with the same signed HTTP contract the C# bridge uses (``LocalClient``).
Process metrics (threads, handles, private bytes, working set) are sampled
from Windows during the run. Results: one JSON file (``--out``).

Phases: poll storm (bridge polling), command storm (key presses beyond the
deduplication capacity), rapid start/stop cycles, reconnect after host
restart, parallel hosts. Every phase records counts, errors and metrics; no
result is interpreted here beyond plain thresholds that are written out.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from adapters.logitech.gate import DEFAULT_MANIFEST_DIR  # noqa: E402
from adapters.logitech.host_runtime import RUNNER_NAME, native_host_bundle  # noqa: E402
from runtime.wire import ConnectionSettings, HostError, LocalClient, json_bytes, project_digest  # noqa: E402

PROCESS_QUERY_INFORMATION, PROCESS_VM_READ = 0x0400, 0x0010


class Counters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]


class ThreadEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ThreadID", wintypes.DWORD),
                ("th32OwnerProcessID", wintypes.DWORD), ("tpBasePri", wintypes.LONG),
                ("tpDeltaPri", wintypes.LONG), ("dwFlags", wintypes.DWORD)]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)


def metrics(pid: int) -> dict:
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        return {"error": ctypes.get_last_error()}
    try:
        count = wintypes.DWORD()
        kernel32.GetProcessHandleCount(handle, ctypes.byref(count))
        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
    finally:
        kernel32.CloseHandle(handle)
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000004, 0)  # TH32CS_SNAPTHREAD
    threads = 0
    entry = ThreadEntry()
    entry.dwSize = ctypes.sizeof(ThreadEntry)
    if kernel32.Thread32First(snapshot, ctypes.byref(entry)):
        while True:
            if entry.th32OwnerProcessID == pid:
                threads += 1
            if not kernel32.Thread32Next(snapshot, ctypes.byref(entry)):
                break
    kernel32.CloseHandle(snapshot)
    return {"threads": threads, "handles": count.value, "private_mb": round(counters.PrivateUsage / 2**20, 2),
            "working_set_mb": round(counters.WorkingSetSize / 2**20, 2)}


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Host:
    def __init__(self, runner: Path, bundle: Path, raw: dict, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.connection = directory / "studio.connection.json"
        settings = ConnectionSettings(raw["plugin"]["id"], project_digest(raw), free_port(), secrets.token_hex(32))
        self.connection.write_bytes(json_bytes(settings.as_dict()))
        self.runner, self.bundle, self.directory = runner, bundle, directory
        self.process = None

    def start(self, timeout: float = 30) -> float:
        started = time.monotonic()
        env = dict(os.environ, LOGI_HOST_STDIN_LIFETIME="1", PYTHONIOENCODING="utf-8")
        for name in ("PYTHONPATH", "PYTHONHOME"):
            env.pop(name, None)
        log = (self.directory / "host.log").open("ab")
        self.process = subprocess.Popen([str(self.runner), "-I", "-B", str(self.bundle), str(self.connection)],
                                        stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                                        cwd=str(self.directory), env=env,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        log.close()
        while True:
            try:
                self.client().handshake()
                return time.monotonic() - started
            except HostError:
                if self.process.poll() is not None or time.monotonic() - started > timeout:
                    raise RuntimeError((self.directory / "host.log").read_text(errors="replace")[-1500:])
                time.sleep(0.05)

    def client(self) -> LocalClient:
        return LocalClient(ConnectionSettings.load(self.connection), timeout=5)

    def stop(self, timeout: float = 10) -> int:
        self.process.stdin.close()
        try:
            return self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
            return -9


def handshake(client: LocalClient, timeout: float = 90) -> None:
    """The host admits 16 sessions per 60 s (idle ones expire): wait like the bridge would."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            client.handshake()
            return
        except HostError as exc:
            if exc.code != "HOST_BUSY" or time.monotonic() > deadline:
                raise
            time.sleep(1)


def poll_storm(host: Host, total: int, workers: int, sample_every: int) -> dict:
    samples, errors, done = [], {}, [0]
    lock = threading.Lock()

    def worker(count):
        client = host.client()
        handshake(client)
        cursor = 0
        for _ in range(count):
            try:
                cursor = client.poll(cursor).get("seq", cursor)
            except HostError as exc:
                with lock:
                    errors[exc.code] = errors.get(exc.code, 0) + 1
                if exc.code.startswith("SESSION") or exc.code == "RUNTIME_CHANGED":
                    handshake(client)
            with lock:
                done[0] += 1
                if done[0] % sample_every == 0:
                    samples.append({"requests": done[0], **metrics(host.process.pid)})
    started = time.monotonic()
    threads = [threading.Thread(target=worker, args=(total // workers,)) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return {"requests": done[0], "workers": workers, "seconds": round(time.monotonic() - started, 1),
            "errors": errors, "samples": samples}


def command_storm(host: Host, total: int, component: str, sample_every: int) -> dict:
    client = host.client()
    handshake(client)
    results, errors, first_error, samples = 0, {}, None, []
    started = time.monotonic()
    for index in range(1, total + 1):
        try:
            client.command(component)
            results += 1
        except HostError as exc:
            errors[exc.code] = errors.get(exc.code, 0) + 1
            if first_error is None:
                first_error = {"command_number": index, "code": exc.code, "message": str(exc)}
        if index % sample_every == 0:
            samples.append({"commands": index, **metrics(host.process.pid)})
    # Let the handler thread drain, then read the journal's final sequence.
    time.sleep(1.0)
    return {"sent": total, "accepted": results, "errors": errors, "first_error": first_error,
            "seconds": round(time.monotonic() - started, 1), "samples": samples}


def sustained(host: Host, seconds: float, polls_per_s: float, commands_per_s: float, component: str) -> dict:
    """Rate-limited load like the C# bridge (it polls every 250 ms) – accelerated."""
    client = host.client()
    handshake(client)
    cursor, polls, commands, errors, samples = 0, 0, 0, {}, []
    started = time.monotonic()
    next_poll = next_command = next_sample = started
    while (now := time.monotonic()) - started < seconds:
        if now >= next_command and commands_per_s:
            next_command += 1 / commands_per_s
            try:
                client.command(component)
                commands += 1
            except HostError as exc:
                errors[exc.code] = errors.get(exc.code, 0) + 1
                if exc.code.startswith("SESSION"):
                    handshake(client)
        if now >= next_poll:
            next_poll += 1 / polls_per_s
            try:
                cursor = client.poll(cursor).get("seq", cursor)
                polls += 1
            except HostError as exc:
                errors[exc.code] = errors.get(exc.code, 0) + 1
                if exc.code.startswith("SESSION"):
                    handshake(client)
        if now >= next_sample:
            next_sample += 20
            samples.append({"t": round(now - started), "polls": polls, "commands": commands,
                            **metrics(host.process.pid)})
        time.sleep(max(0.0, min(next_poll, next_command if commands_per_s else next_poll) - time.monotonic()))
    samples.append({"t": round(time.monotonic() - started), "polls": polls, "commands": commands,
                    **metrics(host.process.pid)})
    return {"seconds": seconds, "polls": polls, "commands": commands, "errors": errors, "samples": samples,
            "polls_per_s": polls_per_s, "commands_per_s": commands_per_s}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True, help="host runtime directory (contains the runner)")
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--polls", type=int, default=40000)
    parser.add_argument("--commands", type=int, default=6000)
    parser.add_argument("--cycles", type=int, default=40)
    parser.add_argument("--parallel", type=int, default=6)
    parser.add_argument("--sustained-seconds", type=float, default=300)
    args = parser.parse_args(argv)
    args.runtime, args.work, args.out = args.runtime.resolve(), args.work.resolve(), args.out.resolve()
    runner = args.runtime / RUNNER_NAME
    raw = json.loads((ROOT / "examples/project_logitech_native_v1.json").read_text(encoding="utf-8"))
    raw["plugin"]["id"] = "polish.stress"
    args.work.mkdir(parents=True, exist_ok=True)
    bundle = args.work / "native-host.pyz"
    bundle.write_bytes(native_host_bundle(raw, None, "native", DEFAULT_MANIFEST_DIR, None))
    report = {"format": "polish-stress-1", "runner": str(runner), "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "python_of_tool": sys.version.split()[0], "phases": {}}
    component = next(c["id"] for c in raw["actions"]) if "actions" in raw else "action.command"

    host = Host(runner, bundle, raw, args.work / "main")
    report["phases"]["startup_seconds"] = round(host.start(), 2)
    report["phases"]["idle_metrics"] = metrics(host.process.pid)
    report["phases"]["poll_storm"] = poll_storm(host, args.polls, 4, max(1, args.polls // 20))
    report["phases"]["after_polls_idle_5s"] = (time.sleep(5), metrics(host.process.pid))[1]
    report["phases"]["command_storm"] = command_storm(host, args.commands, component, max(1, args.commands // 12))
    report["phases"]["after_commands_metrics"] = metrics(host.process.pid)
    report["phases"]["main_exit_code"] = host.stop()

    # Sustained, bridge-like rates on a fresh host (25x the real poll rate, far
    # more key presses than a person produces): no errors, flat metrics expected.
    steady = Host(runner, bundle, raw, args.work / "sustained")
    steady.start()
    report["phases"]["sustained"] = sustained(steady, args.sustained_seconds, 100.0, 25.0, component)
    report["phases"]["sustained_exit_code"] = steady.stop()

    cycles = []
    cycle_host = Host(runner, bundle, raw, args.work / "cycles")
    for index in range(args.cycles):
        seconds = cycle_host.start()
        pid = cycle_host.process.pid
        client = cycle_host.client()
        handshake(client)
        client.command(component)
        code = cycle_host.stop()
        cycles.append({"cycle": index + 1, "startup_s": round(seconds, 2), "exit": code, "pid": pid})
    report["phases"]["start_stop_cycles"] = {
        "cycles": len(cycles), "nonzero_exits": [c for c in cycles if c["exit"] != 0],
        "max_startup_s": max(c["startup_s"] for c in cycles), "avg_startup_s": round(
            sum(c["startup_s"] for c in cycles) / len(cycles), 2)}

    # Reconnect: a client keeps working across host restarts (same connection).
    reconnect = Host(runner, bundle, raw, args.work / "reconnect")
    reconnect.start()
    client = reconnect.client()
    handshake(client)
    reconnects = []
    for index in range(10):
        reconnect.stop()
        reconnect.start()
        try:
            client.poll(0)
            stale = "ACCEPTED"
        except HostError as exc:
            stale = exc.code  # expected: old session is rejected, then re-handshake
        handshake(client)
        client.command(component)
        reconnects.append({"restart": index + 1, "old_session": stale, "rehandshake": "OK"})
    reconnect.stop()
    report["phases"]["reconnect"] = reconnects

    hosts = [Host(runner, bundle, raw, args.work / f"parallel-{i}") for i in range(args.parallel)]
    for h in hosts:
        h.start()
    results = {}

    def drive(index, h):
        results[index] = {"polls": poll_storm(h, 2000, 1, 1000)["errors"],
                          "commands": command_storm(h, 300, component, 300)["errors"]}
    threads = [threading.Thread(target=drive, args=(i, h)) for i, h in enumerate(hosts)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    report["phases"]["parallel"] = {"hosts": len(hosts), "errors": results,
                                    "exit_codes": [h.stop() for h in hosts]}
    report["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = {k: v for k, v in report["phases"].items() if k not in ("poll_storm", "command_storm", "reconnect")}
    summary["poll_errors"] = report["phases"]["poll_storm"]["errors"]
    summary["command_first_error"] = report["phases"]["command_storm"]["first_error"]
    summary["command_errors"] = report["phases"]["command_storm"]["errors"]
    summary["sustained"] = {k: v for k, v in report["phases"]["sustained"].items() if k != "samples"}
    summary["sustained_first_last_sample"] = [report["phases"]["sustained"]["samples"][0],
                                              report["phases"]["sustained"]["samples"][-1]]
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
