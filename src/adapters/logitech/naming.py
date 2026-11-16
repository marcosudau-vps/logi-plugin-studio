"""Deterministic C# identifiers, namespaces and escaped literals.

Every identifier produced here is ASCII-only, starts with a letter, is bounded
in length and ends with a short SHA-256 digest of the *source* string.  The
digest makes the mapping stable for a given input and collision-free even when
two different source ids sanitise to the same readable stem; it never depends
on the surrounding set of ids, so adding or renaming one action cannot silently
change the type name of another one.

The module is pure: no file system access, no SDK access, no global state.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

from .errors import NamingError

IDENTIFIER_MAX_LENGTH = 88
"""Upper bound for a generated C# type name (well below any compiler limit)."""

_ASCII_ALNUM = re.compile(r"[A-Za-z0-9]+")
_ASSEMBLY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:[._][A-Za-z0-9]+)*$")

CSHARP_KEYWORDS = frozenset(
    """
    abstract as base bool break byte case catch char checked class const continue
    decimal default delegate do double else enum event explicit extern false finally
    fixed float for foreach goto if implicit in int interface internal is lock long
    namespace new null object operator out override params private protected public
    readonly ref return sbyte sealed short sizeof stackalloc static string struct
    switch this throw true try typeof uint ulong unchecked unsafe ushort using
    virtual void volatile while
    """.split()
)


def sha8(text: str) -> str:
    """Short, deterministic digest of ``text`` (used for namespacing/length caps)."""
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()[:8]


