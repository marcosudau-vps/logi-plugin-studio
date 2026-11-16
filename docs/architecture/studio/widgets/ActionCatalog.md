# ActionCatalogWidget – Schnittstelle

**Aktuelle Erweiterung AP-INSP-002: APPROVED.** Create ist mit geladenem Projekt aktiv; die älteren Sperraussagen unten beschreiben die v1-Baseline. Aktueller Vertrag im Schlussabschnitt.


**Status:** isoliert APPROVED (AP-WIDGET-003); **native Hostintegration IMPLEMENTIERT, unabhängig APPROVED am 06.11.2026**.  
**Code:** `src/studio/action_catalog/widget.py`; Datentypen `NativeProject`, `NativeAction`, `ActionOffer`. Abnahme: `work/acceptance/20261104-keypad-catalog/ABNAHME.md`.

## Zweck

Darstellung **existierender** SDK-Aktionsdefinitionen einschließlich konkreter Parameterangebote. Der Katalog ist eine Ansicht, **keine** zweite persistente Action-Domäne.

## Öffentliche Host-Eingaben

| Methode | Vertrag |
|---|---|
| `set_project(NativeProject \| None)` | Anzeige der aktuellen Actions, kein Datenbank-Commit |
| `set_actions(Iterable[NativeAction])` | nativer Lese-Snapshot |
| `set_images(Mapping[OfferKey,QImage])` | extern gerenderte Bilder, kopiert |
| `set_selected_action(action_id,action_parameter=None)` | Host-Selektion still spiegeln |
| `set_filter(text)` / `set_type_filter(sdk_type)` / `set_group_order(order)` | reine Ansicht |
| `set_usage_counts(Mapping[OfferKey,int])` | **nur** tatsächlich belegte Placement-Zahlen |
| `offer_for(action_id,action_parameter=None)` | konkretes `ActionOffer \| None`; kein hypothetischer Parameter |

`OfferKey` = Paar (`action_id`, `action_parameter`); eine Parameterwahl ist keine neue SDK-Action.

## Qt-Ausgänge

- `actionSelected(object)`: `ActionOffer` aus **echter Benutzerselektion**.
- `actionEditRequested(str)`: native `action_id`, Host öffnet den Inspector-Tab (AP-INSP-001).
- `createActionRequested()`: Hostroute zu `Coordinator.request_create → Shell.create_action` (AP-INSP-002, APPROVED).

Drag & Drop bietet ein ActionOffer; tatsächliche Placement-Änderung darf **nur** über Host-Validierung erfolgen. Kein Drop darf in dieser Phase sofort Projekt-JSON schreiben.

## Host-Verdrahtung

**IMPLEMENTIERT:** V-02, V-05, V-06. Die programmatische Auswahl darf weder `actionSelected` noch einen Doppelcommit auslösen. `ActionOffer` mit nicht existierender oder veralteter Action-ID wird vom Host abgelehnt. Bis ein echter KeypadFrame/Placement-Adapter existiert, nur Ansicht/Selektion/Edit-Anforderung.

[Gesamtkarte](../00-Gesamtkarte.md) · [Verbindungsregister](../04-Verbindungsregister.md)

## Implementierter Hostvertrag AP-STUDIO-002

`src/studio/native_shell/coordinator.py`: V-02 Sessionprojektion → `set_project`; V-05 `actionSelected → select_offer`; V-06 `actionEditRequested → request_edit`; V-22 `catalog_tree.itemSelectionChanged → _catalog_selection`; V-34/V-35 Such-/Typfilter → `_filtered`; V-41 `_mirror → set_selected_action`. Tests je Kante im [Register](../04-Verbindungsregister.md).

Zusätzliche lesende APIs: `selected_key()`, `selected_offer()`, `visible_keys()`, `item_for(id,parameter)`, `group_names()`, `empty_state()`. `selected_key` kann eine parameterisierte Definition `(id,None)` bezeichnen; `offer_for` liefert dafür ausdrücklich None. Der Host berücksichtigt die Elternauswahl, ohne eine allgemeine Variante zu erfinden. Konkrete Varianten behalten `NativeParameter.name`. Gleiche Anzeigenamen sind keine Identität.

