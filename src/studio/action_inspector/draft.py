"""Qt-free, defensive action draft. The native parser remains authoritative."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import re

from adapters.logitech.native import parse_native_project


class DraftError(ValueError):
    pass


@dataclass(frozen=True)
class DraftDiagnostic:
    path: str
    message: str


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


class ActionDraft:
    def __init__(self, project, action_id, raw_action, revision, project_token=None):
        parse_native_project(project)
        original = next((a for a in project['actions'] if a['id'] == action_id), None)
        if original is None or canonical(original) != canonical(raw_action):
            raise DraftError('Aktions-ID und Originaldaten müssen zum Projektsnapshot gehören.')
        if not isinstance(revision, str) or not revision:
            raise DraftError('Eine opake Baserevision ist erforderlich.')
        self._project = deepcopy(project)
        self._original = deepcopy(raw_action)
        self._value = deepcopy(raw_action)
        self._action_id, self._revision = action_id, revision
        self.project_token = project_token

    @property
    def action_id(self):
        return self._action_id

    @property
    def base_revision(self):
        return self._revision

    @property
    def handler_ids(self):
        return tuple(h["id"] for h in self._project["handlers"])

    def snapshot(self):
        return deepcopy(self._value)

    @property
    def dirty(self):
        # Invalid numeric drafts must still count as dirty and remain discardable.
        return json.dumps(self._value, sort_keys=True) != json.dumps(self._original, sort_keys=True)

    def set_field(self, key, value):
        if key in ('id', 'sdk_type'):
            raise DraftError('Aktions-ID und SDK-Typ sind unveränderlich.')
        common = {'display_name', 'description', 'group_name', 'handler', 'parameters',
                  'icon', 'icon_template', 'symbol', 'parameter_symbols'}
        special = {'PluginMultistateDynamicCommand': {'states', 'state_change'},
                   'PluginDynamicAdjustment': {'adjustment'},
                   'ActionEditorCommand': {'editor_controls'}}
        if key not in common | special.get(self._original['sdk_type'], set()):
            raise DraftError('Dieses Feld gehört nicht zum SDK-Aktionstyp.')
        self._value[key] = deepcopy(value)

    def remove_field(self, key):
        if key in ('id', 'sdk_type', 'display_name', 'handler'):
            raise DraftError('Ein Pflichtfeld kann nicht entfernt werden.')
        self.set_field(key, None)  # Enforce the same field/type boundary.
        self._value.pop(key, None)

    def set_rows(self, key, rows):
        rows = deepcopy(rows)
        if key == 'states':
            for index, row in enumerate(rows):
                row['index'] = index
        self.set_field(key, rows)

    def symbol_conflicts(self):
        names = {p.get('name') for p in (self._value.get('parameters') or [])}
        return tuple(k for k in self._value.get('parameter_symbols', {}) if k not in names)

    def resolve_symbol(self, old_name, new_name=None):
        """Explicit user decision only: move a reference or remove it."""
        symbols = deepcopy(self._value.get('parameter_symbols', {}))
        if old_name not in symbols:
            raise DraftError('Symbolreferenz nicht vorhanden.')
        if new_name is not None:
            names = {p['name'] for p in self._value.get('parameters', [])}
            if new_name not in names or new_name in symbols:
                raise DraftError('Zielparameter fehlt oder besitzt bereits ein Symbol.')
            symbols[new_name] = symbols[old_name]
        del symbols[old_name]
        self.set_field('parameter_symbols', symbols)

    def _proposed_project(self):
        proposed = deepcopy(self._project)
        index = next(i for i, a in enumerate(proposed['actions']) if a['id'] == self.action_id)
        proposed['actions'][index] = self.snapshot()
        return proposed

    def diagnostics(self):
        try:
            canonical(self._value)  # Reject NaN/Infinity even where parser accepts them.
            parse_native_project(self._proposed_project())
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            text = str(exc)
            match = re.search(r'/actions/\d+(/[^\s]*)?', text)
            path = re.sub(r'^/actions/\d+', '', match.group(0)) if match else (text.split(':',1)[0] if text.startswith('/') else '/')
            explanations = (
                ('must be a non-empty string', 'Dieses Feld benötigt einen nicht leeren Text.'),
                ('unknown handler', 'Bitte einen vorhandenen Handler auswählen.'),
                ('duplicate parameter', 'Parameternamen müssen innerhalb der Aktion eindeutig sein.'),
                ('unknown parameter', 'Die Symbolzuordnung muss einen vorhandenen Parameternamen verwenden.'),
                ('portable project-relative path', 'Bitte einen relativen Projektpfad ohne Laufwerk oder übergeordnete Verzeichnisse verwenden.'),
                ('must use one of', 'Die Dateiendung passt nicht zur Referenz.'),
                ('at least two', 'Mindestens zwei feste Zustände sind erforderlich.'),
                ('exactly two', 'Toggle benötigt genau zwei Zustände.'),
                ('contiguous', 'Zustandsindizes müssen lückenlos der Reihenfolge entsprechen.'),
                ('duplicate state', 'Zustandsnamen müssen eindeutig sein.'),
                ('finite number', 'Bitte eine endliche Zahl eingeben.'),
                ('Out of range float', 'NaN und unendliche Zahlen sind nicht zulässig.'),
                ('minimum exceeds', 'Das Minimum darf das Maximum nicht überschreiten.'),
                ('outside bounds', 'Der Standardwert muss innerhalb der Grenzen liegen.'),
                ('inconsistent', 'Minimum, Maximum, positive Schrittweite und Standardwert müssen zusammenpassen.'),
                ('must be boolean', 'Hier ist ausschließlich ein boolescher Wert zulässig.'),
                ('not applicable', 'Diese Option gehört nicht zum gewählten Control-Typ.'),
                ('not supported', 'Diese Option wird vom installierten SDK-Control nicht unterstützt.'),
            )
            explanation = next((de for en, de in explanations if en in text),
                               'Wert und Optionen anhand der Feldhilfe korrigieren.')
            return (DraftDiagnostic(path or '/', 'Bitte Eingabe prüfen: ' + explanation + '\nNative Prüfung: ' + text),)
        return ()

    def proposed_action(self):
        errors = self.diagnostics()
        if errors:
            raise DraftError(errors[0].message)
        return self.snapshot()

    def discard(self):
        self._value = deepcopy(self._original)
