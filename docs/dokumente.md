# Dokumentenablage

App `backend/documents`, Seite „Dokumente“ (`frontend/src/pages/documents/`).

## Aufbau

- Jeder Dachverband, Verein und jede Abteilung hat eine eigene Ablage mit frei
  angelegten Ordnern (`Folder`). Ein Dokument (`Document`) hat Titel, Datum,
  Bemerkung und beliebig viele Fassungen (`DocumentVersion`); aktuell ist die
  jüngste.
- Die Satzung bleibt in der App `statutes` und erscheint in der Ablage als fester
  Ordner „Satzung“ (gleiche Fassungsliste und öffentlicher Link wie in den
  Einstellungen).
- Daneben kann jede Einheit optional eine **Beitragsordnung** hinterlegen
  (Ralf 2026-10-31): gleiche App, Feld `kind = "fee_rules"` (Satzung: `"statute"`),
  eigene Fassungen und eigener öffentlicher Link, fester Ordner „Beitragsordnung“.
  API: `/api/orgs/<id>/statutes/?kind=fee_rules` (ohne `kind` gilt die Satzung).
  Die Webseite bekommt `fee_rules_url` und `fee_rules_preview_url` und zeigt sie
  unter „Dokumente“. Über den Verbund (Paket `statute`) geht nur die Satzung.
- Ebenso optional eine **Gründungsurkunde** (Ralf 2026-10-31): `kind = "founding_deed"`,
  fester Ordner „Gründungsurkunde“, auf der Webseite `founding_deed_url` und
  `founding_deed_preview_url` unter „Dokumente“ (nach Satzung und Beitragsordnung).
- Dateien: PDF, Word, Excel, PowerPoint, OpenDocument, JPEG, PNG, Text, CSV, je
  höchstens 20 MB. Inhalt und Endung werden geprüft. PDF und Bilder öffnen im
  Browser, alles andere wird heruntergeladen. Ablage im privaten Speicher (in den
  täglichen Backups enthalten). Keine Speichergrenze; die Seite zeigt den belegten
  Platz.
- Suche nur in Titel und Bemerkung (keine Volltextsuche in Dateien).

## Rechte und Sichtbarkeit

- Rechte `docs.view` (lesen) und `docs.manage` (verwalten) für Rollen von
  Dachverband und Verein, `dept.docs.manage` für Abteilungsrollen. Lesen im
  Abteilungsbereich darf jede Abteilungsrolle. Die Migration
  `documents/0002_rls_rechte` gibt beide Rechte allen Rollen, die Rollen verwalten
  dürfen.
- Sichtbarkeit je Ordner: „nur Vorstand“, „alle Mitglieder“ (Mitgliederbereich;
  bei Abteilungsordnern nur Mitglieder der Abteilung), „öffentlich per Link“ und
  beim Dachverband „Vereine des Dachverbands“ (erscheint bei den Vereinen unter
  „Vom Dachverband“, nur lesen).
- Die höhere Ebene sieht die Ablagen darunter nicht automatisch (Vorgabe Ralf,
  2026-10-25). Eine Abteilung kann einzelne Ordner „für den Vereinsvorstand
  freigeben“, ein Verein mit Dachverband „für den Dachverband freigeben“
  (`Folder.shared_up`). Die höhere Ebene liest sie dann unter „Von den …“, ändern
  kann sie sie nicht. Abteilungsablagen verwaltet nur die Abteilung selbst
  (Abteilungsrolle mit `dept.docs.manage`).
- RLS: eigene Organisation, dazu für Vereine die freigegebenen Ordner des
  Dachverbands (Verbandsbereich) und für den Dachverband die nach oben
  freigegebenen Ordner seiner Vereine (`documents/0004_rls_nach_oben`).
- Jeder Dateiabruf wird im Änderungsprotokoll vermerkt (Aktion „angesehen“).

## Papierkorb, Rückgängig, Aufräumen

- Löschen legt ein Dokument 30 Tage in den Papierkorb (Reiter „Papierkorb“), dort
  wiederherstellen oder endgültig löschen. Anlegen, Ändern, Verschieben und Löschen
  lassen sich außerdem über ↶ rückgängig machen.
- Dateien gelöschter Fassungen bleiben liegen, bis die tägliche Aufgabe
  `documents.tasks.purge_documents` sie entfernt (nach Ablauf der Frist für
  Änderungspakete), damit Rückgängig sie zurückholen kann.

## Schnittstellen

- Vorstand: `/api/orgs/<org>/documents/` (eigene Ablage, dazu `shared` und `from_below`),
  Abteilungsbereich: `/api/depts/<abteilung>/documents/`, Mitgliederbereich:
  `/api/portal/<zugang>/documents/` (nur lesen).
- Darunter: `trash/`, `folders/`, `folders/<id>/`, `folders/<id>/documents/`,
  `<id>/`, `<id>/restore/`, `<id>/versions/`, `versions/<id>/`.
- Öffentlich: `/api/public/documents/<schlüssel>/` (Liste als JSON) und
  `/api/public/documents/<schlüssel>/<dokument>/` (aktuelle Fassung).

## Export

Ordner, Dokumente und Fassungen sind im vollständigen Export (mit Häkchen samt
Dateien) und im Export einer Abteilung enthalten, nicht im Dachverbands-Export der
Vereine.
