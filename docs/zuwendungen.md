# Zuwendungsbestätigungen

Spendenbescheinigungen nach den amtlichen Mustern (BMF-Schreiben vom 7. November 2013 mit
späteren Änderungen) für steuerbegünstigte Körperschaften. Der Menüpunkt
**Finanzen › Zuwendungsbestätigungen** erscheint für jede Einheit mit Kasse (nicht für die
Plattform). Ausgestellt wird nur, wenn in den Einstellungen „Steuerbegünstigt mit eigenem
Bescheid“ angehakt ist (Feld `enabled`, in `/api/me/organizations/` als `donations_enabled`)
und die Angaben zum Bescheid vollständig und gültig sind. Der Registereintrag (e.V.) spielt
keine Rolle: auch nicht eingetragene Vereine können steuerbegünstigt sein (§ 1 Abs. 1 Nr. 5
KStG, § 10b Abs. 1 Satz 2 Nr. 2 EStG). Einheiten, die vor der Umstellung als e.V. markiert
waren, haben den Schalter durch die Migration `finance/0011` eingeschaltet bekommen. Lesen mit `finance.view`, Erfassen und Ausstellen mit `finance.edit`.

## Ablauf

1. **Einstellungen:** begünstigte Zwecke, Finanzamt, Steuernummer, Art und Datum des
   Bescheids, beim Freistellungsbescheid der letzte Veranlagungszeitraum, Ort. Die Steuernummer
   wird aus „Rechnung & Zahlung“ vorgeschlagen.
2. **Zuwendungen erfassen** (Geld, Sache, auf Wunsch Mitgliedsbeitrag) oder **aus dem
   Kassenbuch übernehmen**: Einnahmen aus Kategorien mit dem Kennzeichen „Spenden“
   (Einrichtung › Kategorien). Name und Anschrift kommen aus dem Mitglied oder dem Zahler.
3. **Ausstellen:** eine Zuwendung ergibt eine Einzelbestätigung, mehrere eines Zuwendenden aus
   einem Kalenderjahr eine Sammelbestätigung mit Anlage. „Jahresende“ stellt für alle offenen
   Geldzuwendungen eines Jahres je Zuwendendem eine Bestätigung aus.
4. Das PDF wird als **Doppel** gespeichert (§ 50 Abs. 7 EStDV) und bleibt unverändert
   abrufbar. Nummern `ZB-<Jahr>-<laufend>` je Ausstellungsjahr.
5. **Storno** mit Grund: Die Bestätigung bleibt mit Vermerk in der Liste, die Zuwendungen werden
   wieder frei und lassen sich neu bestätigen.

## Regeln

- Ohne vollständige Angaben zum Bescheid wird nichts ausgestellt. Ein Freistellungsbescheid
  reicht 5 Jahre, eine Feststellung nach § 60a AO 3 Jahre (§ 63 Abs. 5 AO).
- Mitgliedsbeiträge nur, wenn eingeschaltet. Bei Vereinen, die z. B. Sport, Kultur,
  Heimatpflege oder Brauchtum fördern, sind sie nicht abziehbar (§ 10b Abs. 1 Satz 8 EStG).
- Sachzuwendungen nur einzeln (mit Bezeichnung und Herkunft), nie in einer Sammelbestätigung.
- Bestätigte Zuwendungen lassen sich nicht ändern oder löschen.

## Schnittstelle

`/api/orgs/<id>/finance/`: `donation-settings/` (GET, PUT; mit `problems` und `valid_until`),
`donations/` (Liste mit `?jahr=&offen=1&suche=`, Anlegen, Ändern, Löschen),
`donations/import/` (POST `year`), `donations/year-end/?jahr=` (Vorschau),
`donation-statements/` (Liste, POST `donations`, `signer_name`),
`donation-statements/year-end/` (POST `year`), `donation-statements/<id>/pdf/`,
`donation-statements/<id>/cancel/` (POST `reason`).