V-27 sichert `new_action_button` über einen Host-EnabledChange-Filter dauerhaft als deaktiviert; das wiederverwendete Widget aktiviert ihn intern sonst bei Refresh erneut. V-07 bleibt AUFGESCHOBEN. Bearbeiten öffnet seit AP-INSP-001 den vollständigen Inspector für vorhandene Actions; Erstellung bleibt gesperrt. Drag liefert weiterhin nur eine Referenz; die Shell hat kein freigegebenes Dropziel. Kein Dateizugriff/Commit durch das Widget. Leerzustände ohne Projekt/Actions/Filtertreffer sind reine Ansicht. Projektwechsel leert Bilder, Nutzungszahlen, Filter und alte Parameterauswahl.

AP-HELP-001 (**APPROVED**) bindet hostseitig Suche, Typfilter, A–Z, Definition/Parameter, Bearbeiten und Rücksetzen an passende Topics. Quelle catalog besitzt auch die unveränderten Defaultthemen catalog.*, action.definition. Die deaktivierte Erstellung erklärt ihren fehlenden Editor über Tooltip/Kontexthilfe. Such-Facts enthalten nur Länge und Trefferzahlen, keine Sucheingabe. Kein Widgetcode geändert. Qt-Nachweise: `tests/test_native_help_coverage.py::test_catalog_search`, `test_catalog_type`, `test_catalog_sort`, `test_catalog_parameter`, `test_catalog_edit`, `test_catalog_reset`, `test_disabled_capabilities`; [Arbeitsakte](../../../../work/help-integration/AP-HELP-001/README.md).

## AP-INSP-001 – APPROVED

Katalog-Bearbeiten führt jetzt über request_edit/editRequested zum Inspector-Tab (V-54, V-31 aktualisiert). Toolbar-Anzeigename bleibt Schnelleditor. Kein Create-Vertrag; + Neue Aktion bleibt deaktiviert.

Nachweis: `tests/test_action_inspector_integration.py`; [Inspector-Vertrag](ActionInspector.md), [Arbeitsakte](../../../../work/action-inspector/AP-INSP-001/README.md). Unabhängige Abnahme am 06.11.2026 erfolgt.

## Aktueller Create-Hostvertrag AP-INSP-002 – APPROVED

V-63 verbindet das vorhandene createActionRequested mit dem Host. Der EnabledChange-Filter blockiert nur ohne Session; Filter, Sortieren, Undo/Redo und Refresh erhalten den aktiven Createbefehl bei geladenem Projekt. Das wiederverwendbare Katalogwidget bleibt bytegleich. Frühere Aussagen zur dauerhaften Sperre in den AP-STUDIO-002-/AP-INSP-001-Abschnitten dokumentieren deren historische Baseline und sind durch diesen Absatz ersetzt.

Vor Apply erscheint keine neue Action im Katalog/Explorer. Ein Commit wählt die eingegebene ID zuverlässig aus, macht sie trotz vorherigem Such-/Typfilter sichtbar und öffnet Editmodus. Delete entfernt sie aus der frischen Projektion, `offer_for` liefert anschließend None; alte Offers können kein neues Ziel bestimmen. Cancel eines Dirty-Draftguards erhält die vorige Auswahl. Neue Definitionen bleiben unplatziert. Hilfe des Createbuttons ist inspector.create; die frühere catalog.create_unavailable-Definition bleibt ausschließlich historische Registry-Kompatibilität und ist keinem aktiven Control zugeordnet.

Nachweise: `test_action_lifecycle_widget.py::test_create_button_project_activation_after_filter_sort_history`, `test_action_lifecycle_integration.py::test_v63_catalog_create_intent_to_guarded_create_draft`, `test_v64_create_apply_exactly_one_replace_and_selected_edit_mode`, `test_v66_confirmed_delete_one_replace_history_save_reload`. [Lifecycle-Vertrag](ActionLifecycle.md).
