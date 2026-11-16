"""Path-based navigation: page selection is not a folder transition."""
from dataclasses import dataclass

from .model import Document, FolderError, Reference


@dataclass(frozen=True)
class Step:
    placement_id: str
    origin_id: str
    origin_page_id: str
    target_id: str


class Navigation:
    def __init__(self, document: Document, start_id=None):
        self.document = document
        self.stack: list[Step] = []
        self.select(start_id or document.root_id)

    def select(self, folder_id):
        """Explicit authoring-tree jump resets the simulated user path."""
        self.page_id = self.document.folder(folder_id).pages[0].id
        self.folder_id = folder_id
        self.stack.clear()

    def open(self, placement_id):
        p = self.document.placement(placement_id)
        if p.folder_id != self.folder_id or p.page_id != self.page_id or p.kind == 'action':
            raise FolderError('Nur Ordner/Links der aktuellen Seite öffnen.')
        if p.target.plugin_id != self.document.plugin_id:
            raise FolderError('Externer Ordner nicht verfügbar; Referenz bleibt erhalten.')
        f = self.document.folder(p.target.resource_id)
        self.stack.append(Step(p.id, self.folder_id, self.page_id, f.id))
        self.folder_id, self.page_id = f.id, f.pages[0].id

    def back(self):
        if not self.stack:
            return False
        step = self.stack.pop()
        self.folder_id, self.page_id = step.origin_id, step.origin_page_id
        return True

    def page(self, page_id):
        self.document.page_index(self.folder_id, page_id)
        self.page_id = page_id

    def next_page(self, delta=1):
        f = self.document.folder(self.folder_id)
        index = self.document.page_index(f.id, self.page_id) + delta
        if not 0 <= index < len(f.pages):
            return False
        self.page_id = f.pages[index].id
        return True

    def previous_page(self):
        return self.next_page(-1)

    def update(self, document):
        """Keep valid path steps across edits; never guess a new true-parent path."""
        document.validate()
        self.document = document
        ids = {f.id for f in document.folders}
        valid = self.folder_id in ids
        for step in self.stack:
            try:
                p = document.placement(step.placement_id)
                document.page_index(step.origin_id, step.origin_page_id)
                valid = (valid and p.kind in ('contains', 'link') and p.folder_id == step.origin_id
                         and p.page_id == step.origin_page_id and step.target_id in ids
                         and p.target == Reference(document.plugin_id, step.target_id))
            except FolderError:
                valid = False
        if not valid:
            self.select(self.folder_id if self.folder_id in ids else document.root_id)
        if self.page_id not in {p.id for p in document.folder(self.folder_id).pages}:
            self.page_id = document.folder(self.folder_id).pages[0].id
