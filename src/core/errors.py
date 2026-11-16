"""Structured diagnostics: ``{code, path, message[, severity]}`` (P0-ADR-007)."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Diagnostic:
    code: str
    path: str
    message: str
    severity: str = "ERROR"

    def as_dict(self) -> dict[str, str]:
        return asdict(self)

    def sort_key(self) -> tuple[str, str, str, str]:
        return (self.path, self.code, self.message, self.severity)
