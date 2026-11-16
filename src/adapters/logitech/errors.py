"""Structured errors of the Logitech adapter.

All failures carry a stable machine-readable ``code`` so that tests, the CLI
and later tooling can react without parsing prose.  No error path ever writes
to the file system or touches the Logi Plugin Service.
"""
from __future__ import annotations

from typing import Any, Iterable


class LogitechAdapterError(Exception):
    """Base class; ``code`` is stable and part of the adapter contract."""

    code = "ADAPTER_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


class NamingError(LogitechAdapterError):
    """A caller-supplied name cannot be turned into a safe C# artefact."""

    code = "NAMING_INVALID"


class ValidationGateError(LogitechAdapterError):
    """The core validator rejected the project; generation stops before any write."""

    code = "PROJECT_INVALID"

    def __init__(self, issues: Iterable[Any]) -> None:
        self.issues = [issue.as_dict() if hasattr(issue, "as_dict") else dict(issue) for issue in issues]
        summary = ", ".join(sorted({str(issue.get("code", "?")) for issue in self.issues}))
        super().__init__(f"Core validation failed with {len(self.issues)} error(s): {summary}")

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "issues": self.issues}


class SelectionError(LogitechAdapterError):
    """The project is valid but contains nothing this capability can generate."""

    code = "CAPABILITY_UNSUPPORTED"


class GenerationError(LogitechAdapterError):
    """Generation inputs (e.g. the SDK reference) are unusable."""

    code = "GENERATION_INVALID"


class OutputPathError(LogitechAdapterError):
    """The requested output location is unsafe or not writable by this adapter."""

    code = "OUTPUT_PATH_REJECTED"


class BuildError(LogitechAdapterError):
    """``dotnet build`` was refused or failed."""

    code = "BUILD_FAILED"

    def __init__(self, message: str, result: Any = None) -> None:
        super().__init__(message)
        self.result = result
