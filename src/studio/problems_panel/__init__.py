"""Reusable view of structured ``core.errors.Diagnostic`` values; navigation stays with the host."""
from __future__ import annotations

from studio.problems_panel.widget import (DEFAULT_SOURCE, SEVERITY_ALL, SEVERITY_ERROR, SEVERITY_OTHER, SEVERITY_WARNING,
                                          ProblemsPanelWidget)

__all__ = ["DEFAULT_SOURCE", "ProblemsPanelWidget", "SEVERITY_ALL", "SEVERITY_ERROR", "SEVERITY_OTHER", "SEVERITY_WARNING"]
