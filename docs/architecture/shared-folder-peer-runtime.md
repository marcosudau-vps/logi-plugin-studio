# Eingebettete Shared-Folder-Peers

Der Shared-Generator fügt dem bestehenden SDK-Folderpfad einen plugin-eigenen Python-Child und einen optionalen C#-Adapter hinzu. Der Child enthält den lokalen Host und direkte, authentisierte Peer-Kanäle. Der kompatible Modus behält die bisherige Folderprojektion. Der explizite native Modus erzeugt statische SDK-Folder ohne die virtuelle Layout-Laufzeit.

~~~text
SDK-Folder C → eigener Host C → direkt zum Owner-Host A → SDK-Action A
                                                  ↓
                                           Python-Handler A

SDK-Action A → Darstellung im Owner-Host A → abonnierter Scope C
                                             ↓
                                     eigene Folder-Notifications C
~~~

Stabile Referenzen enthalten Plugin-ID, Action-/Node-ID und ggf. SDK-Parameter. Der Owner hält die SDK-Action und ihren Zustand. Der Consumer hält nur die abgeleitete Darstellung des referenzierten Scopes. Die Authentisierung bindet zwei Plugininstanzen über separat provisionierte Paar-Schlüssel. Konkrete Lese- und Ausführungsfreigaben bleiben beim Owner. Die generische Bridge transportiert weiterhin authentisierte Nachrichten über ihren bestehenden Vertrag.

- [Betriebsarten, Provisionierung und Studio-Kante](../../work/shared-final/AP-SHARED-FINAL-001/outputs/integration_contract.md)
- [Peer-Protokoll und Reichweiten der Ausfallprüfung](../../work/shared-final/AP-SHARED-FINAL-001/outputs/peer_protocol.md)
- [Software- und Hardwaregrenzen](../../work/shared-final/AP-SHARED-FINAL-001/05_offene_punkte.md)