def fold_ascii(text: str) -> str:
    """Fold arbitrary Unicode to plain ASCII letters/digits.

    Decomposes (NFKD), drops combining marks and keeps only ``[A-Za-z0-9]``.
    Everything else becomes a separator, so emoji, quotes, backslashes, path
    separators or control characters can never reach an identifier.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    ascii_only = stripped.encode("ascii", "ignore").decode("ascii")
    return " ".join(_ASCII_ALNUM.findall(ascii_only))


def pascal_stem(text: str, limit: int = 48) -> str:
    """Readable StudlyCaps stem, bounded to ``limit`` characters."""
    words = fold_ascii(text).split()
    if not words:
        return ""
    stem = "".join(word[:1].upper() + word[1:] for word in words)
    if len(stem) > limit:
        stem = stem[:limit]
    return stem


def identifier(prefix: str, source: str) -> str:
    """Build ``<Prefix>_<ReadableStem>_<digest8>`` for ``source``.

    ``prefix`` must be a plain ASCII identifier fragment supplied by the
    generator (never user data).  ``source`` is arbitrary user data.
    """
    if not prefix or not prefix.isalnum() or not prefix[0].isalpha():
        raise NamingError(f"Identifier prefix must be a plain ASCII word, got {prefix!r}")
    digest = sha8(source)
    budget = IDENTIFIER_MAX_LENGTH - len(prefix) - len(digest) - 2
    if budget < 8:
        raise NamingError(f"Identifier prefix {prefix!r} leaves no room for a stem")
    stem = pascal_stem(source, budget)
    if not stem:
        stem = "Unnamed"
    name = f"{prefix}_{stem}_{digest}"
    if not name[0].isalpha() or not all(ch.isalnum() or ch == "_" for ch in name):
        raise NamingError(f"Generated identifier is not C#-safe: {name!r}")
    if name in CSHARP_KEYWORDS:  # cannot happen with a prefix, kept as a guard
        raise NamingError(f"Generated identifier is a C# keyword: {name!r}")
    return name


def namespace_for(plugin_id: str) -> str:
    """Stable namespace for a plugin id, e.g. ``PluginStudio.Generated.Acme_Tools``."""
    if not isinstance(plugin_id, str) or not plugin_id:
        raise NamingError("Plugin id must be a non-empty string")
    stem = pascal_stem(plugin_id, 40) or "Plugin"
    suffix = f"_{sha8(plugin_id)}" if len(plugin_id) > 40 or not stem else ""
    return f"PluginStudio.Generated.{stem}{suffix}"


def validate_assembly_name(name: str) -> str:
    """Validate a caller-supplied assembly / plugin identifier.

    Allowed: ASCII letters, digits, ``_`` and ``.`` separated words, starting
    with a letter, at most 100 characters.  Nothing here is escaped later; an
    invalid value is rejected instead of being silently rewritten.
    """
    if not isinstance(name, str) or not name:
        raise NamingError("Assembly name must be a non-empty string")
    if len(name) > 100:
        raise NamingError("Assembly name must not exceed 100 characters")
    if not _ASSEMBLY_RE.fullmatch(name):
        raise NamingError(
            "Assembly name must match ^[A-Za-z][A-Za-z0-9]*(?:[._][A-Za-z0-9]+)*$ "
            f"(got {name!r})"
        )
    lowered = name.lower()
    if lowered.endswith(".dll"):
        raise NamingError("Assembly name must not include a file extension")
    windows_reserved = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {
        f"lpt{i}" for i in range(1, 10)
    }
    if lowered.split(".")[0] in windows_reserved:
        raise NamingError(f"Assembly name {name!r} is a reserved Windows device name")
    return name


def plugin_class_name(assembly_name: str) -> str:
    """Type name of the plugin class.

    The Logi Plugin Service derives the plugin name from the class name by
    removing the ``Plugin`` suffix, so the name is built as
    ``<StudlyAssemblyName>Plugin`` and never contains ``PluginPlugin``.
    """
    stem = pascal_stem(assembly_name, 60) or "Generated"
    if stem.endswith("Plugin"):
        stem = stem[: -len("Plugin")] or "Generated"
    return f"{stem}Plugin"


def sdk_action_name(plugin_id: str, component_id: str) -> str:
    """Stable, human-readable logical SDK name of one generated action."""
    return f"{plugin_id}:{component_id}"


_SIMPLE_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\r": "\\r",
    "\n": "\\n",
    "\t": "\\t",
    "\0": "\\0",
}


def csharp_literal(value: str) -> str:
    """Return a quoted C# string literal for arbitrary text.

    Handles quotes, backslashes, CR/LF/tab, other control characters, the line
    separators U+2028/U+2029 and unpaired surrogates.  Non-ASCII text is kept as
    UTF-8 (the generated sources are written as UTF-8); everything that could
    terminate the literal or the line is escaped, so JSON content can never
    inject code.
    """
    if not isinstance(value, str):
        raise NamingError(f"C# literal source must be a string, got {type(value).__name__}")
    out: list[str] = []
    for ch in value:
        mapped = _SIMPLE_ESCAPES.get(ch)
        if mapped is not None:
            out.append(mapped)
            continue
        code = ord(ch)
        if code < 0x20 or code == 0x7F or code in (0x2028, 0x2029) or 0xD800 <= code <= 0xDFFF:
            out.append(f"\\u{code:04X}")
            continue
        out.append(ch)
    return '"' + "".join(out) + '"'


def yaml_double_quoted(value: str) -> str:
    """Return a safe YAML double-quoted scalar for arbitrary text."""
    if not isinstance(value, str):
        raise NamingError(f"YAML scalar source must be a string, got {type(value).__name__}")
    out: list[str] = []
    for ch in value:
        mapped = _SIMPLE_ESCAPES.get(ch)
        if mapped is not None:
            out.append(mapped)
            continue
        code = ord(ch)
        if code < 0x20 or code == 0x7F or 0xD800 <= code <= 0xDFFF:
            out.append(f"\\u{code:04X}")
            continue
        out.append(ch)
    return '"' + "".join(out) + '"'


def sdk_assembly_name(prefix: str, plugin_id: str) -> str:
    """Assembly name accepted by LogiPluginTool: it must end with ``Plugin``.

    The SDK plugin name is the class name without that suffix
    (``StudioDemoPlugin.dll`` -> plugin ``StudioDemo``).
    """
    name = identifier(prefix, plugin_id)
    return name if name.endswith("Plugin") else name + "Plugin"
