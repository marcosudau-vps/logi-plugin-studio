"""Immutable documentation and display values for context help."""

import re
from dataclasses import dataclass

_TOPIC_ID = re.compile(r"[a-z0-9_]+(?:\.[a-z0-9_]+)*")


def _validate_topic_id(topic_id: str) -> None:
    if not isinstance(topic_id, str):
        raise TypeError("topic_id must be a string")
    if not _TOPIC_ID.fullmatch(topic_id):
        raise ValueError(f"Invalid help topic ID: {topic_id!r}")


@dataclass(frozen=True)
class HelpEntry:
    topic_id: str
    title: str
    summary: str
    description: str = ""
    example: str = ""
    technical_details: str = ""
    related_topics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        _validate_topic_id(self.topic_id)
        for field in ("title", "summary", "description", "example", "technical_details"):
            value = getattr(self, field)
            if not isinstance(value, str):
                raise TypeError(f"{field} must be a string")
            if field in ("title", "summary") and not value.strip():
                raise ValueError(f"{field} must not be blank")
        if not isinstance(self.related_topics, tuple):
            raise TypeError("related_topics must be a tuple")
        for topic in self.related_topics:
            _validate_topic_id(topic)


@dataclass(frozen=True)
class HelpContext:
    topic_id: str
    facts: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _validate_topic_id(self.topic_id)
        if not isinstance(self.facts, tuple):
            raise TypeError("facts must be a tuple of (label, value) tuples")
        for pair in self.facts:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise TypeError("each fact must be a (label, value) tuple")
            if not all(isinstance(text, str) for text in pair):
                raise TypeError("fact labels and values must be strings")


@dataclass(frozen=True)
class HelpDisplayState:
    requested_topic_id: str | None = None
    resolved_topic_id: str | None = None
    entry: HelpEntry | None = None
    facts: tuple[tuple[str, str], ...] = ()
    pinned: bool = False
    related_topics: tuple[tuple[str, str], ...] = ()

    @property
    def is_fallback(self) -> bool:
        return self.resolved_topic_id is not None and self.resolved_topic_id != self.requested_topic_id
