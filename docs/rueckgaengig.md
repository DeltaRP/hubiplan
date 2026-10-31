# Autospeichern, Rückgängig und Papierkorb

## Autospeichern

Bearbeitungsformulare speichern geänderte Felder kurz nach der letzten Eingabe
(`useAutoSave` in `frontend/src/components/forms.ts`, Anzeige `SaveStatus`).
Neuanlagen speichern erst mit „Anlegen“. Ungültige Eingaben bleiben als
Feldfehler stehen. Beim Bearbeiten eines Termins gehen keine Mails mit; die
Änderungs- bzw. Absage-Mail schickt der Knopf im Formular
(`POST …/events/<id>/notify/`).

Schritt 1 umfasst: Mitgliedsakte (Stammdaten, Zusatzfelder), Termine,
Organisation, Erscheinungsbild, Abteilungen, Mitgliedsarten.

Schritt 2 ergänzt: Beitragssätze, Abrechnungseinstellungen, Vereinsbeiträge,
Konten, Buchungen (Bearbeiten), Veranstaltungen (Finanzen), Zusatzfeld-
Definitionen, Kontaktdaten in der Dachverbandsansicht und die Mitgliedsdaten im
Abteilungsbereich.

Schritt 3 (Oktober 2026) ergänzt: Chronik (Regentschaften samt Foto, Würden),
Titel/Datum/Bemerkung von Dokumenten, Name und Farbe von Terminkategorien,
Umbenennen von Finanzkategorien, Entwurf der Datenschutzhinweise der Webseite
(öffentlich erst mit „Veröffentlichen“), Rechnungsentwürfe (neue Posten
bekommen nach dem ersten Speichern ihre ID) und der eigene Name unter „Mein
Konto“. „Schließen“ schließt ein Formular erst, wenn alles gespeichert ist; einen eigenen „Fertig“-Knopf gibt es nicht.

Bewusst weiter mit Knopf, weil folgenreich, nicht rückgängig oder ein Versand:
Neuanlagen (auch Rechnungen, SEPA-Mandate, Mitgliedschaftszeiträume, Vorlagen),
Rollen und Rechte samt Zeiträumen der Rollenzuordnung, Freigaben im Verbund
(Daten gehen an eine andere Instanz), Mitgliederportal (Änderungsmeldung an
den Vorstand), E-Mail-Adresse und Passwort, Plattformseiten (Löschfrist,
Module, Einheit abschalten wären schon beim Tippen wirksam). Die App nutzt
Bearbeiten-Dialoge mit „Speichern“; jede Änderung ist dort rückgängig zu machen.

## Rückgängig und Wiederherstellen

- Jede ändernde API-Anfrage ergibt ein Änderungspaket (`changes.ChangeSet`) mit
  den Rohwerten vorher/nachher je Datensatz (`changes.ChangeRecord`), auch für
  alles, was beim Löschen mitgelöscht oder geleert wird. Erfasst werden die Apps
  `members`, `events`, `organizations`, `customfields`, `finance`, `billing`,
  `documents` (`backend/changes/tracking.py`).
- Antwort-Kopfzeilen: `X-Change-Set`, `X-Change-Undoable`, `X-Change-Kind`,
  `X-Change-Label` (URL-kodierte Beschreibung für die Schrittliste).
- `POST /api/orgs/<org>/changes/<id>/undo/` spielt ein Paket zurück; das
  Ergebnis ist wieder ein Paket – dessen Rückgängig ist das Wiederherstellen.
  Wurden die Daten seitdem geändert, kommt 409 mit `can_force`; mit
  `{"force": true}` wird trotzdem zurückgesetzt.
- Im Abteilungsbereich: `POST /api/depts/<abteilung>/changes/<id>/undo/`, nur
  für eigene Änderungen und mit den Rechten der Abteilung.
- Gesperrt (nicht rückgängig zu machen): E-Mails, Importe, Zugänge, Rollen und
  Rechte, Ausweise, Fotos und Dateien, Vereinswechsel, Sammeländerungen.
- Finanzen und Abrechnung sind rückgängig zu machen, außer was rechtlich
  festgeschrieben ist: Belege, Jahresabschlüsse, Zahlungen, Mahnungen,
  SEPA-Mandate und Lastschriftläufe (`BLOCKING_MODELS`), außerdem Buchungen in
  abgeschlossenen Geschäftsjahren sowie festgeschriebene Rechnungen und deren
  Positionen (`lock_reason`). Ist ein Datensatz erst später festgeschrieben
  worden, lehnt das Rückgängig ihn ab (harter Konflikt).
- Fremde Änderungen darf nur zurücknehmen, wer das Änderungsprotokoll sehen
  darf; zusätzlich braucht es das Bearbeitungsrecht für die betroffenen Daten.
- Oberfläche: ↶/↷ in der Kopfleiste (Strg+Z / Strg+Y außerhalb von
  Eingabefeldern); ▾ daneben öffnet die Liste der letzten Schritte, dort wählt
  man, bis zu welchem Schritt zurück- oder wiederhergestellt wird. Die Liste
  (bis 50 Schritte je Verein/Abteilung) übersteht ein Neuladen der Seite
  (sessionStorage, gilt für den Browser-Tab). Hinweis nach Anlegen/Löschen, Rückgängig-Knopf im
  Änderungsprotokoll und im Verlauf der Mitgliedsakte, Reiter „Papierkorb“.

## Aufbewahrung

Pakete werden nach 30 Tagen gelöscht (Celery-Job
`changes.tasks.purge_old_changes`, täglich). Beim Löschen nach Ablauf der
Löschfrist (`purge_membership`) werden alle Pakete mit Daten der Person sofort
entfernt.
