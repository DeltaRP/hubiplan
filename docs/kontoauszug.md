# Kontoauszug einlesen (CAMT.053)

Unter **Finanzen › Kontoauszüge** lädt die Kasse den Kontoauszug aus dem Online-Banking hoch.
Das Format heißt CAMT.053 (ISO 20022, bei vielen Banken „CAMT-Export“, als XML oder ZIP mit
mehreren Auszügen). Tagesumsätze im Format CAMT.052 und das alte MT940 werden nicht gelesen.
HUBIplan verbindet sich nicht selbst mit der Bank und braucht keine Bankzugangsdaten.
Lesen mit `finance.view`, Einlesen und Zuordnen mit `finance.edit`.

## Ablauf

1. **Datei hochladen.** Das Konto wird an der IBAN erkannt (IBAN beim Konto eintragen) oder
   von Hand gewählt. Gelesen werden nur gebuchte Umsätze (Status BOOK). Jeder Umsatz wird nur
   einmal gespeichert; ein zweites Einlesen desselben Zeitraums meldet „schon eingelesen“.
   Die Originaldatei wird unverändert mit Prüfsumme (SHA-256) aufbewahrt und liegt dem
   Datenexport für eine Prüfung bei.
2. **Vorschläge** (in dieser Reihenfolge):
   - *schon im Kassenbuch*: gleiches Konto, Betrag und Richtung, Datum ±3 Tage, noch keinem
     Umsatz zugeordnet
   - *Lastschriftlauf*: Gutschrift in Höhe eines noch nicht gebuchten Laufs, Einzug ±10 Tage
   - *Zahlung zu Rechnung*: Rechnungsnummer (z. B. `R2026-0007`) im Verwendungszweck und
     mindestens so viel offen; sonst IBAN eines SEPA-Mandats und genau eine offene Rechnung
     mit genau diesem Betrag
   - *Rücklastschrift*: Lastschrift mit Rückgabegrund und bekannter End-to-End-Referenz (nur
     Hinweis: als Ausgabe buchen und bei der Rechnung die Zahlung entfernen)
3. **Erledigen:** Vorschlag übernehmen (einzeln oder alle), mit Kategorie buchen (Text und
   Gegenseite aus dem Auszug, Mitglied optional) oder übergehen (wenn schon anders erfasst).
4. **Saldo-Abgleich:** Der Endsaldo des Auszugs wird mit dem Stand im Kassenbuch am selben
   Tag verglichen.

Ein Auszug lässt sich wieder entfernen, solange daraus nichts gebucht oder zugeordnet ist.

## Sicherheit

Dateien mit DTD oder Entitäten werden abgelehnt; höchstens 10 MB je Upload, 100 Auszüge je
ZIP und 20 MB je entpackter Datei.

## Schnittstelle

`/api/orgs/<id>/finance/`: `bank-statements/` (Liste mit Saldo-Abgleich, POST multipart
`file`, optional `account`; DELETE), `bank-lines/?auszug=&status=` (Liste),
`bank-lines/<id>/assign/` (POST `action`: `suggestion`, `invoice` + `invoice`, `booking` +
`category`, `membership`, `text`, `ignore`, `reopen`), `bank-lines/apply-suggestions/`
(POST optional `statement`).
