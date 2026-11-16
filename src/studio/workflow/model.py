"""Qt-freies Schrittmodell des geführten Ablaufs.

Reine Funktionen: ``Facts`` → ``StepState``. Keine Datei-, Session- oder
Qt-Zugriffe und kein eigener Zustand. Der Host liest die Fakten aus den
bestehenden Eigentümern und ruft ``evaluate`` nach jeder Änderung neu auf.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Status eines Kriteriums bzw. eines Schritts.
DONE = "done"        # erfüllt
OPEN = "open"        # noch zu erledigen (sperrt das Weitergehen)
WARNING = "warning"  # Hinweis, sperrt nicht
ERROR = "error"      # konkreter Fehler (sperrt)
STALE = "stale"      # Ergebnis älter als der gespeicherte Stand (sperrt)
INFO = "info"        # optional und (noch) nicht genutzt, sperrt nicht
LOCKED = "locked"    # vorherige Schritte nicht abgeschlossen

BLOCKING = (OPEN, ERROR, STALE)
STATUS_TEXT = {DONE: "erfüllt", OPEN: "offen", WARNING: "Hinweis", ERROR: "Fehler", STALE: "veraltet",
               INFO: "optional", LOCKED: "gesperrt"}
STATUS_MARK = {DONE: "✔", OPEN: "○", WARNING: "!", ERROR: "✖", STALE: "↻", INFO: "–", LOCKED: "🔒"}


@dataclass(frozen=True)
class Step:
    key: str
    number: int
    title: str
    optional: bool
    views: tuple[str, ...]      # sichtbare Registerkarten (Schlüssel des Hosts)
    panes: tuple[str, ...]      # sichtbare Seitenbereiche: explorer, catalog
    tools: tuple[str, ...]      # sichtbare Werkzeugleisten-Einträge zusätzlich zu den immer sichtbaren
    home: str                   # Registerkarte, die beim Betreten gezeigt wird
    topic: str                  # Führungsthema in der bestehenden Hilfe


STEPS = (
    Step("project", 1, "Projekt", False, ("start", "help"), (), (), "start", "guide.project"),
    Step("handlers", 2, "Handler", False, ("handlers", "problems", "help"), ("explorer",), (),
         "handlers", "guide.handlers"),
    Step("actions", 3, "Aktionen", False, ("inspector", "states", "details", "problems", "help"),
         ("explorer", "catalog"), ("rename",), "inspector", "guide.actions"),
    Step("symbols", 4, "Darstellung", True, ("symbols", "inspector", "problems", "help"), ("catalog",),
         ("ict",), "symbols", "guide.symbols"),
    Step("layout", 5, "Belegung", True, ("keypad", "folders", "problems", "help"), ("catalog",), ("ict",),
         "keypad", "guide.layout"),
    Step("build", 6, "Prüfen und Bauen", False, ("problems", "build", "help"), (), ("build",),
         "build", "guide.build"),
    Step("install", 7, "Installieren und Testen", False, ("install", "peers", "help"), (), (),
         "install", "guide.install"),
)
STEP_KEYS = tuple(s.key for s in STEPS)


def step(key: str) -> Step:
    for candidate in STEPS:
        if candidate.key == key:
            return candidate
    raise KeyError(key)


@dataclass(frozen=True)
class Facts:
    """Nur gelesene, bereits geprüfte Tatsachen der bestehenden Eigentümer."""
    has_project: bool = False
    project_saved: bool = False
    plugin_id: str = ""
    display_name: str = ""
    handlers: tuple[str, ...] = ()
    handler_file: str = ""
    handler_file_error: str = ""
    handlers_unregistered: tuple[str, ...] = ()
    actions: int = 0
    actions_without_handler: tuple[str, ...] = ()
    draft_open: bool = False
    missing_assets: tuple[str, ...] = ()
    actions_with_symbol: int = 0
    orphan_placements: tuple[str, ...] = ()
    placements: int = 0
    extension_saved: bool = True
    problem_errors: int = 0
    prerequisites: tuple[str, ...] = ()
    build_done: bool = False
    build_current: bool = False
    build_error: str = ""
    package_valid: bool = False
    installed: bool = False
    loaded: bool = False
    connected: bool = False
    install_current: bool = False
    hardware_confirmed: bool = False


@dataclass(frozen=True)
class Criterion:
    key: str
    text: str
    status: str
    detail: str = ""
    target: str = ""  # Sprungziel des Hosts: Registerkarte oder Befehl ("do:<name>")


@dataclass(frozen=True)
class StepState:
    step: Step
    status: str
    criteria: tuple[Criterion, ...] = field(default_factory=tuple)
    reachable: bool = True

    @property
    def blockers(self) -> tuple[Criterion, ...]:
        return tuple(c for c in self.criteria if c.status in BLOCKING)


def _listed(values, limit=3) -> str:
    values = tuple(values)
    return ", ".join(values[:limit]) + (f" und {len(values) - limit} weitere" if len(values) > limit else "")


def _project(f: Facts):
    yield Criterion("project.open", "Projekt geöffnet oder neu angelegt", DONE if f.has_project else OPEN,
                    "" if f.has_project else "Ein neues Projekt anlegen oder ein vorhandenes öffnen.", "start")
    if not f.has_project:
        return
    named = bool(f.plugin_id.strip() and f.display_name.strip())
    yield Criterion("project.identity", "Plugin-ID und Anzeigename vergeben", DONE if named else OPEN,
                    f"{f.display_name} ({f.plugin_id})" if named else "Plugin-ID oder Anzeigename fehlt.", "start")


def _handlers(f: Facts):
    yield Criterion("handlers.exists", "Mindestens ein Handler angelegt", DONE if f.handlers else OPEN,
                    _listed(f.handlers) if f.handlers else "Ein Handler verbindet Aktionen mit deinem Python-Code.",
                    "handlers")
    if not f.handler_file:
        yield Criterion("handlers.file", "Python-Handlerdatei zugeordnet", OPEN,
                        "Eine Handlerdatei aus der Vorlage erzeugen oder eine vorhandene auswählen.", "handlers")
        return
    if f.handler_file_error:
        yield Criterion("handlers.file", "Python-Handlerdatei zugeordnet", ERROR, f.handler_file_error, "handlers")
        return
    yield Criterion("handlers.file", "Python-Handlerdatei zugeordnet", DONE, f.handler_file, "handlers")
    if f.handlers_unregistered:
        yield Criterion("handlers.registered", "Alle Handler werden in der Datei registriert", WARNING,
                        "Nicht registriert: " + _listed(f.handlers_unregistered), "handlers")
    else:
        yield Criterion("handlers.registered", "Alle Handler werden in der Datei registriert", DONE, "", "handlers")


def _actions(f: Facts):
    yield Criterion("actions.exists", "Mindestens eine Aktion angelegt", DONE if f.actions else OPEN,
                    f"{f.actions} Aktion(en)" if f.actions else "Im Aktionskatalog „+ Neue Aktion“ wählen.",
                    "inspector")
    yield Criterion("actions.handlers", "Jede Aktion hat einen gültigen Handler",
                    ERROR if f.actions_without_handler else DONE,
                    "Ohne gültigen Handler: " + _listed(f.actions_without_handler)
                    if f.actions_without_handler else "", "inspector")
    yield Criterion("actions.draft", "Kein offener Entwurf im Aktionsinspektor", OPEN if f.draft_open else DONE,
                    "Entwurf mit „Übernehmen“ abschließen oder verwerfen." if f.draft_open else "", "inspector")


def _symbols(f: Facts):
    if f.missing_assets:
        yield Criterion("symbols.assets", "Alle zugeordneten Symbole und Bilder sind vorhanden", WARNING,
                        "Nicht gefunden: " + _listed(f.missing_assets), "symbols")
    elif f.actions_with_symbol:
        yield Criterion("symbols.assets", "Alle zugeordneten Symbole und Bilder sind vorhanden", DONE,
                        f"{f.actions_with_symbol} von {f.actions} Aktion(en) mit eigenem Symbol", "symbols")
    else:
        yield Criterion("symbols.assets", "Eigene Symbole gestalten", INFO,
                        "Optional: ohne eigenes Symbol zeigt das Gerät den Anzeigenamen.", "symbols")


def _layout(f: Facts):
    if f.orphan_placements:
        yield Criterion("layout.references", "Keine Platzierung verweist auf eine fehlende Aktion", ERROR,
                        "Verwaist: " + _listed(f.orphan_placements), "folders")
    elif f.placements:
        yield Criterion("layout.references", "Keine Platzierung verweist auf eine fehlende Aktion", DONE,
                        f"{f.placements} Platzierung(en)", "keypad")
    else:
        yield Criterion("layout.references", "Aktionen auf Tasten und in Ordner legen", INFO,
                        "Optional: Aktionen lassen sich auch erst in Logi Options+ zuweisen.", "keypad")
    yield Criterion("layout.saved", "Ordner und Belegung gespeichert", DONE if f.extension_saved else OPEN,
                    "" if f.extension_saved else "Mit „Alles speichern“ sichern.", "do:save_all")


def _build(f: Facts):
    saved = f.project_saved and f.extension_saved and not f.draft_open
    yield Criterion("build.saved", "Alles gespeichert", DONE if saved else OPEN,
                    "" if saved else "Der Build verwendet nur den gespeicherten Stand. „Alles speichern“ wählen.",
                    "do:save_all")
    yield Criterion("build.errors", "Keine Fehler in der Problemliste", ERROR if f.problem_errors else DONE,
                    f"{f.problem_errors} Fehler – in der Problemliste öffnen und beheben." if f.problem_errors else "",
                    "problems")
    yield Criterion("build.prerequisites", "Voraussetzungen für den Build vorhanden",
                    ERROR if f.prerequisites else DONE, " ".join(f.prerequisites), "build")
    if f.build_error and not f.build_done:
        yield Criterion("build.done", "Plugin erfolgreich gebaut", ERROR, f.build_error, "build")
    elif not f.build_done:
        yield Criterion("build.done", "Plugin erfolgreich gebaut", OPEN, "„SDK-Plugin bauen“ wählen.", "do:build")
    elif not f.build_current:
        yield Criterion("build.done", "Plugin erfolgreich gebaut", STALE,
                        "Das Projekt wurde seit dem letzten Build geändert. Bitte neu bauen.", "do:build")
    else:
        yield Criterion("build.done", "Plugin erfolgreich gebaut", DONE, "Der Build passt zum gespeicherten Stand.",
                        "build")


def _install(f: Facts):
    yield Criterion("install.package", "Gebautes Paket ist gültig", DONE if f.package_valid else OPEN,
                    "" if f.package_valid else "Zuerst in Schritt 6 bauen.", "install")
    if f.installed and not f.install_current:
        yield Criterion("install.installed", "Plugin installiert", STALE,
                        "Installiert ist ein älterer Build. „Installieren / Aktualisieren …“ wählen.", "install")
    else:
        yield Criterion("install.installed", "Plugin installiert", DONE if f.installed else OPEN,
                        "" if f.installed else "„Plan anzeigen“ prüfen, dann „Installieren / Aktualisieren …“.",
                        "install")
    running = f.installed and f.loaded and f.connected
    yield Criterion("install.running", "Plugin geladen und mit dem Python-Host verbunden",
                    DONE if running else OPEN,
                    "" if running else "Nach der Installation „Ladezustand prüfen“ wählen.", "install")
    yield Criterion("install.hardware", "Am Gerät getestet und bestätigt", DONE if f.hardware_confirmed else OPEN,
                    "" if f.hardware_confirmed else
                    "Aktion in Logi Options+ auf eine Taste legen, drücken und das Ergebnis hier bestätigen.",
                    "do:confirm_hardware")


_RULES = {"project": _project, "handlers": _handlers, "actions": _actions, "symbols": _symbols,
          "layout": _layout, "build": _build, "install": _install}


def _status(criteria) -> str:
    states = {c.status for c in criteria}
    for candidate in (ERROR, STALE, OPEN, WARNING):
        if candidate in states:
            return candidate
    return INFO if INFO in states else DONE


def complete(state: StepState) -> bool:
    """Ein Schritt gilt als abgeschlossen, wenn kein Kriterium das Weitergehen sperrt."""
    return state.status in (DONE, WARNING, INFO)


def evaluate(facts: Facts) -> tuple[StepState, ...]:
    """Status aller Schritte. Spätere Schritte sind erst nach den vorherigen erreichbar."""
    result, reachable = [], True
    for definition in STEPS:
        criteria = tuple(_RULES[definition.key](facts))
        status = _status(criteria)
        result.append(StepState(definition, status if reachable else LOCKED, criteria, reachable))
        reachable = reachable and status in (DONE, WARNING, INFO)
    return tuple(result)


def first_incomplete(states) -> str:
    """Schlüssel des ersten nicht abgeschlossenen Schritts, sonst der letzte Schritt."""
    for state in states:
        if not complete(state):
            return state.step.key
    return states[-1].step.key


def guidance(state: StepState) -> str:
    """Kurzer nächster Handgriff für den Schritt: das erste sperrende Kriterium."""
    if state.status == LOCKED:
        return "Dieser Schritt wird frei, sobald die vorherigen Schritte abgeschlossen sind."
    for criterion in state.criteria:
        if criterion.status in BLOCKING:
            return criterion.detail or criterion.text
    for criterion in state.criteria:
        if criterion.status == WARNING:
            return "Hinweis: " + (criterion.detail or criterion.text)
    if state.step.key == STEP_KEYS[-1]:
        return "Fertig: Das Plugin ist gebaut, installiert und am Gerät bestätigt."
    return "Dieser Schritt ist abgeschlossen. Mit „Weiter“ geht es zum nächsten."
