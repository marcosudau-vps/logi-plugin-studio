from __future__ import annotations

import copy
import json
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QSpinBox, QTabWidget, QTableWidget,
                               QVBoxLayout, QWidget)

from library.document import DocumentError, ProjectDocument, schema_default
from runtime.wire import HostError, json_bytes


def encoded(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def parsed(text: str) -> Any:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise DocumentError("Doppelter JSON-Schluessel: " + key)
            result[key] = value
        return result
    try:
        value = json.loads(text, object_pairs_hook=unique)
        json_bytes(value)
        return value
    except (ValueError, HostError) as exc:
        raise DocumentError("Ungueltiges JSON: " + str(exc)) from exc


def combo(values: list[str], current: str = "") -> QComboBox:
    widget = QComboBox()
    widget.addItems(values)
    if current not in values:
        widget.addItem(current)
    widget.setCurrentText(current)
    return widget


def json_editor(value: Any, height: int = 100) -> QPlainTextEdit:
    editor = QPlainTextEdit(encoded(value))
    editor.setMinimumHeight(height)
    editor.setMaximumHeight(max(height, 160))
    return editor


class ConfigForm(QWidget):
    changed = Signal()

    def __init__(self, schema: dict, config: dict):
        super().__init__()
        self._original = copy.deepcopy(config)
        self._fields: dict[str, tuple[QWidget, dict]] = {}
        self._dirty_fields: set[str] = set()
        form = QFormLayout(self)
        for name, contract in schema.get("properties", {}).items():
            value = config.get(name, schema_default(contract))
            kind = contract.get("type")
            if "enum" in contract and all(isinstance(v, str) for v in contract["enum"]):
                widget = combo(contract["enum"], str(value))
                widget.currentTextChanged.connect(lambda *_, key=name: self._mark_changed(key))
            elif kind == "boolean":
                widget = QCheckBox()
                widget.setChecked(bool(value))
                widget.toggled.connect(lambda *_, key=name: self._mark_changed(key))
            elif kind in ("integer", "number"):
                widget = QLineEdit(json.dumps(value))
                widget.textChanged.connect(lambda *_, key=name: self._mark_changed(key))
            elif kind == "string":
                widget = QLineEdit(value if isinstance(value, str) else "")
                widget.textChanged.connect(lambda *_, key=name: self._mark_changed(key))
            else:
                widget = json_editor(value)
                widget.textChanged.connect(lambda *_, key=name: self._mark_changed(key))
            widget.setToolTip(encoded(contract))
            self._fields[name] = (widget, contract)
            form.addRow(name + (" *" if name in schema.get("required", []) else ""), widget)

    def _mark_changed(self, name):
        self._dirty_fields.add(name)
        self.changed.emit()

    def value(self) -> dict:
        result = copy.deepcopy(self._original)
        for name, (widget, contract) in self._fields.items():
            if name not in self._original and name not in self._dirty_fields:
                continue
            if isinstance(widget, QLineEdit):
                result[name] = parsed(widget.text()) if contract.get("type") in ("integer", "number") else widget.text()
            elif isinstance(widget, QComboBox):
                result[name] = widget.currentText()
            elif isinstance(widget, QCheckBox):
                result[name] = widget.isChecked()
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                result[name] = widget.value()
            else:
                result[name] = parsed(widget.toPlainText())
        return result


class ObjectEditor(QWidget):
    changed = Signal()

    def __init__(self, document: ProjectDocument, collection: str, entity: dict):
        super().__init__()
        self.document = document
        self.collection = collection
        self.original = copy.deepcopy(entity)
        self.pending = False
        layout = QVBoxLayout(self)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.tabs = QTabWidget()
        self.form_page = QWidget()
        self.form = QFormLayout(self.form_page)
        self.id_field = QLineEdit(str(entity.get("id", "")))
        self.form.addRow("Stabile ID (Rename aktualisiert Referenzen)", self.id_field)
        self.tabs.addTab(self.form_page, "Eigenschaften")
        self.raw_editor = QPlainTextEdit(encoded(entity))
        self.tabs.addTab(self.raw_editor, "Objekt-JSON")
        layout.addWidget(self.tabs)
        self.widgets: dict[str, QWidget] = {}
        self.id_field.textChanged.connect(self._changed)
        self.raw_editor.textChanged.connect(self._changed)
        self.tabs.currentChanged.connect(self._switch_tab)
        if any(d.severity == "ERROR" for d in document.diagnostics()):
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(1)
            self.tabs.setTabEnabled(0, False)
            self.tabs.blockSignals(False)
        else:
            self._create_fields()

    def _changed(self, *_):
        self.pending = True
        self.changed.emit()

    def _switch_tab(self, index):
        if index == 1:
            try:
                raw = self._form_value()
                self.raw_editor.blockSignals(True)
                self.raw_editor.setPlainText(encoded(raw))
                self.raw_editor.blockSignals(False)
            except DocumentError as exc:
                self.error_label.setText("Formfehler: " + str(exc))
                self.error_label.show()
                self.tabs.blockSignals(True)
                self.tabs.setCurrentIndex(0)
                self.tabs.blockSignals(False)
                return
            self.error_label.hide()
        elif self.pending:
            # JSON edits stay in the JSON tab until Apply, avoiding two divergent forms.
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(1)
            self.tabs.blockSignals(False)
            self.error_label.setText("JSON-Entwurf zuerst uebernehmen; kein stiller Wechsel zum alten Formular.")
            self.error_label.show()

    def _add(self, name: str, widget: QWidget, label: str | None = None):
        self.widgets[name] = widget
        self.form.addRow(label or name, widget)
        if isinstance(widget, QLineEdit):
            widget.textChanged.connect(self._changed)
        elif isinstance(widget, QPlainTextEdit):
            widget.textChanged.connect(self._changed)
        elif isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(self._changed)
        elif isinstance(widget, QCheckBox):
            widget.toggled.connect(self._changed)

    def _endpoints(self, direction: str) -> list[tuple[str, dict]]:
        result = []
        for component in self.document.raw.get("components", []):
            if not isinstance(component, dict):
                continue
            manifest = self.document.registry.resolve(component.get("type"), component.get("version"))
            if manifest:
                for port in manifest.ports:
                    if port.direction == direction:
                        result.append((f"{component['id']}/{port.id}  [{direction}, {port.kind}]",
                                       {"owner_kind": "component", "owner_id": component["id"], "port": port.id}))
        if direction == "out":
            result += [(s["id"] + "/value  [out, state]",
                        {"owner_kind": "state", "owner_id": s["id"], "port": "value"})
                       for s in self.document.raw.get("states", []) if isinstance(s, dict) and "id" in s]
        else:
            result += [(p["id"] + "/selector  [in, state]",
                        {"owner_kind": "presentation", "owner_id": p["id"], "port": "selector"})
                       for p in self.document.raw.get("presentations", []) if isinstance(p, dict) and "id" in p]
        return result

    def _endpoint_combo(self, name: str, direction: str):
        widget = QComboBox()
        entries = self._endpoints(direction)
        for label, endpoint in entries:
            widget.addItem(label, endpoint)
        value = self.original.get(name)
        index = next((i for i, (_, endpoint) in enumerate(entries) if endpoint == value), -1)
        if index < 0:
            widget.addItem("UNGUELTIG: " + json.dumps(value), value)
            index = widget.count() - 1
        widget.setCurrentIndex(index)
        self._add(name, widget, "Quelle" if name == "source" else "Ziel")

    def _create_fields(self):
        entity = self.original
        if self.collection == "project":
            self._add("display_name", QLineEdit(str(entity.get("display_name", ""))), "Anzeigename")
            self.form.addRow(QLabel("Projektformat 0.1-draft bleibt unveraendert; Runtime-Werte werden separat gehalten."))
        elif self.collection == "components":
            manifests = self.document.component_types()
            types = QComboBox()
            for item in manifests:
                types.addItem(item.type_id + "@" + item.version, (item.type_id, item.version))
            found = next((i for i in range(types.count()) if types.itemData(i) == (entity.get("type"), entity.get("version"))), -1)
            if found < 0:
                types.addItem(f"{entity.get('type')}@{entity.get('version')}", (entity.get("type"), entity.get("version")))
                found = types.count() - 1
            types.setCurrentIndex(found)
            self._add("type", types, "Komponententyp / Version")
            manifest = self.document.registry.resolve(entity.get("type"), entity.get("version"))
            config = entity.get("config") if isinstance(entity.get("config"), dict) else {}
            self.config_form = ConfigForm(manifest.config_schema if manifest else {}, config)
            self.form.addRow("Konfiguration aus Typmanifest", self.config_form)
            self.config_form.changed.connect(self._changed)
            ports = "\n".join(f"{p.id}: {p.direction}/{p.kind} {json.dumps(p.payload_schema)}"
                              for p in manifest.ports) if manifest else "Typ nicht aufgeloest"
            label = QLabel(ports)
            label.setWordWrap(True)
            self.form.addRow("Portvertraege", label)
            self.form.addRow(QLabel("Typwechsel: Konfiguration im Objekt-JSON an den neuen Typ anpassen."))
        elif self.collection == "states":
            self._add("value_schema", json_editor(entity.get("value_schema", {})), "JSON-Wertvertrag")
            self._add("scope", combo(["project", "component", "placement", "session"], str(entity.get("scope", ""))), "Scope (project = Runtime)")
            self._add("authority", QLineEdit(json.dumps(entity.get("authority", {"role": "host"}))), "Authority (JSON; genau ein Writer)")
            self._add("persistence", combo(["none", "runtime_local", "external"], str(entity.get("persistence", ""))), "Persistenzdeklaration (keine automatische Speicherung)")
            enabled = QCheckBox("Fallback vorhanden; ist kein bestaetigter Ist-Wert")
            enabled.setChecked("fallback" in entity)
            self._add("has_fallback", enabled, "Fallback")
            self._add("fallback", QLineEdit(json.dumps(entity.get("fallback"))), "Fallback JSON")
        elif self.collection == "bindings":
            self._add("kind", combo(["command", "event", "state"], str(entity.get("kind", ""))), "Signalart")
            self._endpoint_combo("source", "out")
            self._endpoint_combo("target", "in")
            self.form.addRow(QLabel("Nur out -> in derselben Signalart. Payload-Kompatibilitaet wird live validiert."))
        elif self.collection == "views":
            self._add("type", combo(["folder", "grid"], str(entity.get("type", ""))), "Logischer View-Typ")
            self.table = QTableWidget(0, 4)
            self.table.setHorizontalHeaderLabels(["Placement-ID", "Komponente", "Presentation", "Position"])
            self.table.setMinimumHeight(230)
            self.table.horizontalHeader().setStretchLastSection(True)
            self.form.addRow("Placements (kein logisches Mengenlimit)", self.table)
            for placement in entity.get("placements", []) if isinstance(entity.get("placements"), list) else []:
                if isinstance(placement, dict):
                    self._placement_row(placement)
            buttons = QHBoxLayout()
            add = QPushButton("Placement hinzufuegen")
            remove = QPushButton("Ausgewaehltes entfernen")
            buttons.addWidget(add)
            buttons.addWidget(remove)
            add.clicked.connect(self._new_placement)
            remove.clicked.connect(self._remove_row)
            self.form.addRow(buttons)
        elif self.collection == "presentations":
            self.table = QTableWidget(0, 7)
            self.table.setHorizontalHeaderLabels(["Variantenschluessel", "Text", "Hintergrund", "Vordergrund", "Asset-ID",
                                                 "Bildmodus", "Schrift px / 116"])
            self.table.setMinimumHeight(230)
            self.form.addRow("Varianten", self.table)
            variants = entity.get("variants", {})
            for key, value in variants.items() if isinstance(variants, dict) else []:
                if isinstance(value, dict):
                    self._variant_row(key, value)
            buttons = QHBoxLayout()
            add = QPushButton("Variante hinzufuegen")
            remove = QPushButton("Ausgewaehlte entfernen")
            buttons.addWidget(add)
            buttons.addWidget(remove)
            add.clicked.connect(lambda: (self._variant_row("variant_" + str(self.table.rowCount()), {"text": "Neue Variante"}), self._changed()))
            remove.clicked.connect(self._remove_row)
            self.form.addRow(buttons)
            self.form.addRow(QLabel("State-Binding auf selector waehlt den Variantenschluessel; Bilder sind PNG-Asset-Referenzen."))
        elif self.collection == "assets":
            self._add("path", QLineEdit(str(entity.get("path", ""))), "Projekt-relativer PNG-Pfad")
            self.form.addRow(QLabel("Bilder ueber 'PNG importieren' exportieren. Transparente Vorschau im Layout-Tab."))

    def _cell_line(self, row, column, text):
        widget = QLineEdit(str(text))
        widget.textChanged.connect(self._changed)
        self.table.setCellWidget(row, column, widget)

    def _placement_row(self, placement):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._cell_line(row, 0, placement.get("id", ""))
        for column, section, field in ((1, "components", "component"), (2, "presentations", "presentation")):
            ids = [r["id"] for r in self.document.raw.get(section, []) if isinstance(r, dict) and "id" in r]
            widget = combo(([""] if column == 2 else []) + ids, str(placement.get(field, "")))
            widget.currentTextChanged.connect(self._changed)
            self.table.setCellWidget(row, column, widget)
        position = QSpinBox()
        position.setRange(0, 2_147_483_647)
        value = placement.get("position", row)
        position.setValue(value if type(value) is int else row)
        position.valueChanged.connect(self._changed)
        self.table.setCellWidget(row, 3, position)

    def _new_placement(self):
        stem = self.document.next_id("placements", "placement.new")
        used = {self.table.cellWidget(r, 0).text() for r in range(self.table.rowCount())}
        base = stem
        index = 2
        while stem in used:
            stem = f"{base}.{index}"
            index += 1
        positions = [self.table.cellWidget(r, 3).value() for r in range(self.table.rowCount())]
        self._placement_row({"id": stem, "position": max(positions, default=-1) + 1})
        self._changed()

    def _variant_row(self, key, variant):
        row = self.table.rowCount()
        self.table.insertRow(row)
        for column, field in enumerate(("key", "text", "background", "foreground", "image")):
            self._cell_line(row, column, key if field == "key" else variant.get(field, ""))
        fit = combo(["", "stretch", "contain"], str(variant.get("image_fit", "")))
        fit.currentTextChanged.connect(self._changed)
        self.table.setCellWidget(row, 5, fit)
        self._cell_line(row, 6, json.dumps(variant["font_size"]) if "font_size" in variant else "")

    def _remove_row(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self._changed()

    def _form_value(self) -> dict:
        value = copy.deepcopy(self.original)
        value["id"] = self.id_field.text().strip()
        if self.collection == "project":
            value["display_name"] = self.widgets["display_name"].text()
        elif self.collection == "components":
            value["type"], value["version"] = self.widgets["type"].currentData()
            value["config"] = self.config_form.value()
        elif self.collection == "states":
            value["value_schema"] = parsed(self.widgets["value_schema"].toPlainText())
            value["scope"] = self.widgets["scope"].currentText()
            value["authority"] = parsed(self.widgets["authority"].text())
            value["persistence"] = self.widgets["persistence"].currentText()
            if self.widgets["has_fallback"].isChecked():
                value["fallback"] = parsed(self.widgets["fallback"].text())
            else:
                value.pop("fallback", None)
        elif self.collection == "bindings":
            value["kind"] = self.widgets["kind"].currentText()
            value["source"] = self.widgets["source"].currentData()
            value["target"] = self.widgets["target"].currentData()
        elif self.collection == "views":
            value["type"] = self.widgets["type"].currentText()
            value["placements"] = []
            original = {p.get("id"): p for p in self.original.get("placements", []) if isinstance(p, dict)}
            for row in range(self.table.rowCount()):
                pid = self.table.cellWidget(row, 0).text().strip()
                placement = copy.deepcopy(original.get(pid, {}))
                placement.update({"id": pid, "component": self.table.cellWidget(row, 1).currentText(),
                                  "position": self.table.cellWidget(row, 3).value()})
                presentation = self.table.cellWidget(row, 2).currentText()
                if presentation:
                    placement["presentation"] = presentation
                else:
                    placement.pop("presentation", None)
                value["placements"].append(placement)
        elif self.collection == "presentations":
            value["variants"] = {}
            originals = self.original.get("variants", {})
            for row in range(self.table.rowCount()):
                key = self.table.cellWidget(row, 0).text()
                if not key or key in value["variants"]:
                    raise DocumentError("Variantenschluessel muss nichtleer und eindeutig sein")
                variant = copy.deepcopy(originals.get(key, {}))
                variant["text"] = self.table.cellWidget(row, 1).text()
                for column, field in ((2, "background"), (3, "foreground"), (4, "image")):
                    text = self.table.cellWidget(row, column).text()
                    if text:
                        variant[field] = text
                    else:
                        variant.pop(field, None)
                fit = self.table.cellWidget(row, 5).currentText()
                if fit:
                    variant["image_fit"] = fit
                else:
                    variant.pop("image_fit", None)
                font = self.table.cellWidget(row, 6).text().strip()
                if font:
                    variant["font_size"] = parsed(font)
                else:
                    variant.pop("font_size", None)
                value["variants"][key] = variant
        elif self.collection == "assets":
            value["path"] = self.widgets["path"].text()
        return value

    def value(self) -> dict:
        value = parsed(self.raw_editor.toPlainText()) if self.tabs.currentIndex() == 1 else self._form_value()
        if not isinstance(value, dict):
            raise DocumentError("Objekt muss ein JSON-Object sein")
        return value
