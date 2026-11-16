# 01 – Systemidee, Zielbild und Prinzipien

> **Zielarchitektur ab 03.11.2026:** [ARCH-ADR-001](decisions/ARCH-ADR-001.md) hat Vorrang vor älteren Aussagen über ein *fachlich führendes, SDK-unabhängiges* Core-Modell. Die unten stehende Beschreibung erklärt zum großen Teil das bisherige `0.1-draft`-System. Neue SDK-Funktionen werden **nativ-first** abgebildet, nicht als generische Eigenmodelle neu erfunden.

**Status:** beschreibende Interpretation der akzeptierten Architektur-Baseline; Details des Metamodells bleiben Entwurf.  
**Zielpublikum:** Entwickler, Designer, Agenten, Reviewer ohne Kenntnis der vorausgegangenen Unterhaltung.

## 1. Warum dieses System entsteht

Das Logitech Actions SDK stellt eine Schnittstelle bereit, um eigene Aktionen und dynamische Oberflächen für unterstützte Logitech-Geräte zu implementieren. Die bisherigen Tests belegen, dass auf dem MX Creative Keypad ein C#-Plugin auf Tasteneingaben reagiert, Daten an Python überträgt und von Python geänderte LCD-Darstellungen sowie Dynamic-Folder-Mitgliedschaften nachführt.

Diese funktionierenden Tests sind noch **kein Produkt**: Das erste Studio verwendete feste Schalter wie `counter`, `dynamic_folder`, `python_live`; die generierten Aktionen enthielten immer noch Testwerte, vordefinierte Zustände und die Demo-Alternative „vier oder acht Aktionen“.

Das neue System soll stattdessen **beliebige Plugins deklarativ modellierbar** machen. Nicht die Bibliothek sagt „diese Taste startet eine Aufnahme“; der Projektentwickler definiert eine Aktion, ihren Port, ihre Verbindung zu einer Laufzeitoperation und ihre Darstellung. Eine externe Anwendung kann den gewünschten Inhalt und Zustand liefern.

## 2. Bisherige fachneutrale Projektarchitektur (IST/Legacy)

Die Architektur kennt keine eingebauten fachlichen Zustände wie `recording`, `listening`, `paused` oder `ready`. Solche Namen dürfen lediglich **Werte oder Identitäten eines konkreten Projekts** sein. Das System kennt nur Mechanismen:

- **Komponenten** können Eigenschaften, Funktionen und Schnittstellen bereitstellen.
- **Commands** fordern eine Operation an; sie garantieren keinen Erfolg.
- **Events** informieren über Vorkommnisse; sie sind keine gespeicherten aktuellen Werte.
- **States** sind aktuell abrufbare Werte mit Schema, Autorität, Qualität und Scope.
- **Bindings** verbinden kompatible Quellen und Ziele ohne Kenntnis der konkreten Fachfunktion.
- **Views/Placements/Presentations** beschreiben unabhängig voneinander *wo* etwas erscheint und *wie* es aussieht.

## 3. Zwei getrennte Nutzungsszenarien

**A – Entwicklung einer SDK-Fähigkeit**: Im Lab implementieren wir z. B. die Bildaktualisierung, prüfen sie auf echter Hardware und frieren die technische Fähigkeit inklusive Evidenz ein. Sie wird dadurch nicht automatisch ein fertiger Editorbaustein.

**B – Gestaltung eines konkreten Plugins**: Im Studio erzeugt ein Benutzer N Aktionen, M Ordner, beliebige State-Varianten und Verknüpfungen. Der Generator kombiniert dafür bekannte technische Bausteine. Das Plugin verwendet die eigenen Projektwerte; das Lab muss nie installiert sein.

## 4. Architekturprinzipien

