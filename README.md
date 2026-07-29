# Bohrungen deduplizieren

KiCad-ActionPlugin für den PCB-Editor. Findet Bohrungen, die auf derselben
Stelle liegen, und entfernt die überzähligen.

## Installation

Das Plugin liegt in

```
~/Documents/KiCad/10.0/scripting/plugins/hole_dedup/
```

Im PCB-Editor `Werkzeuge → Externe Plugins → Plugins aktualisieren` aufrufen.
Danach erscheint der Knopf **Bohrungen deduplizieren** in der Werkzeugleiste
und unter `Werkzeuge → Externe Plugins`.

## Was gefunden wird

| Kategorie | Bedeutung | Vorauswahl |
|---|---|---|
| Vias gestapelt | Mehrere Vias auf identischer Position, gleiches Netz, kompatibler Lagenbereich | ✅ ausgewählt |
| Via in Pad-Bohrung | Via liegt vollständig in der Bohrung eines durchkontaktierten Pads desselben Netzes | ✅ ausgewählt |
| Bohrungs-Footprints deckungsgleich | Zwei Footprints mit deckungsgleicher Bohrung (z. B. Montageloch doppelt platziert) | ⬜ manuell prüfen |
| Netz-Konflikt | Gestapelte Bohrungen mit unterschiedlichen Netzen, Via in NPTH-Bohrung | nur Bericht |
| Bohrungen überlappen | Zwei Bohrungen schneiden sich, decken sich aber nicht | nur Bericht |

Nur-Bericht-Zeilen sind grau und lassen sich nicht anhaken.

## Bedienung

* **Positionstoleranz** – Mittelpunkte innerhalb dieser Distanz gelten als
  deckungsgleich (Vorgabe 0,05 mm). Nach dem Ändern `Neu suchen` drücken.
* **Nur sichere / Alle möglichen / Keine** – Auswahl setzen.
* **Richtung tauschen** – bei der markierten Zeile vertauschen, welches Objekt
  entfernt und welches behalten wird.
* Beim Markieren einer Zeile springt der PCB-Editor auf das betroffene Objekt.
* **Auswahl entfernen** – setzt die Änderung um. Rückgängig mit `Strg+Z`.

## Auswahl des zu behaltenden Objekts

* Vias: Es bleibt das Via mit dem größten Lagenbereich, dann der größten
  Bohrung, dann der größten Breite stehen. Vias mit abweichendem Lagenbereich
  werden nur gemeldet.
* Via in Pad: Das Via entfällt, das Pad bleibt.
* Footprints: Vorgeschlagen wird das Entfernen der kleineren Bohrung, weil die
  größere sie geometrisch abdeckt. Achtung – der komplette Footprint wird
  entfernt und kommt bei `PCB aus Schaltplan aktualisieren` zurück, wenn er im
  Schaltplan steht.

## Aufbau

| Datei | Inhalt |
|---|---|
| `core.py` | Erkennung und Anwendung, ohne wxPython, headless testbar |
| `dialog.py` | wx-Dialog mit Befundliste |
| `action.py` | `pcbnew.ActionPlugin` inkl. Werkzeugleisten-Knopf |
| `__init__.py` | Registrierung |
