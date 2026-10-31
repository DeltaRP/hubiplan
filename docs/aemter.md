# Ämter: heutige und frühere Inhaber

Unter **Mitglieder › Ämter** steht je Amt in einer eigenen Tabelle, wer wann welches Amt
hatte. Die Seite zeigt nur Rollen der eigenen Einheit, keine der Untereinheiten (Ralf
2026-10-31); die API liefert beide. Gezählt und gezeigt wird nur das Jahr (Ralf 2026-10-31).

## Frühere Inhaber ohne Konto

Frühere Amtsinhaber sind oft keine Mitglieder mehr. Sie werden als freier Eintrag mit
Name, Anfangs- und Endjahr erfasst (`RoleAssignment.name`, ohne Konto und ohne
Mitgliedschaft), optional mit einer Mitgliedsakte verknüpft (auch ehemalige Mitglieder).

- Gespeichert wird der 1. 1. des Anfangs- und des Endjahres. Das Endjahr ist Pflicht und
  höchstens das laufende Jahr: Ein freier Eintrag ist immer abgeschlossen und zählt deshalb
  nirgends als heutiger Inhaber (Rechte, Impressum, Briefbogen, Vorstand auf der Webseite).
- Heutige Inhaber vergibt man wie bisher unter Einstellungen › Rollen bzw. bei der
  Untereinheit; sie sind unter Ämter nur zu sehen, nicht zu ändern.
- Rechte: lesen mit „Mitglieder ansehen“, ändern und importieren mit „Mitglieder bearbeiten“.
- Code: `backend/access/offices.py`, `backend/access/office_views.py`,
  `frontend/src/pages/members/OfficesPage.tsx`.

## Import

Excel oder CSV mit den Spalten **Amt**, **Name**, **von** und optional **bis** (Jahr;
leer = nur das eine Jahr) und **Einheit** (Name der Untereinheit, z. B. des Zuges; auch
die eigene Bezeichnung der Untereinheiten wird als Spaltenname erkannt). Ablauf wie beim
Würden-Import: Vorschau mit Vorschlägen für Mitgliedsakten und Hinweis „schon vorhanden“,
dann Übernahme. Unbekannte Ämter werden als Rollen ohne Rechte angelegt, nicht als
Vorstandsrolle und noch nicht auf der Webseite („unter Ämter zeigen“ bewusst einschalten).

## Statistik

Unterpunkt **Statistik**, nur Ämter der eigenen Ebene (ohne Untereinheiten, Ralf 2026-10-31):
je Amt die Inhaber nach Jahren, dazu alle Personen nach Jahren im
Amt insgesamt (wahlweise nur Vorstandsrollen). Jahresgenau: „1955 bis 1972“ sind 17 Jahre,
ein einzelnes Jahr zählt als eines, heutige Inhaber bis zum laufenden Jahr. Zeiträume einer
Person werden vereinigt, gleichzeitige Ämter zählen nur einmal. Gleiche Person heißt
dieselbe Mitgliedsakte, sonst derselbe Name.

## Webseite

Die Webseite (Geschichte › Ämter, Vorstand „seit …“) zeigt nur Jahre. Freie Einträge
erscheinen dort mit Namen wie Würdenträger ohne Mitgliedsakte.

## Datenübernahme

Der JSON-Export nimmt freie Einträge mit (`holder_name` bei den Rollen der Einheit,
`former_holders` und `in_chronicle` bei den Rollen der Untereinheiten).
