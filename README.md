# Bohrungen und Leiterbahnen deduplizieren

KiCad-ActionPlugin für den PCB-Editor. Findet Bohrungen, die auf derselben
Stelle liegen, sowie Leiterbahnsegmente, die doppelt oder übereinander
liegen, und entfernt die überzähligen.

## Installation

Das Plugin liegt in

```
~/Documents/KiCad/10.0/scripting/plugins/hole_dedup/
```

Im PCB-Editor `Werkzeuge → Externe Plugins → Plugins aktualisieren` aufrufen.
Danach erscheint der Knopf **Bohrungen und Leiterbahnen deduplizieren** in der Werkzeugleiste
und unter `Werkzeuge → Externe Plugins`.

## Was gefunden wird

| Kategorie | Bedeutung | Vorauswahl |
|---|---|---|
| Vias gestapelt | Mehrere Vias auf identischer Position, gleiches Netz, kompatibler Lagenbereich | ✅ ausgewählt |
| Via in Pad-Bohrung | Via liegt vollständig in der Bohrung eines durchkontaktierten Pads desselben Netzes | ✅ ausgewählt |
| Bohrungs-Footprints deckungsgleich | Zwei Footprints mit deckungsgleicher Bohrung (z. B. Montageloch doppelt platziert) | ⬜ manuell prüfen |
| Netz-Konflikt | Gestapelte Bohrungen mit unterschiedlichen Netzen, Via in NPTH-Bohrung | nur Bericht |
| Bohrungen überlappen | Zwei Bohrungen schneiden sich, decken sich aber nicht | nur Bericht |
| Leiterbahn exakt doppelt | Zwei gerade Segmente, gleiches Netz, gleiche Lage, gleiche Breite, Endpunkte identisch (≤ 10 µm) | ✅ ausgewählt |
| Leiterbahn in Leiterbahn enthalten | Segment liegt komplett auf einem längeren oder breiteren Segment derselben Linie | ✅ ausgewählt |
| Leiterbahnen überlappen – verschmelzen | Gleich breite Segmente auf einer Linie decken sich teilweise; das längste wird auf die Gesamtlänge verlängert, die anderen entfallen | ✅ ausgewählt |
| Leiterbahnen überlappen – verschiedene Breite | Teilweise Überdeckung bei verschiedenen Breiten | nur Bericht |

Nur-Bericht-Zeilen sind grau und lassen sich nicht anhaken.

Leiterbahnen gelten als „auf einer Linie", wenn beide Endpunkte des einen
Segments höchstens 2 µm neben der Linie des anderen liegen (Rundungsreste
des Routers). Bögen und Vias werden nicht angefasst, Null-Segmente überlässt
das Plugin KiCads eigenem `Cleanup Tracks & Vias`. Die Kupferfläche ändert
sich bei keiner der drei auswählbaren Kategorien, Gerber bleiben identisch.

## Bedienung

* **Positionstoleranz** – Mittelpunkte innerhalb dieser Distanz gelten als
  deckungsgleich (Vorgabe 0,05 mm); bei Leiterbahnen entscheidet sie, ob ein
  Segment noch als „enthalten" zählt. Nach dem Ändern `Neu suchen` drücken.
* **Nur sichere / Alle möglichen / Keine** – Auswahl setzen.
* **Richtung tauschen** – bei der markierten Zeile vertauschen, welches Objekt
  entfernt und welches behalten wird.
* Beim Markieren einer Zeile springt der PCB-Editor auf das betroffene Objekt;
  das zu entfernende Objekt wird selektiert (Auswahlfarbe), das bleibende
  aufgehellt. So ist auch bei deckungsgleichen Objekten klar, welches gemeint
  ist. Die Hervorhebung verschwindet beim Schließen des Dialogs.
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
* Leiterbahnen: Bei gleicher Breite bleibt das längste Segment (und wird bei
  Teilüberdeckung verlängert), bei verschiedener Breite bleibt das breitere.
  Segmente, die an den entfernten Enden hingen, bleiben verbunden, weil ihr
  Endpunkt weiterhin auf dem verbleibenden Kupfer liegt.

## Aufbau

| Datei | Inhalt |
|---|---|
| `core.py` | Erkennung und Anwendung für Bohrungen, ohne wxPython, headless testbar |
| `tracks.py` | Erkennung und Anwendung für Leiterbahnsegmente, ebenfalls ohne wxPython |
| `dialog.py` | wx-Dialog mit Befundliste |
| `action.py` | `pcbnew.ActionPlugin` inkl. Werkzeugleisten-Knopf |
| `__init__.py` | Registrierung |
