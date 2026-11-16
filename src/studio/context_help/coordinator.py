"""Host-owned selection and pin policy for the help panel."""

from dataclasses import replace

from PySide6.QtCore import QObject, Signal

from .entries import HelpContext, HelpDisplayState
from .registry import HelpRegistry


class HelpCoordinator(QObject):
    helpChanged = Signal(object)

    def __init__(self, registry: HelpRegistry, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._registry = registry
        self._context: HelpContext | None = None
        self._state = HelpDisplayState()

    def set_context(self, context: HelpContext | None) -> None:
        if context is not None and not isinstance(context, HelpContext):
            raise TypeError("Expected a HelpContext or None")
        if not self._state.pinned:
            self._context = context
            self.refresh()

    def request_help(self, context: HelpContext) -> None:
        if not isinstance(context, HelpContext):
            raise TypeError("Expected a HelpContext")
        self._context = context
        self.refresh()

    def set_pinned(self, pinned: bool) -> None:
        if not isinstance(pinned, bool):
            raise TypeError("pinned must be a bool")
        self._publish(replace(self._state, pinned=pinned))

    def current(self) -> HelpDisplayState:
        return self._state

    def refresh(self) -> None:
        context = self._context
        state = HelpDisplayState(
            requested_topic_id=context.topic_id if context is not None else None,
            pinned=self._state.pinned,
        )
        resolved = self._registry.resolve(context.topic_id) if context is not None else None
        if resolved is not None:
            topic_id, entry = resolved
            related = []
            for related_id in dict.fromkeys(entry.related_topics):
                target = self._registry.get(related_id)
                if target is not None and target.topic_id != topic_id:
                    related.append((target.topic_id, target.title))
            state = replace(state, resolved_topic_id=topic_id, entry=entry, facts=context.facts,
                            related_topics=tuple(related))
        self._publish(state)

    def _publish(self, state: HelpDisplayState) -> None:
        if state != self._state:
            self._state = state
            self.helpChanged.emit(state)
