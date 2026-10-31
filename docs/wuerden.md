# Würden und Würdenträger

Mitglieder › Würdenträger verwaltet Würden (König, Prinz, Zugkönig …) und wer sie wann trug
(Regentschaften, mit Begleitpersonen, Foto und Ordnungszahl). Ehrungen (Ehrenmitglied,
Ehrenmajor) sind etwas anderes: dauerhafte Auszeichnungen an der Person, die den Beitrag ändern
können; sie stehen unter Mitglieder › Einrichtung › Ehrungen (siehe [ehrungen.md](ehrungen.md)).

## Herkunft („Aus“)

Jede Regentschaft kann sagen, aus welcher Einheit der Würdenträger kam: Auswahl aus den
Einheiten darunter (Züge im eigenen Datenbereich, beim Dachverband die Vereine direkt darunter)
oder frei als Text, z. B. für einen aufgelösten Zug vor 100 Jahren. Ist ein Mitglied verknüpft
und gehört es genau einer Untereinheit an, belegt HUBIplan das Feld beim Anlegen vor. Der
Import liest die Spalte „Aus“ (auch „Herkunft“, „Zug“, „Verein“, „Einheit“).

## Weitergeben

Schalter je Würde „an Untereinheiten weitergeben“ (Ralf 2026-10-31):

- Ein Verein unter dem Dachverband sieht unter Würdenträger die weitergegebenen Würden des
  Dachverbands, aber **nur die Träger, die aus ihm kamen** (Herkunft = der Verein). Ändern kann
  er sie nie. Abgesichert per RLS (core 0027).
- Auf der Webseite erscheinen sie nur mit dem Schalter „Weitergegebene Würden der übergeordneten
  Einheiten zeigen“; es gelten die Einwilligungen der vergebenden Einheit. Die Webseite eines
  Zugs zeigt so die weitergegebenen Vereinswürden seiner eigenen Träger (Herkunft = der Zug oder
  ein Zug darunter).
- Die Ordnungszahl zählt über alle Träger der Würde, auch wenn nur ein Teil gezeigt wird.

## Menü der Webseite

Das Menü hat den Punkt „Würdenträger“ (Überschrift) mit Unterpunkten je Würde (Mehrzahl ab zwei
Regentschaften) und „Ehrungen“ (eigene Seite, nicht mehr auf der Vorstandsseite). Unter Webseite ›
Aufbau › Bausteine lassen sich die Unterpunkte per Ziehen umordnen oder herausziehen, und jeder hat
ein eigenes Häkchen (Ralf 2026-10-31; gespeichert in `blocks` als `dignity:<Nummer>` bzw.
`honorary`, ohne Eintrag an). Eine ausgeschaltete Würde fehlt auf der ganzen Webseite (Menü,
`honors/`, Startseite); ausgeschaltete Ehrungen liefert `board/` nicht mehr. Der frühere Schalter
„Würden und Ehrungen unter einem Menüpunkt“ ist entfallen. Die Schnittstelle liefert
`honors_menu` in den Grunddaten immer.
