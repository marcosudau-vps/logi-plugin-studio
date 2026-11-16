"""User-bound protection of Shared peer keys with Windows DPAPI (stdlib only).

Used by the Studio (``PairingStore``) to write and by the embedded Shared host
(``embedded_host.policy``) to read peer keys. Both run as the same Windows
user as the Logi Plugin Service, so ``CryptProtectData`` without
``CRYPTPROTECT_LOCAL_MACHINE`` binds a key to exactly this user account.

* The optional entropy binds every blob to its policy slot (owner plugin,
  peer plugin): a blob copied into another slot does not decrypt.
* Errors never contain key material. A blob that cannot be decrypted raises
  :class:`SecretUnavailable`; callers must fail closed and must not create a
  replacement key silently.
"""
from __future__ import annotations

import base64
import os

PREFIX = "dpapi-user-1:"
FORMAT = "dpapi-user-1"
_ENTROPY = b"LogiPluginStudio/shared-peer-key/1\x00"
_UI_FORBIDDEN = 0x1
_MAX_BLOB = 4096


class SecretUnavailable(Exception):
    """A protected secret cannot be used (wrong user, damaged, unsupported OS)."""


def available() -> bool:
    return os.name == "nt"


def _entropy(owner: str, peer: str) -> bytes:
    return _ENTROPY + owner.encode("utf-8") + b"\x00" + peer.encode("utf-8")


def _call(function: str, data: bytes, entropy: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(value: bytes):
        buffer = ctypes.create_string_buffer(value, len(value))
        return Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    source, keep_source = blob(data)
    extra, keep_extra = blob(entropy)
    output = Blob()
    fn = getattr(crypt32, function)
    fn.restype = wintypes.BOOL
    # Same signature for CryptProtectData / CryptUnprotectData (description out-param unused).
    ok = fn(ctypes.byref(source), None, ctypes.byref(extra), None, None, _UI_FORBIDDEN, ctypes.byref(output))
    del keep_source, keep_extra
    if not ok:
        raise SecretUnavailable(f"{function} failed (Windows error {ctypes.get_last_error()})")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))


def protect(secret: bytes, *, owner: str, peer: str) -> str:
    """Encrypt ``secret`` for the current Windows user; returns a text token."""
    if not available():
        raise SecretUnavailable("DPAPI requires Windows")
    return PREFIX + base64.b64encode(_call("CryptProtectData", secret, _entropy(owner, peer))).decode("ascii")


def unprotect(token: str, *, owner: str, peer: str) -> bytes:
    """Decrypt a token written by :func:`protect` for the same slot and user."""
    if not isinstance(token, str) or not token.startswith(PREFIX) or len(token) > _MAX_BLOB:
        raise SecretUnavailable("Unsupported protected key format")
    if not available():
        raise SecretUnavailable("DPAPI requires Windows")
    try:
        data = base64.b64decode(token[len(PREFIX):], validate=True)
    except (ValueError, TypeError) as exc:
        raise SecretUnavailable("Protected key is not valid base64") from exc
    return _call("CryptUnprotectData", data, _entropy(owner, peer))