1. **Modell vor Codegenerierung:** Das Projekt wird validiert, bevor es in SDK-Code übersetzt wird.
2. **Mechanismen statt Anwendungsfälle:** Keine hartcodierten Alpha/Beta/Gamma-, 4/8-, Counter- oder Recording-Regeln im allgemeinen Kern.
3. **Stabile IDs statt sichtbarer Texte:** Referenzen überleben Umbenennungen und Layoutänderungen.
4. **Wiederverwendbare Instanzen:** Eine Action kann mehrfach platziert werden, ohne neue Logik zu erhalten.
5. **Zustandsverantwortung ist explizit:** Der autoritative Writer wird pro State festgelegt; das Plugin darf nicht aus einem Tastendruck den Erfolg einer Operation behaupten.
6. **Live vs. statisch ist sichtbar:** Ein SDK-Adapter deklariert, welche Eigenschaften ohne Neubuild geändert werden können.
7. **Sichere Synchronisation:** Initial-Snapshot, inkrementelle Updates und Re-Sync; der technische Verbindungszustand ist vom Nutzwert getrennt.
8. **Editor und Laufzeit unabhängig:** Generierte Plugins funktionieren, auch wenn Studio und Lab geschlossen sind; eine externe Python-Anwendung kann jedoch Teil der konkreten Laufzeit sein.
9. **Adapterfähigkeit statt falscher Versprechen:** Ein fachneutral mögliches Modell bedeutet nicht, dass jede Hardware jeden Bestandteil physisch darstellen kann.
10. **Nachweise sind versioniert:** „Im Lab funktioniert“ und „im Studio-generierten Plugin funktioniert“ sind unterschiedliche Freigaben.

## 5. Was das System *nicht* automatisch ist

- Kein allgemeiner Ersatz für Logi Options+; die anfängliche Zuweisung eines Plugin-Einstiegs auf Hardware kann weiter in Options+ erfolgen.
- Keine fertige Automationsplattform mit beliebiger Codeausführung innerhalb der JSON-Projektdatei.
- Keine Zusage, dass eine beliebige Laufzeitänderung auf allen Geräteprofilen live möglich ist.
- Keine Verpflichtung, jedes Objekt als endliche Zustandsmaschine oder mit Start/Stop/KeepAlive-Callbacks zu modellieren.
- Kein Event-Sourcing-System und keine pauschale Exactly-once-Ausführung.

## 6. Minimaler Erfolgsmaßstab des ersten produktiven Entwurfs

Ein Entwickler kann im Studio **eine frei benannte Aktion** anlegen, mit einem **frei benannten externen Handler** verbinden, **einen eigenen typisierten State** definieren und mit einer **frei definierten Presentation** verknüpfen. Die Aktion wird in einer View platziert, gebaut und in Options+ registriert. Ein Tastendruck führt zum externen Handler; dessen Änderung des autoritativen States aktualisiert das Gerät. Ein Service-Neustart stellt die Anzeige per Snapshot wieder her. Dynamische Folder-Mitglieder sind nicht auf Demokonfigurationen begrenzt.

Damit ist nicht schon „alles fertig“, aber die vertikale Kette beweist das **generische Modell** statt nur einzelne Hardcode-Beispiele.

**Weiter:** [Ebenen](02_Ebenen_und_Verantwortung.md), [Metamodell](03_Metamodell.md), [Entstehungsprozess](05_Vom_Projekt_zum_Plugin.md).

## 7. Neues Zielbild – Native First

1. Das **Logitech Actions SDK** ist fachlich maßgeblich für Actions, Parameter, Multistate, Adjustments, Dynamic Folders, Navigationsarten und Icon Templates.
2. Zwischen Python und C# liegt nur die **technisch erforderliche Bridge**; keine parallele native Fachlogik.
3. Studio-Komfort, Wizards, generische Bindings und Vorlagen liegen **in einer separaten optionalen Erweiterungsschicht**.
4. Der vorhandene Core-/StateStore-/Presentation-Code bleibt bis zu einer sicheren, gesonderten Migration als funktionierender IST-Stand erhalten.

Siehe [ARCH-ADR-001](decisions/ARCH-ADR-001.md) und [SDK-Abgleich](specifications/sdk-native-modellabgleich-v01.md).
