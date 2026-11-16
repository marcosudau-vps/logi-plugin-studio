"""Immutable folder graph. Actions are references, never definition copies.

Containment has exactly one placement for every non-root node. Links are not
traversed by structural operations. Every mutation returns a validated snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4

from core.ids import is_valid_id

VERSION = 'virtual-folders-1'


class FolderError(ValueError):
    """Invalid extension, reference or authoring operation; old snapshot survives."""


def new_id(kind):
    return f'{kind}.{uuid4().hex}'


def identifier(value):
    if not is_valid_id(value):
        raise FolderError(f'Ungültige stabile ID: {value!r}')
    return value


def title(value):
    if not isinstance(value, str) or not value.strip():
        raise FolderError('Name darf nicht leer sein.')
    try:
        value.encode('utf-8')
    except UnicodeError as exc:
        raise FolderError('Text enthält ungültiges Unicode.') from exc
    return value


def index_at(value, length, *, append=False):
    if type(value) is not int or not 0 <= value < length + int(append):
        raise FolderError(f'Ungültige Position: {value!r}')
    return value


@dataclass(frozen=True)
class Reference:
    plugin_id: str
    resource_id: str

    def __post_init__(self):
        identifier(self.plugin_id)
        identifier(self.resource_id)

    @property
    def key(self):
        return f'{self.plugin_id}::{self.resource_id}'

    @classmethod
    def parse(cls, key):
        if not isinstance(key, str) or key.count('::') != 1:
            raise FolderError('Referenz erwartet plugin.id::resource.id')
        return cls(*key.split('::'))


@dataclass(frozen=True)
class PagingCapability:
    slots: int
    source: str

    def __post_init__(self):
        if type(self.slots) is not int or self.slots <= 0:
            raise FolderError('Auto-Paging benötigt eine positive explizite Slot-Capability.')
        title(self.source)


@dataclass(frozen=True)
class Page:
    id: str
    name: str


@dataclass(frozen=True)
class Folder:
    id: str
    owner: str
    name: str
    parent_id: str | None
    pages: tuple[Page, ...]
    mode: str = 'single'
    capability: PagingCapability | None = None


@dataclass(frozen=True)
class Placement:
    id: str
    folder_id: str
    page_id: str
    kind: str  # contains, link, action
    target: Reference
    position: int
    action_parameter: str | None = None


@dataclass(frozen=True)
class Document:
    project_id: str
    plugin_id: str
    root_id: str
    folders: tuple[Folder, ...]
    placements: tuple[Placement, ...] = ()
    version: str = VERSION

    @classmethod
    def create(cls, project_id, plugin_id, name='Plugin-Root'):
        root = Folder(new_id('folder'), plugin_id, name, None,
                      (Page(new_id('page'), 'Seite 1'),))
        return cls(project_id, plugin_id, root.id, (root,)).validate()

    def folder(self, identity):
        for folder in self.folders:
            if folder.id == identity:
                return folder
        raise FolderError(f'Ordnerziel fehlt: {identity}')

    def placement(self, identity):
        for placement in self.placements:
            if placement.id == identity:
                return placement
        raise FolderError(f'Platzierung fehlt: {identity}')

    def entries(self, folder_id, page_id=None):
        self.folder(folder_id)
        return tuple(sorted((p for p in self.placements if p.folder_id == folder_id
                             and (page_id is None or p.page_id == page_id)),
                            key=lambda p: (self.page_index(folder_id, p.page_id), p.position)))

    def page_index(self, folder_id, page_id):
        for i, page in enumerate(self.folder(folder_id).pages):
            if page.id == page_id:
                return i
        raise FolderError(f'Seite fehlt im Ordner: {page_id}')

    def validate(self):
        if self.version != VERSION:
            raise FolderError('Unbekannte Extension-Version.')
        identifier(self.project_id)
        identifier(self.plugin_id)
        identifier(self.root_id)
        if type(self.folders) is not tuple or type(self.placements) is not tuple:
            raise FolderError('Snapshots benötigen unveränderliche Tupel.')
        seen = set()

        def unique(identity):
            identifier(identity)
            if identity in seen:
                raise FolderError(f'Doppelte ID: {identity}')
            seen.add(identity)

        for f in self.folders:
            if not isinstance(f, Folder):
                raise FolderError('Ungültiges Ordnerobjekt.')
            unique(f.id)
            if f.owner != self.plugin_id:
                raise FolderError('Fremde Ordner gehören in Providerreferenzen, nicht in diesen Owner.')
            title(f.name)
            if f.parent_id is not None:
                identifier(f.parent_id)
            if f.mode not in ('single', 'auto', 'manual') or not f.pages or type(f.pages) is not tuple:
                raise FolderError('Seitenmodus oder Seitenliste ungültig.')
            if f.mode == 'auto':
                if not isinstance(f.capability, PagingCapability):
                    raise FolderError('Auto-Paging ohne explizite Capability ist gesperrt.')
                f.capability.__post_init__()
            elif f.capability is not None:
                raise FolderError('Slot-Capability ist nur für Auto-Paging bestimmt.')
            if f.mode == 'single' and len(f.pages) != 1:
                raise FolderError('Single Page benötigt genau eine Seite.')
            for page in f.pages:
                if not isinstance(page, Page):
                    raise FolderError('Ungültiges Seitenobjekt.')
                unique(page.id)
                title(page.name)
        if self.folder(self.root_id).parent_id is not None:
            raise FolderError('Plugin-Root muss ein echter Root sein.')
        incoming = {}
        positions = {}
        for p in self.placements:
            if not isinstance(p, Placement):
                raise FolderError('Ungültiges Platzierungsobjekt.')
            unique(p.id)
            f = self.folder(p.folder_id)
            self.page_index(f.id, p.page_id)
            if p.kind not in ('contains', 'link', 'action'):
                raise FolderError('Unbekannter Platzierungstyp.')
            if not isinstance(p.target, Reference):
                raise FolderError('Ungültige Referenz.')
            p.target.__post_init__()
            if type(p.position) is not int or p.position < 0:
                raise FolderError('Position muss eine nichtnegative Ganzzahl sein.')
            if p.action_parameter is not None and (p.kind != 'action' or not isinstance(p.action_parameter, str)):
                raise FolderError('actionParameter ist nur bei Actions als Text zulässig.')
            if p.kind in ('contains', 'link') and p.target.plugin_id == self.plugin_id:
                self.folder(p.target.resource_id)
            if p.kind == 'contains':
                if p.target.plugin_id != self.plugin_id:
                    raise FolderError('Containment darf keinen fremden Owner verändern.')
                child = self.folder(p.target.resource_id)
                if child.parent_id != p.folder_id or child.id in incoming:
                    raise FolderError('Containment und echter Parent widersprechen sich.')
                incoming[child.id] = p.id
            positions.setdefault((f.id, p.page_id), []).append(p.position)
        for f in self.folders:
            if (f.parent_id is not None) != (f.id in incoming):
                raise FolderError('Parent benötigt genau eine Contains-Platzierung.')
            ancestors = {f.id}
            parent = f.parent_id
            while parent is not None:
                if parent in ancestors:
                    raise FolderError('Containment-Zyklus ist verboten.')
                ancestors.add(parent)
                parent = self.folder(parent).parent_id
            for page in f.pages:
                values = positions.get((f.id, page.id), [])
                if sorted(values) != list(range(len(values))):
                    raise FolderError('Seitenpositionen müssen lückenlos und eindeutig sein.')
            if f.mode == 'auto':
                counts = [len(positions.get((f.id, page.id), [])) for page in f.pages]
                needed = max(1, (sum(counts) + f.capability.slots - 1) // f.capability.slots)
                if len(counts) != needed or any(c != f.capability.slots for c in counts[:-1]) or counts[-1] > f.capability.slots:
                    raise FolderError('Auto-Seiten stimmen nicht mit der Capability überein.')
        return self

    def _finish(self, *, folders=None, placements=None, root_id=None):
        """Normalize positions and auto pages only after a deliberate mutation."""
        fs = list(self.folders if folders is None else folders)
        ps = list(self.placements if placements is None else placements)
        for i, f in enumerate(fs):
            ordered = sorted((p for p in ps if p.folder_id == f.id),
                             key=lambda p: (next(j for j, page in enumerate(f.pages) if page.id == p.page_id), p.position))
            if f.mode == 'auto':
                count = max(1, (len(ordered) + f.capability.slots - 1) // f.capability.slots)
                pages = list(f.pages[:count])
                while len(pages) < count:
                    pages.append(Page(new_id('page'), f'Seite {len(pages)+1}'))
                f = replace(f, pages=tuple(pages))
                fs[i] = f
                revised = [replace(p, page_id=pages[j // f.capability.slots].id,
                                   position=j % f.capability.slots) for j, p in enumerate(ordered)]
            else:
                revised = []
                for page in f.pages:
                    revised.extend(replace(p, position=j) for j, p in enumerate(ordered_p for ordered_p in ordered if ordered_p.page_id == page.id))
            ps = [p for p in ps if p.folder_id != f.id] + revised
        return replace(self, folders=tuple(fs), placements=tuple(ps),
                       root_id=self.root_id if root_id is None else root_id).validate()

    def validate_native(self, snapshot, *, require_available=True):
        """Validate local action targets against the actual native authority.

        Call at the attachment/import boundary. Later owner deletion is shown as
        unavailable until explicitly repaired; a provider refresh never deletes
        authoring data. Remote targets may always remain offline references.
        """
        from adapters.logitech.native import parse_native_project
        native = parse_native_project(snapshot)
        if native.plugin_id != self.plugin_id:
            raise FolderError('Native Plugin-ID und Extension stimmen nicht überein.')
        known = {a.id for a in native.actions}
        missing = [p.target.key for p in self.placements if p.kind == 'action'
                   and p.target.plugin_id == self.plugin_id and p.target.resource_id not in known]
        if missing and require_available:
            raise FolderError('Lokale SDK-Actionziele fehlen: ' + ', '.join(sorted(set(missing))))
        return self.validate()

    def missing_actions(self, snapshot):
        """Availability is external state, never a reason to drop placements."""
        self.validate_native(snapshot, require_available=False)
        known = {a['id'] for a in snapshot['actions']}
        return tuple(p for p in self.placements if p.kind == 'action'
                     and p.target.plugin_id == self.plugin_id and p.target.resource_id not in known)

    def _edit_folder(self, folder):
        return self._finish(folders=[folder if f.id == folder.id else f for f in self.folders])

    def set_root(self, folder_id):
        return replace(self, root_id=self.folder(folder_id).id).validate()

    def rename_folder(self, folder_id, name):
        return self._edit_folder(replace(self.folder(folder_id), name=title(name)))

    def _destination(self, folder_id, page_id):
        f = self.folder(folder_id)
        page_id = f.pages[-1].id if page_id is None else page_id
        self.page_index(folder_id, page_id)
        return page_id

    def create_folder(self, name, parent_id=None, page_id=None):
        f = Folder(new_id('folder'), self.plugin_id, title(name), parent_id,
                   (Page(new_id('page'), 'Seite 1'),))
        ps = list(self.placements)
        if parent_id is not None:
            page_id = self._destination(parent_id, page_id)
            ps.append(Placement(new_id('placement'), parent_id, page_id, 'contains',
                                Reference(self.plugin_id, f.id), len(self.entries(parent_id, page_id))))
        return self._finish(folders=(*self.folders, f), placements=ps), f.id

    def add_link(self, folder_id, target, page_id=None):
        return self._add(folder_id, 'link', target, page_id)

    def add_action(self, folder_id, target, page_id=None, action_parameter=None):
        return self._add(folder_id, 'action', target, page_id, action_parameter)

    def _add(self, folder_id, kind, target, page_id, parameter=None):
        page_id = self._destination(folder_id, page_id)
        p = Placement(new_id('placement'), folder_id, page_id, kind, target,
                      len(self.entries(folder_id, page_id)), parameter)
        return self._finish(placements=(*self.placements, p)), p.id

    def remove_placement(self, placement_id):
        p = self.placement(placement_id)
        if p.kind == 'contains':
            raise FolderError('Echten Ordner verschieben oder explizit löschen; kein implizites Abtrennen.')
        return self._finish(placements=[p for p in self.placements if p.id != placement_id])

    def move_placement(self, placement_id, folder_id, page_id, position):
        p = self.placement(placement_id)
        if p.kind == 'contains':
            return self.move_folder(p.target.resource_id, folder_id, page_id, position)
        return self._relocate(p, folder_id, page_id, position)

    def _relocate(self, p, folder_id, page_id, position, folders=None):
        page_id = self._destination(folder_id, page_id)
        siblings = [x for x in self.entries(folder_id, page_id) if x.id != p.id]
        index_at(position, len(siblings), append=True)
        siblings.insert(position, replace(p, folder_id=folder_id, page_id=page_id))
        ids = {x.id for x in siblings} | {p.id}
        ps = [x for x in self.placements if x.id not in ids]
        ps.extend(replace(x, position=i) for i, x in enumerate(siblings))
        return self._finish(folders=folders, placements=ps)

    def reorder_placement(self, placement_id, position):
        p = self.placement(placement_id)
        index_at(position, len(self.entries(p.folder_id, p.page_id)))
        return self.move_placement(p.id, p.folder_id, p.page_id, position)

    def move_folder(self, folder_id, parent_id, page_id=None, position=None):
        f = self.folder(folder_id)
        if f.id == self.root_id and parent_id is not None:
            raise FolderError('Plugin-Root zuerst explizit wechseln.')
        fs = [replace(x, parent_id=parent_id) if x.id == f.id else x for x in self.folders]
        incoming = next((p for p in self.placements if p.kind == 'contains' and p.target.resource_id == f.id), None)
        if parent_id is None:
            return self._finish(folders=fs, placements=[p for p in self.placements if not incoming or p.id != incoming.id])
        page_id = self._destination(parent_id, page_id)
        if incoming is None:
            incoming = Placement(new_id('placement'), parent_id, page_id, 'contains', Reference(self.plugin_id, f.id), 0)
        count = len([p for p in self.entries(parent_id, page_id) if p.id != incoming.id])
        return self._relocate(incoming, parent_id, page_id, count if position is None else position, fs)

    def copy_folder(self, folder_id, parent_id=None, page_id=None):
        self.folder(folder_id)
        # Iterative traversal of CONTAINS only, never follow links (including cycles).
        subtree, pending = [], [folder_id]
        while pending:
            current = pending.pop()
            subtree.append(current)
            pending.extend(f.id for f in self.folders if f.parent_id == current)
        mapping = {old: new_id('folder') for old in subtree}
        pages = {p.id: new_id('page') for old in subtree for p in self.folder(old).pages}
        fs, ps = list(self.folders), list(self.placements)
        for old in subtree:
            f = self.folder(old)
            fs.append(replace(f, id=mapping[old], parent_id=parent_id if old == folder_id else mapping[f.parent_id],
                              name=f.name + ' (Kopie)' if old == folder_id else f.name,
                              pages=tuple(replace(p, id=pages[p.id]) for p in f.pages)))
        for p in self.placements:
            if p.folder_id in mapping:
                # Links preserve their exact target, even when it is inside the copied tree.
                target = Reference(self.plugin_id, mapping[p.target.resource_id]) if p.kind == 'contains' else p.target
                ps.append(replace(p, id=new_id('placement'), folder_id=mapping[p.folder_id], page_id=pages[p.page_id], target=target))
        if parent_id is not None:
            page_id = self._destination(parent_id, page_id)
            ps.append(Placement(new_id('placement'), parent_id, page_id, 'contains',
                                Reference(self.plugin_id, mapping[folder_id]), len(self.entries(parent_id, page_id))))
        return self._finish(folders=fs, placements=ps), mapping[folder_id]

    def delete_folder(self, folder_id):
        self.folder(folder_id)
        if folder_id == self.root_id:
            raise FolderError('Konfigurierten Plugin-Root nicht löschen; zuerst anderen Root wählen.')
        if any(f.parent_id == folder_id for f in self.folders):
            raise FolderError('Ordner hat echte Kinder; zuerst verschieben oder einzeln löschen.')
        if any(p.kind == 'link' and p.target == Reference(self.plugin_id, folder_id) for p in self.placements):
            raise FolderError('Ordner wird verlinkt; Links zuerst explizit entfernen.')
        return self._finish(folders=[f for f in self.folders if f.id != folder_id],
                            placements=[p for p in self.placements if p.folder_id != folder_id and
                                        not (p.kind == 'contains' and p.target.resource_id == folder_id)])

    def set_mode(self, folder_id, mode, capability=None):
        f = self.folder(folder_id)
        if mode not in ('single', 'auto', 'manual'):
            raise FolderError('Unbekannter Seitenmodus.')
        if mode == 'auto' and not isinstance(capability, PagingCapability):
            raise FolderError('Auto-Paging benötigt eine explizite Capability.')
        if mode == 'single':
            ps = [p for p in self.placements if p.folder_id != f.id]
            ps.extend(replace(p, page_id=f.pages[0].id, position=i) for i, p in enumerate(self.entries(f.id)))
            f = replace(f, mode=mode, pages=f.pages[:1], capability=None)
            return self._finish(folders=[f if x.id == f.id else x for x in self.folders], placements=ps)
        return self._edit_folder(replace(f, mode=mode, capability=capability if mode == 'auto' else None))

    def add_page(self, folder_id, name='Neue Seite'):
        f = self.folder(folder_id)
        if f.mode != 'manual':
            raise FolderError('Seiten nur im Modus Manual hinzufügen.')
        page = Page(new_id('page'), title(name))
        return self._edit_folder(replace(f, pages=(*f.pages, page))), page.id

    def rename_page(self, folder_id, page_id, name):
        f = self.folder(folder_id)
        self.page_index(folder_id, page_id)
        return self._edit_folder(replace(f, pages=tuple(replace(p, name=title(name)) if p.id == page_id else p for p in f.pages)))

    def remove_page(self, folder_id, page_id):
        f = self.folder(folder_id)
        self.page_index(folder_id, page_id)
        if f.mode != 'manual' or len(f.pages) == 1 or self.entries(folder_id, page_id):
            raise FolderError('Nur leere zusätzliche Manual-Seiten löschen; Einträge vorher verschieben.')
        return self._edit_folder(replace(f, pages=tuple(p for p in f.pages if p.id != page_id)))

    def reorder_page(self, folder_id, page_id, position):
        f = self.folder(folder_id)
        if f.mode != 'manual':
            raise FolderError('Seitenreihenfolge nur bei Manual ändern.')
        old = self.page_index(folder_id, page_id)
        index_at(position, len(f.pages))
        pages = list(f.pages)
        pages.insert(position, pages.pop(old))
        return self._edit_folder(replace(f, pages=tuple(pages)))
