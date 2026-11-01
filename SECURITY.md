# Sicherheit

HUBIplan verwaltet personenbezogene Daten von Vereinsmitgliedern, Bankverbindungen und
Kassenbücher. Hinweise auf Sicherheitslücken nehmen wir deshalb sehr ernst und sind für jede
Meldung dankbar.

*Reports in English are welcome; see the [English summary](#english-summary) at the end.*

## Lücke melden

Bitte **kein öffentliches Issue**, sondern vertraulich über GitHub:
[Report a vulnerability](https://github.com/hubiplan/hubiplan/security/advisories/new)
(im Repository unter **Security › Report a vulnerability**).

Hilfreich sind:

- betroffene Fassung (Commit) und betroffener Teil (z. B. Backend-Endpunkt, Seite, Rolle),
- Schritte zum Nachvollziehen, am besten mit den Demodaten (`seed_testdata`),
- eingeschätzte Auswirkung: Wer kann was sehen oder ändern, was er nicht dürfte?

## Was dann passiert

- Wir bestätigen den Eingang in der Regel innerhalb von 7 Tagen.
- Wir prüfen die Meldung, halten dich auf dem Laufenden und stimmen eine Korrektur mit dir ab.
- Die Korrektur erscheint zuerst; Einzelheiten veröffentlichen wir danach als
  Sicherheitshinweis (GitHub Security Advisory), auf Wunsch mit Nennung deines Namens.
- Bitte gib uns bis zur Korrektur, höchstens 90 Tage ab Meldung, Zeit, bevor du Einzelheiten
  veröffentlichst.

## Unterstützte Fassungen

HUBIplan wird fortlaufend aus `main` ausgerollt; es gibt keine Release-Zweige. Korrekturen
gibt es für den aktuellen Stand von `main`. Wer HUBIplan selbst betreibt, sollte regelmäßig
aktualisieren ([docs/betrieb.md](docs/betrieb.md#updates)).

## Umfang

Gemeint ist der Code in diesem Repository: Backend, Oberfläche, Schnittstellen für Webseite
und App, Push-Gateway, Verbund, Anmeldedienst für die Nextcloud sowie die Skripte und
Vorlagen für Ausrollen und Backup. Besonders interessant sind:

- Zugriff auf Daten fremder Vereine oder Einheiten (Mandantentrennung, Row-Level Security),
- Rechte, die eine Rolle nicht haben dürfte, oder Umgehung der Zwei-Faktor-Anmeldung,
- Änderungen während „Ansicht als Rolle“ oder mehr Rechte, als man selbst hat,
- Daten in der öffentlichen Schnittstelle, die nicht freigegeben sind,
- Schwächen im Verbund zwischen Instanzen oder bei Geräteschlüsseln der App,
- Schwächen der Anmeldung per OpenID Connect (z. B. Weiterleitungen, Token für fremde
  Konten oder Nextclouds),
- Zugriff über einen Standzugang der Wettbewerbe auf mehr als den eigenen Wettbewerb,
- verschlüsselt abgelegte Felder oder Dateien, die im Klartext (z. B. in Logs, Exporten oder
  Backups) oder mit dem Schlüssel eines anderen Vereins lesbar sind.

Nicht gemeint sind Lücken in Fremdsoftware (bitte dort melden), reine Last- oder
Überlastungsangriffe, Social Engineering sowie Befunde ohne Auswirkung (z. B. fehlende
Header ohne Angriffsweg).

## Regeln fürs Prüfen

- Prüfe **nur gegen eine eigene Installation** mit erfundenen Daten, z. B. mit
  `docker compose up` und `seed_testdata`.
- Keine Angriffe auf fremde HUBIplan-Instanzen oder echte Vereinsdaten, keine
  Überlastungsangriffe.
- Stößt du doch auf echte personenbezogene Daten, greife nicht weiter darauf zu, speichere
  nichts und melde es uns.

Wer sich an diese Regeln hält und in gutem Glauben handelt, hat von uns keine rechtlichen
Schritte zu erwarten.

## English summary

Please do **not** open a public issue. Report vulnerabilities privately via
[GitHub private vulnerability reporting](https://github.com/hubiplan/hubiplan/security/advisories/new).
We usually acknowledge reports within 7 days and ask you to keep details private until a fix
is available, for at most 90 days. Fixes are made on `main`; there are no release branches.
Test only against your own installation with made-up data (`docker compose up` plus
`seed_testdata`), never against other people's instances or real member data. Good-faith
research that follows these rules will not face legal action from us.
