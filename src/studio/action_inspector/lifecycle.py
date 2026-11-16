"""Qt-freie Action-Lebenszyklen: defensive Vorschläge, keine Session/Dateiwrites.

Der Host korreliert Projekttoken und Revision und committet genau einmal.
CreateDraft bleibt außerhalb der Session; die Validierungsprojektion hängt nur
zur Parserprüfung eine Kopie an. Löschen schützt alle FolderEntry-Referenzen.
"""
from copy import deepcopy
from dataclasses import dataclass
import re

from adapters.logitech.native import ACTION_TYPES, parse_native_project
from core.ids import is_valid_id
from .draft import ActionDraft, DraftError, canonical


def suggest_id(project, name='neu'):
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-') or 'neu'
    base = 'action.' + slug
    used = {a['id'] for a in project['actions']}
    result, suffix = base, 2
    while result in used:
        result = f'{base}-{suffix}'
        suffix += 1
    return result


def starter_action(sdk_type, action_id, display_name, handler):
    if sdk_type not in ACTION_TYPES:
        raise DraftError('/sdk_type: Bitte eine der vier unterstützten SDK-Klassen wählen.')
    action = dict(id=action_id, sdk_type=sdk_type, display_name=display_name, handler=handler)
    if sdk_type == 'PluginMultistateDynamicCommand':
        action.update(state_change='toggle', states=[
            dict(index=i, name=name, display_name=label, description='')
            for i, name, label in ((0, 'off', 'Aus'), (1, 'on', 'An'))])
    elif sdk_type == 'PluginDynamicAdjustment':
        action['adjustment'] = {}
    elif sdk_type == 'ActionEditorCommand':
        action['editor_controls'] = [dict(type='textbox', name='text', label='Text')]
    return action


def propose_create(project, action):
    proposed = deepcopy(project)
    parse_native_project(proposed)
    if not isinstance(action, dict):
        raise DraftError('/: Eine Action als Objekt ist erforderlich.')
    if not is_valid_id(action.get('id')):
        raise DraftError('/id: Ungültige Action-ID. Beispiel: action.mein-befehl (klein, ohne Leerzeichen).')
    if any(a['id'] == action['id'] for a in proposed['actions']):
        raise DraftError('/id: Diese Action-ID existiert bereits; bitte eine eindeutige ID eingeben.')
    if not isinstance(action.get('display_name'), str) or not action['display_name'].strip():
        raise DraftError('/display_name: Bitte einen nicht leeren Anzeigenamen eingeben.')
    canonical(action)
    proposed['actions'].append(deepcopy(action))
    parse_native_project(proposed)
    return proposed


@dataclass(frozen=True)
class DeleteCheck:
    action_id: str
    display_name: str
    references: tuple[tuple[str, str], ...]
    reason: str

    @property
    def allowed(self):
        return not self.reason


def check_delete(project, action_id):
    parse_native_project(project)
    action = next((a for a in project['actions'] if a['id'] == action_id), None)
    if action is None:
        raise DraftError('Native Action-ID nicht mehr vorhanden; nichts geändert.')
    refs = tuple((f['id'], e['id']) for f in project['folders'] for e in f['entries']
                 if e['action'] == action_id)
    reason = (f'{len(refs)} Folder-Referenz(en) verhindern das Löschen: ' +
              ', '.join(f'{f} / {e}' for f, e in refs)) if refs else ''
    if len(project['actions']) == 1:
        reason = 'Die letzte Action darf nicht gelöscht werden; das Projekt benötigt mindestens eine Action.' + (
            '\n' + reason if reason else '')
    return DeleteCheck(action_id, action['display_name'], refs, reason)


def propose_delete(project, action_id):
    proposed = deepcopy(project)
    check = check_delete(proposed, action_id)
    if not check.allowed:
        raise DraftError(check.reason)
    proposed['actions'] = [a for a in proposed['actions'] if a['id'] != action_id]
    parse_native_project(proposed)
    canonical(proposed)
    return proposed


class CreateDraft(ActionDraft):
    """Ein aktiver Create-Entwurf ist separat dirty, auch mit gültigem Starter."""
    def __init__(self, project, revision, project_token, sdk_type='PluginDynamicCommand'):
        parse_native_project(project)
        if not isinstance(revision, str) or not revision or not project_token:
            raise DraftError('Projekttoken und opake Baserevision sind erforderlich.')
        self._project = deepcopy(project)
        self._revision, self.project_token = revision, project_token
        self._original = starter_action(sdk_type, suggest_id(project), 'Neue Aktion', project['handlers'][0]['id'])
        self._value = deepcopy(self._original)

    @property
    def action_id(self):
        return self._value['id']

    @property
    def dirty(self):
        return True

    def set_field(self, key, value):
        if key == 'id':
            self._value[key] = deepcopy(value)
        else:
            super().set_field(key, value)

    def change_type(self, sdk_type):
        common = {k: deepcopy(v) for k, v in self._value.items()
                  if k not in ('sdk_type', 'states', 'state_change', 'adjustment', 'editor_controls')}
        self._value = starter_action(sdk_type, self.action_id, self._value['display_name'], self._value['handler'])
        self._value.update(common)
        self._original = starter_action(sdk_type, common['id'], common['display_name'], common['handler'])

    def _proposed_project(self):
        return propose_create(self._project, self._value)
