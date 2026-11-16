"""Entrypoint stored as __main__.py in each generated Shared plugin assembly."""
import importlib.util
import json
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile

from extensions.shared_folders.peer_host import SharedFolderHost
from extensions.shared_folders.peer_runtime import Scope, Trust
from extensions.shared_folders.peer_wire import PeerError, shape
from runtime.wire import ConnectionSettings, HostError, parse_json


def policy(home, plugin):
    path = home / "config" / (plugin + ".json")
    if not path.is_file():
        # Diagnosable, secret-free: an absent policy means local-only operation.
        logging.info("No peer policy file at %s (config dir exists=%s, entries=%s)", path,
                     path.parent.is_dir(), sorted(p.name for p in path.parent.glob("*.json"))[:20]
                     if path.parent.is_dir() else [])
        return {}
    with path.open("rb") as handle:
        row = parse_json(handle.read(65537))
    shape(row, "peers")
    if not isinstance(row["peers"], dict):
        raise PeerError("INVALID_POLICY")
    trust = {}
    for peer, item in row["peers"].items():
        if isinstance(item, dict) and "key_protected" in item:
            # AP-POLISH-001: user-bound DPAPI blob (Studio ≥ 1.0). A blob that
            # cannot be decrypted (other Windows account, damaged) rejects the
            # whole policy: the host stays local-only, nothing is regenerated.
            shape(item, "key_protected", "grants")
            from extensions.shared_folders.secret_store import SecretUnavailable, unprotect
            try:
                secret = unprotect(item["key_protected"], owner=plugin, peer=peer)
            except SecretUnavailable as exc:
                raise PeerError("POLICY_KEY_UNAVAILABLE") from exc
            if len(secret) != 32:
                raise PeerError("INVALID_POLICY")
            key = secret.hex()
        else:
            shape(item, "key", "grants")
            key = item["key"]
        if not isinstance(key, str) or re.fullmatch("[0-9a-f]{64}", key) is None or not isinstance(item["grants"], list):
            raise PeerError("INVALID_POLICY")
        grants = {}
        for grant in item["grants"]:
            shape(grant, "scope", "operations")
            scope = Scope.parse(grant["scope"])
            operations = grant["operations"]
            if scope in grants or not isinstance(operations, list) or any(not isinstance(op, str) for op in operations):
                raise PeerError("INVALID_POLICY")
            grants[scope] = frozenset(operations)
        trust[peer] = Trust(bytes.fromhex(key), grants)
    return trust


def main():
    settings = ConnectionSettings.load(sys.argv[1])
    root = Path(os.environ.get("LOGI_SHARED_HOME") or Path(os.environ["LOCALAPPDATA"]) / "LogiPluginStudio" / "SharedFolders")
    if not root.is_absolute():
        raise PeerError("SHARED_HOME")
    # The SDK process discards the child's console; keep a bounded, secret-free log.
    try:
        from logging.handlers import RotatingFileHandler
        (root / "logs").mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(root / "logs" / (settings.plugin_id + ".log"), maxBytes=262144,
                                      backupCount=1, encoding="utf-8")
        logging.basicConfig(level=logging.INFO, handlers=[handler],
                            format="%(asctime)s %(process)d %(threadName)s %(levelname)s %(name)s %(message)s")
    except Exception:  # logging must never prevent the host from starting
        pass
    logging.info("Shared host start plugin=%s pid=%s", settings.plugin_id, os.getpid())
    with zipfile.ZipFile(sys.argv[0]) as bundle, tempfile.TemporaryDirectory(prefix="logi-shared-host-") as data:
        read = lambda name: json.loads(bundle.read("shared/" + name + ".json"))
        manifest_dir = Path(data)
        for name in read("manifests"):
            (manifest_dir / name).write_bytes(bundle.read("shared/manifests/" + name))
        project = read("project")
        options = dict(folder_runtime=read("layout"), shared_references=read("references"),
                       directory=root / "discovery", manifest_dir=manifest_dir)
        try:
            trust = policy(root, settings.plugin_id)
            host = SharedFolderHost(project, settings, trust=trust, **options)
            logging.info("Peer policy accepted: peers=%d grants=%d", len(trust),
                         sum(len(t.grants) for t in trust.values()))
        except (PeerError, HostError, OSError, TypeError, ValueError) as exc:
            logging.warning("Shared peer policy rejected (%s: %s); starting with local resources",
                            type(exc).__name__, exc)
            host = SharedFolderHost(project, settings, trust={}, **options)
        if importlib.util.find_spec("shared_plugin_handler") is not None:
            from shared_plugin_handler import register
            register(host)
        with host:
            # Only the parent owns this write end. No external stop command.
            while sys.stdin.buffer.read(4096):
                pass


if __name__ == "__main__":
    main()
