"""Identity rule (P0-ADR-001): ``^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$``."""
from __future__ import annotations

import re

ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
ID_RE = re.compile(ID_PATTERN)


def is_valid_id(value: object) -> bool:
    return isinstance(value, str) and ID_RE.fullmatch(value) is not None
