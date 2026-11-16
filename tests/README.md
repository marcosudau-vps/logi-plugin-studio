# Tests

Aus dem Projektroot, mit [dokumentierter Umgebung](../docs/DEVELOPMENT.md):

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python tools/run_tests.py
```

Die Suite prüft Core, Runtime, Authentisierung/Reconnect, Generator, Autorenmodelle, Studio/Qt, Referenzen, sichere Dateien und Export. SDK-Tests bauen gegen die tatsächlich installierte PluginApi.dll; fehlende Voraussetzungen führen zu sichtbaren Skips. Deploymenttests verwenden temporäre Fake-Verzeichnisse.

REVIEW-FIX-20261106 ergänzt eigenständige Tests in `test_review_native_validation.py`, `test_review_export.py` und `test_review_folder_runtime.py`. Der letzte Test kompiliert die exakten generierten C#-Quellen mit der echten SDK-DLL und ruft Commands, Parameter, Multistate samt Statebildern, Adjustment/Reset, dynamische Membership, Link-Back, Pages und Reconnect auf. Es ist kein physischer Gerätetest.

Contractfixtures liegen unter `tests/fixtures/contracts/`; Regressionen benötigen keine historischen Agentenakten mehr. Zwei CLI-Negativtests verwenden temporäre Verzeichnisse. Sieben optionale Vergleiche mit externen Originalgrafiken werden im bereinigten Quellarchiv sichtbar übersprungen; diese privaten/externen Dateien werden nicht exportiert.

Zusätzliche getrennte Prozesschecks:

```powershell
python tools/run_native_first_probe.py --out work/local-checks/native
python tools/run_product_checks.py --out work/local-checks/legacy
```

Finale Zählungen, Exitcodes und der Test aus einem frisch entpackten echten Archiv stehen in [der Review-Fix-Evidenz](../work/reviews/REVIEW-FIX-20261106/04_tests_und_evidenz.md). Ältere Testzahlen in historischen Abnahmen sind Zeitstände, keine aktuellen Gesamtergebnisse.

## 07.11.2026 – NativeStudioShell/FolderComposer/SDK-Build

`test_native_folder_build_integration.py` prüft den tatsächlichen gemeinsamen Build-Pfad beider Agentenlieferungen: gespeicherte Sidecars, native Standardfälle ohne Extension, Parameter-/Placement-Identität, mehrere SDK-Einstiegsknoten, Dirty-/DiskConflict-/Orphan-Sperren sowie einen echten .NET-/PluginApi.dll-Build über den Hauptfenster-Worker. Der Test installiert kein Plugin und verändert keinen Logitech-Service. [Gemeinsame Abnahme](../work/acceptance/20261107-joint-folder-build/ABNAHME.md).

## 08.11.2026 – SDK-Bridge vs. optionale SharedFolder-Schicht

`tests/test_sdk_bridge_separation.py` prüft per echten generierten C#-Quellen, dass die generische `Bridge.cs.in` keine Folder-Protokollnamen kennt, die Extension allein Layoutdaten interpretiert, native Plugins ihre optionalen Subscriber vor der IPC starten und der Legacy-Build keine Folderklasse benötigt. Die alten Python-Importe referenzieren identische Objekte in `extensions.shared_folders`. [Architekturdokument](../docs/architecture/sdk-bridge-schichtentrennung.md) · [SDK-Python-Checklist](../docs/specifications/sdk-python-api-checklist.md).
