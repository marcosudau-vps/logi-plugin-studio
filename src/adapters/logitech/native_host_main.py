"""Entrypoint stored as __main__.py of a generated ``native-host.pyz``.

The bundle contains the frozen project snapshot, the Studio core/runtime
modules and optionally ONE trusted, project-relative handler file chosen by
the author (``register(host)``). Without such a file every handler route is
bound to a recorder that only appends a JSON line per SDK callback to
``callbacks.jsonl`` beside the connection file: no code is ever derived from
project JSON. The host runs until stdin reaches EOF or the process is stopped.
"""
import importlib.util
import json
import logging
import os
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from runtime.wire import ConnectionSettings


def _recorder(path, lock):
    def record(payload, context):
        row = dict(time=time.time(), component=context.component_id, placement=context.placement_id,
                   parameter=context.action_parameter, operation=context.operation,
                   diff=context.adjustment_diff, command=context.command_id, pid=os.getpid())
        with lock, path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(row, ensure_ascii=True) + "\n")
        return {"ok": True}
    return record


def _configure_logging(plugin_id):
    """Studio-managed hosts log to stdout (captured by the Studio). A host the
    plugin started itself (``LOGI_HOST_LOG=plugin``) has no console: keep a
    bounded, secret-free log in the user's Studio data directory instead."""
    fmt = "%(asctime)s %(process)d %(threadName)s %(levelname)s %(message)s"
    if os.environ.get("LOGI_HOST_LOG") == "plugin" and (os.environ.get("LOCALAPPDATA")
                                                         or os.environ.get("LOGI_HOST_LOG_DIR")):
        try:
            from logging.handlers import RotatingFileHandler
            directory = Path(os.environ.get("LOGI_HOST_LOG_DIR") or
                             Path(os.environ["LOCALAPPDATA"]) / "LogiPluginStudio" / "HostLogs")
            directory.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(directory / (plugin_id + ".log"), maxBytes=262144, backupCount=1,
                                          encoding="utf-8")
            logging.basicConfig(level=logging.INFO, handlers=[handler], format=fmt)
            return
        except Exception:  # logging must never prevent the host from starting
            pass
    logging.basicConfig(level=logging.INFO, format=fmt)


def _heartbeat(host, interval=30.0):
    """Secret-free liveness line: bridge sessions, commands, threads (diagnosis aid)."""
    time.sleep(5)
    while True:
        try:
            d = host.diagnostics()
            logging.info("heartbeat sessions=%s commands=%s sequence=%s queue=%s threads=%s",
                         d["session_count"], d["command_count"], d["sequence"], d["queue_depth"],
                         threading.active_count())
        except Exception as exc:  # never let diagnostics stop the host
            logging.warning("heartbeat failed: %s", type(exc).__name__)
        time.sleep(interval)


def main():
    connection = Path(sys.argv[1]).resolve()
    settings = ConnectionSettings.load(connection)
    _configure_logging(settings.plugin_id)
    with zipfile.ZipFile(sys.argv[0]) as bundle, tempfile.TemporaryDirectory(prefix="logi-native-host-") as data:
        read = lambda name: json.loads(bundle.read("native/" + name + ".json"))
        manifest_dir = Path(data)
        for name in read("manifests"):
            (manifest_dir / name).write_bytes(bundle.read("native/manifests/" + name))
        project, layout, mode = read("project"), read("layout"), read("mode")
        if mode == "native":
            from runtime.host import PluginHost
            host = PluginHost(project, settings, manifest_dir=manifest_dir)
        else:
            from extensions.shared_folders.host import FolderRuntimeHost
            host = FolderRuntimeHost(project, settings, folder_runtime=layout, manifest_dir=manifest_dir)
        if importlib.util.find_spec("studio_plugin_handler") is not None:
            from studio_plugin_handler import register
            register(host)
        else:
            handlers = {h["id"] for h in project.get("handlers", [])}
            record = _recorder(connection.parent / "callbacks.jsonl", threading.Lock())
            for component, port in sorted(host._plan.targets):
                if component in handlers:
                    host.register_handler(component, port, record)
        with host:
            print(f"HOST_READY plugin={settings.plugin_id} port={settings.port} mode={mode}", flush=True)
            if os.environ.get("LOGI_HOST_LOG") == "plugin":
                threading.Thread(target=_heartbeat, args=(host,), name="studio-heartbeat", daemon=True).start()
            if os.environ.get("LOGI_HOST_STDIN_LIFETIME") == "1":
                # Owned by a parent (Studio): EOF on stdin ends the host.
                while sys.stdin.buffer.read(4096):
                    pass
            else:
                while True:
                    time.sleep(0.5)


if __name__ == "__main__":
    main()
