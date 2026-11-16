# P0 Core-Spike – experimenteller Prüfer (keine produktive Runtime)

Unverändert übernommener Python-Validator aus P0 v0.4. Die folgenden Befehle funktionieren vom Projektroot aus (Windows / PowerShell oder CMD):

```powershell
python tools/run_core_spike.py validate examples/project_v0_1_draft.json
python tools/run_core_spike.py inspect examples/project_v0_1_draft.json
python tools/run_tests.py
```

Die Wrapper ergänzen `src/` ausschließlich für den Python-Importpfad. Der Spike validiert nur eine konservative Teilmenge, führt keine Bindings aus, bietet keine Runtime-Synchronisation und hat keine Logitech-SDK-/Qt-Abhängigkeiten. **14 P0-Tests** sind als technische Quelle enthalten. Der neue produktive Core gehört nach [../core/](../core/).
