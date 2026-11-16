"""Source-owned help topics and an explicit, bounded JSON reader."""

import json
from collections.abc import Sequence
from dataclasses import fields
from pathlib import Path
from threading import Lock

from .entries import HelpEntry, _validate_topic_id

MAX_HELP_JSON_BYTES = 1024 * 1024
_MAX_JSON_TEXT_LENGTH = 16_384
_MAX_JSON_TITLE_LENGTH = 160
_MAX_JSON_TOPIC_LENGTH = 160
_MAX_JSON_RELATED_TOPICS = 32
_ENTRY_FIELDS = {field.name for field in fields(HelpEntry)}
_REQUIRED_FIELDS = {"topic_id", "title", "summary"}


class HelpRegistry:
    """Store globally unique IDs with one owner per registered topic."""

    def __init__(self) -> None:
        self._topics: dict[str, tuple[str, HelpEntry]] = {}
        self._lock = Lock()

    def register(self, entry: HelpEntry, *, source: str) -> None:
        self.register_many((entry,), source=source)

    def register_many(self, entries: Sequence[HelpEntry], *, source: str) -> None:
        _validate_source(source)
        pending: dict[str, tuple[str, HelpEntry]] = {}
        for entry in entries:
            if not isinstance(entry, HelpEntry):
                raise TypeError("Expected a HelpEntry")
            HelpEntry._validate(entry)
            if entry.topic_id in pending:
                raise ValueError(f"Duplicate help topic: {entry.topic_id}")
            pending[entry.topic_id] = (source, entry)
        with self._lock:
            conflicts = self._topics.keys() & pending.keys()
            if conflicts:
                raise ValueError(f"Help topics already registered: {', '.join(sorted(conflicts))}")
            self._topics.update(pending)

    def unregister_source(self, source: str) -> None:
        _validate_source(source)
        with self._lock:
            self._topics = {
                topic: record for topic, record in self._topics.items() if record[0] != source
            }

    def get(self, topic_id: str) -> HelpEntry | None:
        _validate_topic_id(topic_id)
        with self._lock:
            record = self._topics.get(topic_id)
        return record[1] if record else None

    def resolve(self, topic_id: str) -> tuple[str, HelpEntry] | None:
        _validate_topic_id(topic_id)
        with self._lock:
            while topic_id:
                record = self._topics.get(topic_id)
                if record is not None:
                    return topic_id, record[1]
                topic_id = topic_id.rpartition(".")[0]
        return None

    def topics(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._topics))


def _validate_source(source: str) -> None:
    if not isinstance(source, str):
        raise TypeError("source must be a string")
    if not source or source.strip() != source:
        raise ValueError("source must be nonempty and have no surrounding whitespace")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key!r}")
        result[key] = value
    return result


def _bounded_text(value: object, limit: int) -> bool:
    if not isinstance(value, str) or len(value) > limit:
        return False
    try:
        value.encode("utf-8")  # Also reject unpaired surrogates introduced by JSON escapes.
    except UnicodeEncodeError:
        return False
    return True


def load_help_entries(path: Path) -> tuple[HelpEntry, ...]:
    """Read one explicit UTF-8 JSON array. Invalid content raises ValueError."""
    with path.open("rb") as stream:
        data = stream.read(MAX_HELP_JSON_BYTES + 1)
    if len(data) > MAX_HELP_JSON_BYTES:
        raise ValueError(f"Help JSON exceeds {MAX_HELP_JSON_BYTES} bytes")
    try:
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)
    except RecursionError as exc:
        raise ValueError("Help JSON is nested too deeply") from exc
    if not isinstance(payload, list):
        raise ValueError("Help JSON must contain an array of topics")

    entries = []
    seen = set()
    for index, item in enumerate(payload):
        try:
            if not isinstance(item, dict) or not _REQUIRED_FIELDS <= item.keys() <= _ENTRY_FIELDS:
                raise ValueError("expected a topic object with topic_id, title and summary")
            for field, value in item.items():
                if field == "related_topics":
                    if (not isinstance(value, list) or len(value) > _MAX_JSON_RELATED_TOPICS
                            or not all(_bounded_text(topic, _MAX_JSON_TOPIC_LENGTH) for topic in value)):
                        raise ValueError("invalid related_topics array")
                else:
                    limit = {"topic_id": _MAX_JSON_TOPIC_LENGTH, "title": _MAX_JSON_TITLE_LENGTH}.get(
                        field, _MAX_JSON_TEXT_LENGTH
                    )
                    if not _bounded_text(value, limit):
                        raise ValueError(f"{field} must be Unicode text of at most {limit} characters")
            entry = HelpEntry(**{**item, "related_topics": tuple(item.get("related_topics", ()))})
            if entry.topic_id in seen:
                raise ValueError(f"duplicate help topic: {entry.topic_id}")
        except ValueError as exc:
            raise ValueError(f"Help JSON topic {index + 1}: {exc}") from exc
        seen.add(entry.topic_id)
        entries.append(entry)
    return tuple(entries)
