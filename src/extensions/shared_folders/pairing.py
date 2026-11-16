"""User-facing administration of the EXISTING peer policy files (no transport).

The Shared runtime reads ``<home>/config/<plugin_id>.json`` at plugin start
(``embedded_host.policy``). This module is the only Studio writer for those
files and keeps the security contract of AP-SHARED-FINAL-001:

* Pairing (a shared random 256-bit key per plugin pair) and permissions are
  separate steps. A new pairing grants nothing; a reference alone never makes a
  foreign action executable.
* Grants are directed (owner → consumer), exact (scope incl. parameter) and are
  never widened implicitly: changing operations of an existing grant requires
  the explicit ``replace=True`` path.
* Keys never leave the per-user policy directory: no project JSON, package,
  export, log, audit line or UI text contains them. Files are written
  atomically and, on Windows, ACL-restricted to the current user.
* AP-POLISH-001: keys are stored DPAPI-protected for the current Windows user
  (``key_protected``, see ``secret_store``). Plaintext policies of older
  versions stay readable and are migrated by :meth:`PairingStore.migrate` –
  except for a plugin whose installed build predates 1.0 (its embedded host
  only reads plaintext); that file is migrated after the plugin's next update.
  A key that cannot be decrypted is reported, never silently regenerated.
* Every written file is re-validated with the runtime's own parser; anything the
  runtime would reject is refused before writing (fail closed).
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from runtime.wire import HostError, json_bytes, parse_json

from . import secret_store
from .peer_runtime import OPERATIONS, Scope
from .peer_wire import MAX_PEERS, MAX_SCOPES, PeerError, resource_id

STATUS_FRESH_SECONDS = 5.0


class PairingError(ValueError):
    pass


def shared_home() -> Path:
    configured = os.environ.get("LOGI_SHARED_HOME")
    if configured:
        root = Path(configured)
        if not root.is_absolute():
            raise PairingError("LOGI_SHARED_HOME must be absolute")
        return root
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise PairingError("LOCALAPPDATA is not configured")
    return Path(base) / "LogiPluginStudio" / "SharedFolders"


def _restrict(path: Path) -> None:
    """Best effort: owner-only ACL (Windows) or 0600/0700 permissions."""
    if os.name == "nt":
        user = os.environ.get("USERNAME")
        if not user:
            return
        try:
            subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(OI)(CI)F" if path.is_dir()
                            else f"{user}:F"], capture_output=True, timeout=20, shell=False,
                           stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        os.chmod(path, 0o700 if path.is_dir() else 0o600)


@dataclass(frozen=True)
class Grant:
    owner: str
    consumer: str
    scope: Scope
    operations: tuple[str, ...]

    def describe(self) -> str:
        what = f"{self.scope.kind}:{self.scope.resource}"
        if self.scope.parameter is not None:
            what += f" [{self.scope.parameter}]"
        ops = ", ".join(self.operations) or "nur anzeigen"
        return f"{self.owner} → {self.consumer}: {what} ({ops})"


def installed_plaintext_only(plugin: str) -> bool:
    """True if an installed Studio build of ``plugin`` cannot read protected keys."""
    try:
        from adapters.logitech.deployment import installed_key_support
        return installed_key_support(plugin) == "plaintext-only"
    except Exception:  # no plugin directory / not readable: nothing installed to protect
        return False


class PairingStore:
    def __init__(self, home: Path | None = None, *, plaintext_only=installed_plaintext_only):
        self.home = Path(home) if home is not None else shared_home()
        self._plaintext_only = plaintext_only

    # -- files ---------------------------------------------------------------
    @property
    def config_dir(self) -> Path:
        return self.home / "config"

    def _path(self, plugin: str) -> Path:
        if not resource_id(plugin):
            raise PairingError(f"Ungültige Plugin-ID: {plugin!r}")
        return self.config_dir / (plugin + ".json")

    def _read(self, plugin: str) -> dict:
        path = self._path(plugin)
        if not path.is_file():
            return {"peers": {}}
        try:
            row = parse_json(path.read_bytes(), limit=65536)
        except (OSError, ValueError, HostError) as exc:
            raise PairingError(f"Policy von {plugin} ist unlesbar; Runtime arbeitet nur lokal ({exc})") from exc
        if set(row) != {"peers"} or not isinstance(row["peers"], dict):
            raise PairingError(f"Policy von {plugin} ist ungültig; Runtime arbeitet nur lokal")
        return row

    def _load(self, plugin: str, *, replace_unreadable: tuple[str, ...] = ()) -> dict:
        """Policy in memory form: every peer carries its key as ``key`` (hex).

        ``replace_unreadable`` lists peers whose key is about to be replaced by
        an EXPLICIT user action (re-key/unpair): only their undecryptable key
        is tolerated (``key: None``); any other unreadable key still fails."""
        row = self._read(plugin)
        for peer, item in row["peers"].items():
            if isinstance(item, dict) and "key_protected" in item:
                try:
                    secret = secret_store.unprotect(item["key_protected"], owner=plugin, peer=peer)
                except secret_store.SecretUnavailable as exc:
                    if peer in replace_unreadable:
                        row["peers"][peer] = {"key": None, "grants": item.get("grants")}
                        continue
                    raise PairingError(
                        f"Geschützter Schlüssel von {plugin} → {peer} kann nicht entschlüsselt werden "
                        "(anderes Windows-Konto oder beschädigt). Runtime arbeitet nur lokal. "
                        "Abhilfe: Paarung ausdrücklich „Neu verschlüsseln“ oder entpaaren und neu paaren.") from exc
                grants = item.get("grants")
                row["peers"][peer] = {"key": secret.hex(), "grants": grants}
        return row

    def protects(self, plugin: str) -> bool:
        """Whether this plugin's policy is (to be) stored DPAPI-protected.

        The installed-build check hashes installed packages; it is cached
        briefly because the Studio status view polls."""
        if not secret_store.available():
            return False
        cache = self.__dict__.setdefault("_protect_cache", {})
        hit = cache.get(plugin)
        if hit is None or time.monotonic() - hit[0] > 30:
            hit = cache[plugin] = (time.monotonic(), not self._plaintext_only(plugin))
        return hit[1]

    def _disk_form(self, plugin: str, row: dict) -> dict:
        if not self.protects(plugin):
            return row
        peers = {}
        for peer, item in row["peers"].items():
            key = item.get("key")
            if not isinstance(key, str) or len(key) != 64:
                raise PairingError("Policy enthält einen ungültigen Schlüssel; nichts geschrieben")
            try:
                token = secret_store.protect(bytes.fromhex(key), owner=plugin, peer=peer)
            except (ValueError, secret_store.SecretUnavailable) as exc:
                raise PairingError("Schlüssel konnte nicht geschützt werden; nichts geschrieben") from exc
            peers[peer] = {"key_protected": token, "grants": item.get("grants", [])}
        return {"peers": peers}

    def key_storage(self, plugin: str) -> str:
        """``none`` | ``protected`` | ``plaintext`` | ``plaintext-required`` (old installed build)."""
        try:
            row = self._read(plugin)
        except PairingError:
            return "invalid"
        items = [i for i in row["peers"].values() if isinstance(i, dict)]
        if not items:
            return "none"
        if all("key_protected" in i for i in items):
            return "protected"
        return "plaintext" if self.protects(plugin) else "plaintext-required"

    def migrate(self) -> dict:
        """Protect plaintext keys of all policies whose installed plugin supports it.

        Keys, peers and grants are carried over unchanged (no new key, no new
        grant). Files that fail to load stay untouched and are reported.
        """
        result = {"protected": [], "kept_plaintext": [], "failed": {}}
        for plugin in self.configured_plugins():
            state = self.key_storage(plugin)
            if state == "plaintext-required":
                result["kept_plaintext"].append(plugin)
                continue
            if state != "plaintext":
                continue
            try:
                row = self._load(plugin)
                self._save(plugin, row)
            except PairingError as exc:
                result["failed"][plugin] = str(exc)
                continue
            result["protected"].append(plugin)
        if result["protected"]:
            self._audit("protect_keys", plugins=result["protected"])
        return result

    def _validate(self, plugin: str, row: dict) -> None:
        """Use the runtime's own parser so Studio never writes a rejected policy."""
        from .embedded_host import policy
        with tempfile.TemporaryDirectory(prefix="pairing-check-") as temp:
            (Path(temp) / "config").mkdir()
            (Path(temp) / "config" / (plugin + ".json")).write_bytes(json_bytes(row))
            try:
                trust = policy(Path(temp), plugin)
            except (PeerError, ValueError, TypeError) as exc:
                raise PairingError(f"Policy wäre für die Runtime ungültig: {exc}") from exc
        if plugin in trust or len(trust) > MAX_PEERS or len({t.key for t in trust.values()}) != len(trust):
            raise PairingError("Policy verletzt Peergrenzen (Selbstpaarung, >16 Peers oder doppelter Schlüssel)")
        if sum(len(t.grants) for t in trust.values()) > MAX_SCOPES:
            raise PairingError("Mehr als 128 freigegebene Scopes")

    def _save(self, plugin: str, row: dict) -> None:
        row = self._disk_form(plugin, row)
        self._validate(plugin, row)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        _restrict(self.home)
        path = self._path(plugin)
        handle, temporary = tempfile.mkstemp(dir=self.config_dir, prefix=".policy-", suffix=".tmp")
        try:
            with os.fdopen(handle, "wb") as output:
                output.write(json_bytes(row))
                output.flush()
                os.fsync(output.fileno())
            _restrict(Path(temporary))
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _audit(self, action: str, **detail) -> None:
        # Never a key, never a policy body.
        detail = {k: v for k, v in detail.items() if k != "key"}
        self.home.mkdir(parents=True, exist_ok=True)
        with (self.home / "audit.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps(dict(time=time.time(), action=action, **detail), ensure_ascii=True) + "\n")

    # -- queries ---------------------------------------------------------------
    def configured_plugins(self) -> list[str]:
        if not self.config_dir.is_dir():
            return []
        return sorted(p.stem for p in self.config_dir.glob("*.json") if resource_id(p.stem))

    def peers(self, plugin: str) -> list[str]:
        return sorted(self._load(plugin)["peers"])

    def is_paired(self, a: str, b: str) -> bool:
        try:
            ka = self._load(a)["peers"].get(b, {}).get("key")
            kb = self._load(b)["peers"].get(a, {}).get("key")
        except PairingError:
            return False
        return isinstance(ka, str) and ka == kb

    def grants(self, owner: str) -> list[Grant]:
        result = []
        for consumer, item in sorted(self._load(owner)["peers"].items()):
            for row in item.get("grants", []):
                result.append(Grant(owner, consumer, Scope.parse(row["scope"]), tuple(row["operations"])))
        return result

    def check(self, plugin: str) -> list[str]:
        """Human-readable problems (empty = the runtime accepts this policy)."""
        problems = []
        try:
            row = self._load(plugin)
            self._validate(plugin, row)
        except PairingError as exc:
            return [str(exc)]
        for peer in row["peers"]:
            if not self.is_paired(plugin, peer):
                problems.append(f"Paarung mit {peer} ist einseitig oder Schlüssel unterscheiden sich; neu paaren.")
        return problems

    # -- pairing ---------------------------------------------------------------
    def pair(self, a: str, b: str, *, rekey: bool = False) -> None:
        if a == b:
            raise PairingError("Ein Plugin kann nicht mit sich selbst gepaart werden")
        tolerate = (lambda peer: (peer,)) if rekey else (lambda peer: ())
        ra, rb = self._load(a, replace_unreadable=tolerate(b)), self._load(b, replace_unreadable=tolerate(a))
        if (b in ra["peers"] or a in rb["peers"]) and not rekey:
            raise PairingError("Paar existiert bereits; zum Erneuern ausdrücklich neu verschlüsseln")
        key = secrets.token_hex(32)
        ra["peers"][b] = {"key": key, "grants": ra["peers"].get(b, {}).get("grants", []) if rekey else []}
        rb["peers"][a] = {"key": key, "grants": rb["peers"].get(a, {}).get("grants", []) if rekey else []}
        self._validate(a, ra)
        self._validate(b, rb)
        self._save(a, ra)
        self._save(b, rb)
        self._audit("rekey" if rekey else "pair", plugins=sorted((a, b)))

    def unpair(self, a: str, b: str) -> None:
        ra, rb = self._load(a, replace_unreadable=(b,)), self._load(b, replace_unreadable=(a,))
        if b not in ra["peers"] and a not in rb["peers"]:
            raise PairingError("Diese Plugins sind nicht gepaart")
        ra["peers"].pop(b, None)
        rb["peers"].pop(a, None)
        self._save(a, ra)
        self._save(b, rb)
        self._audit("unpair", plugins=sorted((a, b)))

    # -- permissions -------------------------------------------------------------
    def grant(self, owner: str, consumer: str, scope: Scope, operations, *, offers: dict | None = None,
              replace: bool = False) -> Grant:
        """Allow ``consumer`` to see (and optionally invoke) ONE owner scope.

        ``offers`` (scope → allowed operations, from the owner's project) lets
        the Studio refuse scopes the owner runtime would reject at start.
        """
        operations = tuple(sorted(set(operations)))
        if not set(operations) <= OPERATIONS:
            raise PairingError("Unbekannte Operation")
        if scope.kind == "folder" and operations:
            raise PairingError("Ordnerfreigaben sind nur lesend; Actions einzeln freigeben")
        if offers is not None:
            allowed = offers.get(scope)
            if allowed is None:
                raise PairingError("Owner bietet diesen Scope nicht an (unbekannte Action/Parameter/Ordner)")
            if not set(operations) <= set(allowed):
                raise PairingError(f"Operation für diesen Actiontyp nicht erlaubt (erlaubt: {', '.join(allowed) or '-'})")
        if not self.is_paired(owner, consumer):
            raise PairingError("Zuerst die beiden Plugins paaren; Pairing und Freigabe sind getrennt")
        row = self._load(owner)
        rows = row["peers"][consumer]["grants"]
        existing = next((g for g in rows if Scope.parse(g["scope"]) == scope), None)
        if existing is not None:
            if tuple(sorted(existing["operations"])) == operations:
                return Grant(owner, consumer, scope, operations)
            if not replace:
                raise PairingError("Freigabe existiert mit anderen Operationen; Änderung ausdrücklich bestätigen")
            existing["operations"] = list(operations)
        else:
            rows.append({"scope": scope.wire(), "operations": list(operations)})
        self._save(owner, row)
        self._audit("grant", owner=owner, consumer=consumer, scope=scope.wire(), operations=list(operations))
        return Grant(owner, consumer, scope, operations)

    def revoke(self, owner: str, consumer: str, scope: Scope) -> None:
        row = self._load(owner)
        item = row["peers"].get(consumer)
        if item is None:
            raise PairingError("Kein Paar")
        before = len(item["grants"])
        item["grants"] = [g for g in item["grants"] if Scope.parse(g["scope"]) != scope]
        if len(item["grants"]) == before:
            raise PairingError("Keine solche Freigabe")
        self._save(owner, row)
        self._audit("revoke", owner=owner, consumer=consumer, scope=scope.wire())

    # -- runtime observation (read-only) -----------------------------------------
    def status(self, plugin: str) -> dict:
        """Secret-free status published by a running Shared plugin, if fresh."""
        path = self.home / "status" / (hashlib.sha256(plugin.encode()).hexdigest() + ".json")
        discovery = self.home / "discovery" / (hashlib.sha256(plugin.encode()).hexdigest() + ".json")
        try:
            row = parse_json(path.read_bytes(), limit=65536)
        except (OSError, ValueError, HostError):
            return {"plugin": plugin, "online": False, "registered": discovery.is_file(), "peers": {}}
        fresh = isinstance(row.get("time"), (int, float)) and time.time() - row["time"] <= STATUS_FRESH_SECONDS
        return {"plugin": plugin, "online": fresh and row.get("plugin") == plugin, "registered": discovery.is_file(),
                "sdk_attached": bool(row.get("sdk_attached")) and fresh, "peers": row.get("peers", {}) if fresh else {},
                "instance": row.get("instance"), "age": time.time() - row.get("time", 0)}


def project_offers(raw: dict, layout: dict | None = None) -> dict:
    """Scopes an owner project can export, with their permitted operations.

    Mirrors the owner runtime (``SharedFolderHost``): command-like SDK actions
    allow ``command``; adjustments allow ``adjustment`` (+``command`` if reset).
    """
    from adapters.logitech.native import project_view
    native = project_view(raw)
    offers = {}
    for action in native.actions:
        if action.sdk_type in ("PluginDynamicCommand", "PluginMultistateDynamicCommand"):
            ops = ("command",)
        elif action.sdk_type == "PluginDynamicAdjustment":
            ops = ("adjustment", "command") if action.has_reset else ("adjustment",)
        else:
            continue
        offers[Scope("action", action.id)] = ops
        for parameter in action.parameters:
            offers[Scope("action", action.id, parameter.name)] = ops
    if layout is not None:
        for folder in layout.get("folders", []):
            for node in folder.get("nodes", []):
                offers[Scope("folder", node["id"])] = ()
    return offers
