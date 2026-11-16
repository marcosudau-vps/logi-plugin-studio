# Sichere Projektuebergabe und lokale Verbindungen

FINAL-PRODUCT-01 wurde unabhaengig fuer den Software-MVP freigegeben.
Die damals hochgeladene **Vollprojekt-ZIP enthielt drei private Connection-
Dateien**. Das getrennte delivery/source-snapshot.zip war bereinigt.
Dies ist ein Verteilungsrisiko, kein belegter Kontomissbrauch.
Vollprojekt-ZIPs niemals als share-safe oder produktiven Release verteilen.

## Sicherer Review-Quellarchivexport

```powershell
python tools\package_result.py
python tools\package_result.py --verify work\autopilot\FINAL-PRODUCT-02\delivery\source-snapshot.zip
```

Alternativ im Studio-Build-Tab **Sicheres Review-Quellarchiv**; der Worker
liefert nur Erfolg/Hash oder SAFE_EXPORT_REFUSED, keine privaten Inhalte.
Nur `delivery\source-snapshot.zip`, dessen `source-hashes.json` und SHA-Datei
weitergeben. Der Export verwendet erlaubte Quellverzeichnisse/Dateitypen,
ausgewaehlte schriftliche Reviewnachweise, kein beliebiges Vollprojekt.
Builds/bin/obj, Vendor-DLLs, Archive, private Connections, Backups, Logs,
Receipts, lokale Environment-/Schluesseldateien werden nicht exportiert.
Symlinks/Junctions und nicht klassifizierte Quelldateien werden verweigert.
Verdachtige Geheimnisdateien/-inhalte brechen den Export ab; keine
automatische Bereinigung aktiver Dateien. CRC und SHA-256 werden erneut
verifiziert; extra/unbekannte ZIP-Dateien machen eine ZIP nicht share-safe.

Der Export entdeckt studio.connection.json in verschachtelten lokalen
Ordnern und prueft deren Keybytes auf Abwesenheit in ausgewaehlten Quellen.
Er erkennt gaengige Credentials/PEM/Tokens; das ist **kein universeller
Secret-Scanner fuer beliebige Kodierungen oder persoenliche Inhalte**.
Auch schriftliche Nachweise vor Weitergabe fachlich pruefen.
Keine Schluesselwerte werden in Fehlermeldungen oder Manifeste geschrieben.

Ein Fehler verlangt lokale Pruefung. Nicht als Ausweg den gesamten
Projektordner mit Explorer zippen. Lokale private Arbeitskopie und
bereinigte Reviewlieferung sind unterschiedliche Artefakte.

## Kontrollierter Schluesselwechsel vor Rollout

Bereits verteilte Test-Keys nicht produktiv wiederverwenden. Bestehende
Verbindungen werden durch diesen Folgelauf nicht geloescht oder erneuert.
Sicherster Workflow ohne unterbrochene aktive Verbindung:

1. Eigene beabsichtigte Plugin-ID/Projektrevision im Studio festlegen.
2. In **neues leeres, isoliertes Build-Ausgabeverzeichnis** generieren/bauen.
   `provision_connection` erzeugt dort neue zufaellige Installation/Key/Port.
3. Neuen eigenstaendigen Host mit der neuen privaten Datei lokal pruefen.
4. Eigenen alten Host bewusst beenden; Plugin-Reload/Wechsel erst nach
   gesonderter Nutzerfreigabe und geprueftem Dry-Run.
5. Neue private Connection **nur lokal** zwischen eigener DLL und Host
   verwenden. Kein Austausch der Connection per Review-ZIP.

Das neue Paket und die alte Host-/Plugin-Installation koennen getrennt
vorbereitet werden; kein heimlicher In-place-Keywechsel und kein stiller
Service-Neustart. Alte aktive Keys/Archive nicht pauschal loeschen.
Unbereinigte Nutzer-ZIPs nicht weiterverbreiten; bereits erlaubte lokale
Abnahmeakten bleiben unveraendert. Backup/Receipt privat lokal halten.

Lokale Prozesse desselben Windows-Kontos und Administratoren mit
Dateileserechten sind keine isolierte Sicherheitsgrenze.
