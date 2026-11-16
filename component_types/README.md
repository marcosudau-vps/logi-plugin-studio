# Beispielhafte ComponentType-Manifeste – nur P0-Entwurf

> **Einordnung 03.11.2026:** Die vorhandenen `ComponentType`-Manifeste sind das **bestehende SDK-agnostische Core-Format**. Neue SDK-Fähigkeiten sollen gemäß ARCH-ADR-001 (im Quellprojekt `docs/decisions/ARCH-ADR-001.md`; nicht Teil der Windows-Pakete) zuerst nativ und nur mit minimal notwendiger Bridge abgebildet werden. Kein neues universelles Pflichtmodell aus dem aktuellen Katalog ableiten.

Beide JSON-Manifeste stammen unverändert aus P0 v0.4 und werden vom SDK-unabhängigen Spike geladen. Sie sind **keine** produktive Bibliothek und enthalten keine lauffähige Logitech-Implementierung.

- [`core.command_action.json`](core.command_action.json)
- [`core.host_handler.json`](core.host_handler.json)

Für echte Bibliotheksverträge sind u. a. Versionierungsregeln, Capability-Mapping, Runtime-Adapter, Tests und Abnahme noch offen.
