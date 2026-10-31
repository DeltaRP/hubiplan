# Verbund: Einheiten über mehrere HUBIplan-Instanzen

Konzept: `konzepte/dezentrale-einheiten.md` im Projektordner. Der Verbund ist eine
**Option**: Ohne Kopplung läuft alles wie bisher auf einer Instanz. Eingeschaltet wird
er unter Plattform › Einstellungen („Kopplung mit anderen Instanzen“).

## Ablauf

1. Plattform schaltet den Verbund ein (optional: Liste erlaubter Domains).
2. Vorstand der oberen Einheit (Dachverband, Recht „Verbund verwalten“) erzeugt unter
   Einstellungen › Verbund einen Kopplungscode (48 Stunden, einmalig) und gibt ihn auf
   anderem Weg weiter.
3. Vorstand der unteren Einheit (Verein ohne Dachverband auf seiner Instanz) gibt den
   Code ein, prüft Gegenseite und Fingerabdruck, wählt die Freigaben und koppelt.
4. Die obere Einheit bestätigt. Danach fließen die freigegebenen Pakete.

Die ferne Einheit erscheint als Platzhalter (`Organization.is_remote`): beim Dachverband
als Verein unter ihm, beim Verein als Dachverband ohne Umhängen (der Verbandsbereich
des Vereins bleibt unverändert). In Platzhaltern arbeitet niemand.

## Sicherheit

- Nur HTTPS, keine internen Adressen, keine Weiterleitungen.
- Jedes Paket ist zusätzlich Ende-zu-Ende verschlüsselt (X25519, HKDF-SHA256,
  ChaCha20-Poly1305) und jede Anfrage und Antwort unterschrieben (Ed25519, Zeit ±5 min,
  Einmalwert). Ein vorgeschalteter Webserver sieht nur Chiffretext.
- Der Schlüssel einer anderen Instanz wird beim Koppeln festgehalten; meldet sie später
  einen anderen, wird abgelehnt und eine Alarm-Mail geht hinaus. Ein Wechsel kommt nur als
  eigene Ankündigung (siehe Schlüsselwechsel).
- Schlüssel dieser Instanz: `PRIVATE_ROOT/peering/instance.json` (0600). Er ist Teil der
  verschlüsselten Sicherung; nach einer Rücksicherung bleibt die Instanz dieselbe.
  Wer ihn löscht, muss alle Kopplungen neu herstellen.
- Bei bekannten Absendern wird zuerst die Unterschrift geprüft, dann entschlüsselt.
  Grenzen: 600 Anfragen je Minute und IP, 300 je Minute und Absender-Instanz.
- Eingehende Pakete laufen mit Zeilensicherheit (RLS) im Bereich der Einheit, die sie
  betreffen: allgemein die lokale Einheit, Termine und namentliche Meldung im Platzhalter
  der fernen Einheit. Nur Wechsel oben und die Abfrage „anderswo aktiv?“ betreffen den
  ganzen Verbandsbereich und laufen ohne RLS. Die Tests schicken Pakete wie im
  Echtbetrieb in der Rolle `hubiplan_app` (`tests/verbund_netz.py`).
- Was von außen kommt, wird wie ein Upload behandelt: Anhänge weitergeleiteter
  Rundschreiben nur als PDF und mit den Grenzen des Hochladens, Antwortadresse nur, wenn
  sie zu den gemeldeten Adressen der fernen Einheit gehört; Satzung und Rechnungen der
  Gegenseite werden abgeschottet angezeigt (`Content-Security-Policy: sandbox`).
- Wartende Pakete werden schon beim Einreihen für die Empfängerin versiegelt
  (`Message.payload` enthält nur `{"sealed": …}`); diese Instanz kann sie selbst nicht mehr
  lesen. Was 14 Tage nicht zugestellt ist, wird verworfen; die Stände gehen beim nächsten
  Kontakt neu hinaus, der Vorstand bekommt eine Mail (höchstens eine am Tag).
- Höchststufe beim Empfänger: Angenommen wird je Paket nur die Stufe, die beim Koppeln
  angezeigt und bestätigt wurde (`options.accept`). Gibt die Gegenseite später mehr frei,
  lehnt diese Instanz das Paket mit 422 ab, zeigt dem Vorstand „möchte mehr senden“ und
  schickt eine Mail; nach „Annehmen“ kommt der Stand spätestens beim täglichen Abgleich.
  Weniger geht immer. Ältere Kopplungen behalten ihren bisherigen Stand als Zustimmung.
- Verbindungen zu Partnern und Push-Diensten lösen den Namen einmal auf, prüfen alle
  Adressen und verbinden genau die geprüfte (`core/safehttp.py`, kein DNS-Rebinding).
- Ein angekündigter Umzug der Gegenstelle wird erst nach Bestätigung übernommen (siehe
  Umzug). Konzept zur Härtung: `konzepte/haertung-austausch.md` im Projektordner.

## Betrieb

| Einstellung | Bedeutung |
|---|---|
| `PEERING_BASE_URL` | öffentliche Adresse dieser Instanz (Standard `FRONTEND_URL`) |
| `PEERING_KEY_FILE` | Schlüsseldatei (Standard siehe oben) |
| `PEERING_COUNTRY` | Serverstandort für die Selbstauskunft (Standard `DE`) |
| `PEERING_ALLOW_INSECURE` | nur Testaufbau: http und interne Adressen erlauben |

Hintergrundaufgaben (Celery Beat): `verbund-staende` (alle 5 Minuten geänderte Stände in
den Postausgang), `verbund-zustellen` (jede Minute fällige Pakete, Wiederholung nach 1, 5,
30 Minuten, dann stündlich), `verbund-abgleich` (täglich Prüfsummen vergleichen). Nach
24 Stunden Stau bekommen die Vorstände mit „Verbund verwalten“ eine Mail.

Schnittstelle (nur für andere Instanzen, alles POST außer der Selbstauskunft):

- `GET /api/peering/v1/instance/` Selbstauskunft
- `/api/peering/v1/pair/inspect/`, `/api/peering/v1/pair/request/` Koppeln mit Code
- `/api/peering/v1/inbox/` Pakete
- `/api/peering/v1/status/` Prüfsummen für den Abgleich
- `/api/peering/v1/keys/` Schlüsselwechsel einer Gegenstelle

## Schlüsselwechsel (Härtung H6)

Die Instanz wechselt ihre Schlüssel (Ed25519 und X25519) **automatisch nach einem Jahr**
und auf Knopfdruck unter Plattform › Einstellungen › Verbund (Bestätigungswort) oder mit
`manage.py verbund_schluessel_wechseln [--notfall]`. Jeder Wechsel löst eine Alarm-Mail aus.

- **Geplant:** Die alten Schlüssel bleiben 30 Tage gültig. Anfragen und Antworten tragen
  in dieser Zeit zwei Unterschriften (`X-Hubiplan-Signature` neu,
  `X-Hubiplan-Signature-2` alt), Pakete an den alten Verschlüsselungsschlüssel lassen sich
  noch öffnen. Jede Gegenstelle bekommt die Ankündigung `instance.keys` (Kopfzeile mit dem
  alten Schlüssel unterschrieben, Inhalt mit Nachweis des neuen) und übernimmt sie sofort;
  ihre Vorstände bekommen eine Hinweis-Mail, das Protokoll vermerkt den Wechsel. Wer die
  Ankündigung verpasst, bekommt sie täglich erneut. Nach 30 Tagen löscht der tägliche Lauf
  den alten privaten Schlüssel; mitgeschnittene Pakete aus der Zeit davor sind dann auch
  mit einem später gestohlenen Schlüssel nicht mehr lesbar.
- **Notfall** (Schlüssel vermutlich gestohlen): Pakete unterschreibt und öffnet nur noch
  der neue Schlüssel; der alte unterschreibt 30 Tage lang nur noch die Ankündigung. Die
  Gegenstelle übernimmt die neuen Schlüssel erst, wenn dort ein Vorstand den
  Fingerabdruck eingibt, den wir ihm auf anderem Weg nennen (unter Verbund bei der
  Kopplung; gilt für alle Kopplungen mit dieser Instanz). Bis dahin ruht der Austausch.
  Solange ein Notfallwechsel wartet, lehnt die Gegenstelle geplante Wechsel ab: Wer nur
  den alten Schlüssel gestohlen hat, kann sich nicht dazwischen drängen.
- Gehäuft ungültige Unterschriften einer bekannten Instanz (ab 5 in einer Stunde) lösen
  eine Alarm-Mail aus.
- Hintergrundaufgabe `verbund-schluessel` (täglich): alte Schlüssel löschen, nach einem
  Jahr wechseln, Ankündigung wiederholen.

## Pakete

Jedes Paket ist ein Stand: Die Heimat der Daten baut ihn, die Gegenseite ersetzt ihre
Kopie. Freigaben entscheidet die Heimat; ein entzogenes Paket kommt als leerer Stand an
und die Kopie wird gelöscht. Beim Lösen räumen beide Seiten ihre Kopien auf.

| Paket | Richtung | Inhalt |
|---|---|---|
| `unit` | beide | Name, Bezeichnungen, Gründungsjahr, Anschrift, Kontakt, Website, Logo |
| `events` | beide | nicht interne Termine der Einheit selbst nach „nach oben/unten freigeben“, ab 90 Tagen zurück, mit Serienabweichungen; nie Zu-/Absagen, Teilnehmer, Anhänge |
| `board` | beide | Rollen „auf der Webseite zeigen“ mit Funktionsadresse, Namen nur mit Einwilligung (wie auf der Webseite); Standard aus |
| `statute` | beide | aktuelle Satzung als PDF, nur wenn sie öffentlich abrufbar ist |
| `members` | nach oben | Stufe A: nur Anzahlen gemeldeter Mitgliedschaften nach aktiv/passiv und Geburtsmonat, keine Namen. Stufe B: namentlich minimal (siehe unten); Standard aus |
| `circulars` | nach unten | Rundschreiben des Dachverbands an „Mitglieder“ zur Weitergabe (siehe unten); Standard an |
| `invoices` | nach unten | Rechnungen der Einheit darüber an die ferne Einheit (Vorgänge statt Stand, siehe unten); Standard an |

Übermittelte Termine liegen als Termine des Platzhalters im Kalender (Feld
`Event.remote_uid`); RLS erlaubt das Lesen nur bei aktiver Kopplung nach oben
(`core/0022`). Vorstand und Satzung stehen auf der Seite Verbund bei der Kopplung.

### Mitgliederzahlen und Rechnungen (Schritt 3)

Gibt ein Verein `members` frei, rechnet die Beitragsrechnung des Dachverbands
(`billing.services.reported_counts`) für seinen Platzhalter mit diesen Zahlen; die
Altersstufe ergibt sich aus dem Geburtsmonat zum Beginn des Geschäftsjahrs.
Ehrungen des Dachverbands spielen dabei keine Rolle, weil der Dachverband die
Personen nicht kennt (erst mit der namentlichen Meldung in Schritt 4).

Rechnungen sind Vorgänge in einer festen Reihenfolge, kein Stand:

- `invoice.issue`: Festschreiben einer Rechnung an einen fernen Verein. Inhalt:
  Nummer, Betreff, Datum, Fälligkeit, Betrag, Positionen, Bankverbindung des Ausstellers
  und das PDF (bis 8 MB).
- `invoice.cancel`: Storno.
- `invoice.status`: Zahlungseingang beim Aussteller (bezahlter Betrag, ausgeglichen ja/nein).
- `invoice.paid` (nach oben): Der Verein meldet „bezahlt am …“. Dabei kann er die
  Ausgabe gleich in der eigenen Kasse buchen, mit dem PDF als Beleg (braucht das
  Recht „Kasse führen“). Maßgeblich für den Ausgleich bleibt der Zahlungseingang
  beim Aussteller.

Beide Seiten halten die Rechnung in `RemoteInvoice` (Aussteller mit Verweis auf die
eigene Rechnung). Rechnungen bleiben beim Lösen der Kopplung erhalten.

### Namentliche Meldung (Schritt 4)

Stufe B des Pakets `members` schickt je Mitgliedschaft mit einer gemeldeten Art nur
Name, Vorname, Geburtsdatum, Verbandsnummer, gemeldete Mitgliedsarten mit Zeiträumen,
Ein- und Austritte (Grund nur „Wechsel“ oder „sonstiges“) und ob der Verein die Daten
nach Ablauf der Löschfrist gelöscht hat. Nie Anschrift, E-Mail, Telefon, Bankdaten,
Fotos, Zusatzfelder, Rollen oder Züge. Vor dem Einschalten zeigt die Oberfläche eine
Prüfliste (Meldepflicht in der Satzung, Datenschutzhinweise).

Beim Dachverband werden daraus Mitgliedschaften im Platzhalter des Vereins
(`peering.register`, Verbindung über `RemoteMember`). Damit gelten Verbandsnummer,
„nur eine aktive Mitgliedschaft“, Mitgliedsdauer, Jubiläen und die Beitragsrechnung
wie bei Vereinen derselben Instanz.

- **Verbandsnummer:** Der Dachverband vergibt sie wie bisher und schickt sie mit
  `register.numbers` zurück. Beim Verein steht sie in der Mitgliedsakte.
- **Zuordnung:** Bringt die Zeile eine Verbandsnummer mit, gilt die Person mit dieser
  Nummer. Gibt es sonst schon eine Person mit gleichem Namen und Geburtsdatum, entsteht
  ein **Klärfall**: Der Dachverband entscheidet unter Einstellungen › Verbund „dieselbe
  Person“ oder „andere Person“. Bis dahin wird die Zeile nicht übernommen.
- **Doppelt aktiv:** Ist eine gemeldete aktive Person schon in einer anderen Einheit
  aktiv, sieht der Dachverband einen Hinweis.
- **Abfrage vor der Aufnahme (P7):** Nimmt ein Verein mit namentlicher Meldung jemanden
  mit aktiver Art auf, fragt seine Instanz beim Dachverband nach
  (`/api/peering/v1/query/`, nur Name, Vorname, Geburtsdatum, Verbandsnummer). Die
  Antwort nennt nur die andere Einheit. Ist der Dachverband nicht erreichbar, wird die
  Aufnahme nicht blockiert.
- **Berichtigung und Löschung (P5, P14):** Änderungen kommen mit dem nächsten Stand.
  Fällt jemand aus der Meldung, wird die Freigabe entzogen oder die Kopplung gelöst,
  enden offene Zeiträume beim Dachverband, und es bleibt nur das Minimum (wie nach der
  Löschfrist). Löscht der Verein nach Ablauf der Löschfrist, kürzt auch der
  Dachverband auf das Minimum.

### Wechsel und Korrekturvorschläge (Schritt 4b)

Wechsel zwischen Vereinen laufen über den Dachverband wie auf einer Instanz
(`members.TransferRequest`). Liegt ein Verein auf einer anderen Instanz, gehen Anfrage
und Entscheidung als Pakete (`peering.transfers`, Verbindung über `RemoteTransfer`):

- **Bisheriger Verein fern:** Die Wechselanfrage eines Vereins beim Dachverband geht als
  `transfer.request` an den fernen Verein. Dort steht sie unter Einstellungen › Verbund:
  Austritt bestätigen, nicht aktive Art wählen oder ablehnen. Der Verein schickt erst
  den neuen Stand der Meldung, dann `transfer.decision`; danach nimmt der neue Verein auf.
- **Neuer Verein fern:** Der ferne Verein stellt die Anfrage unter Einstellungen ›
  Verbund (Name, Vorname, Geburtsdatum, Art, Eintritt). Ist die Person beim Dachverband
  nirgends aktiv, darf er sofort aufnehmen. Sonst entscheidet der bisherige Verein wie
  gewohnt; nach der Zustimmung nimmt der ferne Verein auf und bekommt die
  Verbandsnummer mit, damit der Dachverband die Person im nächsten Stand wiedererkennt.
- **Zurückziehen** (`transfer.cancel`) erreicht den fernen bisherigen Verein ebenfalls.

Personen ferner Vereine kann der Dachverband nicht selbst ändern. In der
Mitgliederliste des Dachverbands steht stattdessen „Korrektur vorschlagen“
(`register.suggest`, nur Name, Vorname, Geburtsdatum). Beim Verein erscheint der
Vorschlag als Änderungsmeldung und wird übernommen oder abgelehnt; die Berichtigung
kommt dann mit dem nächsten Stand zurück.

### Rundschreiben nach unten (Schritt 5)

Schickt der Dachverband ein Rundschreiben an „Mitglieder“, bekommt er für Vereine auf
anderen Instanzen keine Adressen: Diese Vereine fehlen in seiner Empfängerliste. Stattdessen
geht `circular.forward` mit Betreff, Text (Platzhalter bleiben erhalten), Anhängen (bis
10 MB), Antwortadresse und „nur gemeldete Mitglieder“ an jeden gekoppelten Verein, der in
der Auswahl liegt und das Paket `circulars` vom Dachverband freigegeben bekommt.

Beim Verein entsteht ein eigenes Rundschreiben „Im Auftrag von …“. Standard: Es liegt als
Entwurf bereit, der Vorstand bekommt eine Mail, prüft, wählt Empfänger und versendet. Mit
„automatisch weitergeben“ (Einstellungen › Verbund) geht es sofort an alle passenden
Mitglieder. Zurück kommt nur `circular.report` mit der Zahl versandter und
fehlgeschlagener Mails und der Briefe.


## Umzug auf eine andere Instanz (Schritt 6)

Eine Einheit kann mit ihren Kopplungen auf eine andere HUBIplan-Instanz umziehen, ohne
dass die Gegenstellen neu koppeln müssen:

1. **Exportieren** (Datenübernahme). Die Datei enthält die offenen Kopplungen der Einheit:
   Gegenstelle mit öffentlichen Schlüsseln, Freigaben, Optionen und beim Verein die
   Verbandsnummern je Mitgliedschaft. Schlüssel dieser Instanz stehen nicht darin.
2. **Einlesen** auf der neuen Instanz (Plattformverwaltung). Die feste Kennung der Einheit
   bleibt, die Kopplungen entstehen dort neu. Ist die Gegenstelle dort schon mit anderen
   Schlüsseln bekannt, wird die Kopplung übergangen und als Hinweis gemeldet.
3. **Umzug melden** unter Einstellungen › Verbund › „Umzug auf eine andere Instanz“: Adresse
   der neuen Instanz eintragen, ihren Fingerabdruck auf anderem Weg vergleichen, melden.
   Die alte Instanz schickt `unit.moved`, unterschrieben mit ihrem Schlüssel. Die
   Gegenstelle holt die Selbstauskunft der neuen Instanz und prüft die angekündigten
   Schlüssel. Sie stellt aber nichts um: Die Kopplung steht auf „Umzug angekündigt“, es
   geht nichts hinaus, ihre Vorstände bekommen eine Mail, der Betreiber eine Alarm-Mail.
   Ein Vorstand der Gegenstelle gibt dort den Fingerabdruck der neuen Instanz ein, den
   die umziehende Einheit auf anderem Weg mitteilt; erst dann koppelt sie sich um und
   schickt ihre Stände neu. „Ablehnen“ löst die Kopplung. So kann eine gehackte alte
   Instanz die Daten nicht still auf eine eigene umlenken.
4. Auf der alten Instanz stehen die Kopplungen danach als „umgezogen“. Sie nimmt keine
   Pakete mehr an (410 mit der neuen Adresse); die Einheit kann dort gelöscht werden.

Der Dachverband erkennt die gemeldeten Personen nach dem Umzug an der Verbandsnummer
wieder. Die alte Zuordnung wird dabei still abgelöst, Zeiträume und Daten bleiben.

## Anmelden über eine gekoppelte Instanz (Schritt 7)

Wer Zugänge auf mehreren gekoppelten Instanzen hat, kann sich mit dem Zugang seiner
Heimat-Instanz auch auf den anderen anmelden. Rechte gibt das keine: Jede Instanz vergibt
ihre Rollen weiter selbst, und es gibt keine gemeinsame Oberfläche.

- **Einschalten:** Plattformverwaltung › Verbund › „Anmelden mit dem Zugang einer gekoppelten
  Instanz erlauben“ (Standard aus) auf der Instanz, bei der man sich so anmelden will. Es
  zählen nur Instanzen mit aktiver (nicht pausierter) Kopplung.
- **Verknüpfen:** einmal unter Mein Konto › App & andere Instanzen › „Anmelden über andere Instanzen“. Man muss dafür
  hier angemeldet sein (mit 2FA, falls eingerichtet) und auf der anderen Instanz die
  Verknüpfung bestätigen. Ohne Verknüpfung entsteht kein Konto und keine Anmeldung.
- **Anmelden:** Auf der Anmeldeseite stehen die gekoppelten Instanzen („Anmelden mit …“). Auf
  der Heimat-Instanz stehen verknüpfte Instanzen in der Einheitenauswahl („… öffnen“); ein
  Klick führt dorthin, schon angemeldet.
- **Sicherheit:** Die Heimat-Instanz stellt eine Anmeldebestätigung aus (Version 2: Kennung,
  Name, E-Mail, Anmeldeweg dieser Sitzung `amr` wie `pwd`/`mfa`/`link`, Anmeldezeit
  `auth_time`, Zufallswert der Sitzung). Sie ist für die Ziel-Instanz verschlüsselt
  (X25519/ChaCha20-Poly1305), mit dem beim Koppeln gespeicherten Schlüssel unterschrieben
  (Ed25519), zwei Minuten gültig und nur einmal nutzbar. Der Browser bringt sie im Teil
  nach `#` (kommt in keinem Serverprotokoll an) zur Ziel-Instanz; die prüft sie gegen den
  Zufallswert ihrer eigenen Sitzung, damit niemand einen fremden Browser anmeldet.
- **Nie schwächer als hier:** Nutzt das Konto hier 2FA, muss die Sitzung auf der
  Heimat-Instanz selbst mit 2FA angemeldet worden sein (nicht nur: Konto hat 2FA). Zugänge
  der Plattformverwaltung melden sich nie über eine andere Instanz an und stellen keine
  Bestätigungen aus.
- **Frisch und ohne Ketten:** Die Heimat-Instanz stellt nur aus einer Anmeldung aus, die
  höchstens 12 Stunden alt ist (2FA ebenso); sonst fragt sie Passwort und ggf. Code neu ab.
  Sitzungen, die selbst über eine andere Instanz entstanden sind, stellen keine Bestätigung
  aus. Die Ziel-Instanz lehnt alte Bestätigungen (Version 1, ohne Anmeldezeit) ab.
- **Konten mit Rollen** (Vorstand, Kasse, Prüfer …) geben nach der Bestätigung zusätzlich
  den eigenen Code dieser Instanz ein; ohne eigene 2FA ist für sie die Anmeldung über eine
  andere Instanz gesperrt.
- Sitzungen aus dieser Anmeldung laufen nach 12 Stunden ab. Bei der ersten Anmeldung aus
  einem Browser bekommt das Konto eine Hinweis-Mail. Eingelöste Bestätigungen stehen
  zusätzlich in der Datenbank (`UsedAssertion`), damit ein Neustart des Caches keine
  zweite Einlösung erlaubt.
- Schnittstelle: `/api/peering/sso/` (`choices`, `start`, `describe`, `issue`, `finish`,
  `account`, `links/<id>`, `accounts/<id>`); Seiten `/verbund/start`, `/verbund/anmelden`,
  `/verbund/angemeldet`.

## Untereinheit auf eigener Instanz (Schritt 8)

Eine Untereinheit (z. B. ein Zug) kann eine eigene HUBIplan-Instanz betreiben und bleibt über
den Verbund mit ihrem Verein verbunden. Konzept: `konzepte/ausgliedern.md` im Projektordner.

**8a: Verein als obere Seite.** Neben einem Dachverband kann jetzt auch ein Verein einen
Kopplungscode erzeugen (Einstellungen › Verbund › „Ferne Einheit aufnehmen“).

- Der Code nennt die Art der oberen Seite (`"k": "club"`); die Antworten auf Vorschau und
  Anfrage nennen sie noch einmal (`kind`). Passen beide nicht zusammen, bricht die Kopplung ab.
  Codes eines Dachverbands bleiben unverändert.
- Beim Verein entsteht als Platzhalter eine **Untereinheit** in seinem Datenbereich
  (`is_remote`). Sie steht in der Liste der Untereinheiten mit „andere Instanz“, lässt sich
  aber weder bearbeiten noch löschen, und Mitglieder lassen sich ihr nicht zuordnen.
- Zwischen Verein und ferner Untereinheit fließen nur Stammdaten, Termine, Vorstand und
  Satzung (`Packet.under_club`). Mitgliedermeldung, Rechnungen und Rundschreiben gibt es
  hier nicht; den Abgleich der Mitglieder bringt Schritt 8d.
- Termine der fernen Untereinheit erscheinen im Verein als Termine dieser Untereinheit und
  sind dort nicht bearbeitbar (das gilt für alle Termine aus dem Verbund).

**8b: Untereinheit wird auf der Plattform eigene Einheit.** Die Plattformverwaltung kann den
Export einer Untereinheit einlesen (Plattform › Datenübernahme). Daraus entsteht eine oberste
Einheit, die ihre Mitglieder selbst führt.

- Mitgliedsnummern, Zeiträume, Mitgliedsarten, Fotos, Satzung und Ablage bleiben.
- Rollen der Untereinheit werden Rollen der Einheit (Rechte nur, soweit es sie dort gibt).
  Ihre Inhaber bleiben als Ämter ohne Konto; Zugänge entstehen neu per Einladung.
- Jede Mitgliedschaft merkt sich ihre Kennung beim abgebenden Verein (`origin_ref`). Darüber
  ordnet der Verein den späteren Abgleich zu (Schritt 8d), ohne dass Personen doppelt
  entstehen. Die Kennung zieht beim Umzug mit.
- Die Anschrift kommt aus der Angabe beim Import, sonst vom abgebenden Verein (der Export einer
  Untereinheit enthält dafür jetzt dessen Anschrift).

**8c: Ausgliedern-Assistent.** Einstellungen › Verbund › „Untereinheit auf eigene Instanz
ausgliedern“ (nur mit den Rechten „Verbund verwalten“ und „vollständiger Export“, also der
Vereinsvorstand).

1. Untereinheit (ohne eigene Untereinheiten), Weg und Stichtag wählen, Prüfliste bestätigen:
   - Weg A „bleiben Vereinsmitglieder“: Datenschutzhinweise nennen die neue Instanz,
     Auftragsverarbeitung ist geregelt.
   - Weg B „werden Mitglieder der Untereinheit“: Wechsel nach der Satzung beschlossen,
     Übergabe der Daten geregelt.
2. Es entstehen ein Kopplungscode (30 Tage gültig, an diese Untereinheit gebunden) und ein
   Export der Untereinheit. Der Export enthält Weg, Stichtag und Code; bei eigenem Arbeitsbereich
   auch Kasse und Rechnungen (`workspace_tables`). Der Code steht danach nur in der Datei, die
   Datenbank behält nur seine Prüfsumme (`SpinOff`).
3. Die Plattform der neuen Instanz liest den Export ein (8b) und fragt mit dem Code gleich die
   Kopplung unter den Verein an. Klappt das nicht, koppelt der Vorstand dort von Hand.
4. Bestätigt der Verein, wird die Untereinheit selbst zum Platzhalter (`is_remote`). Ihre alten
   Termine bleiben. Lehnt er ab oder wird die Ausgliederung abgebrochen, bleibt die
   Untereinheit, wie sie war.

**8d: Fern geführte Mitgliedschaften (Weg A).** Bestätigt der Verein die Kopplung einer
Ausgliederung mit „Mitglieder bleiben Vereinsmitglieder“, werden die heutigen Mitglieder der
Untereinheit beim Verein *fern geführt* (`Membership.managed_by`).

- Name, Geburtsdatum, Geschlecht und Kontakt pflegt die Untereinheit auf ihrer Instanz und
  schickt sie mit dem Paket „Mitglieder der ausgegliederten Untereinheit“ (`unit_members`, nur
  zwischen Verein und ferner Untereinheit). Beim Verein sind diese Felder gesperrt; die Akte
  bietet „Korrektur vorschlagen“, das bei der Untereinheit als Änderungsmeldung ankommt.
- Mitgliedschaft, Zeiträume, Mitgliedsart, Mitgliedsnummer und Beitrag bleiben Sache des Vereins.
- Zuordnung über die Kennungen (`origin_ref` → Mitgliedschaft im Verein), nie über Namen.
- Neue Mitglieder der Untereinheit werden beim Verein neue, fern geführte Mitgliedschaften
  (Mitgliedsart gleichen Namens, sonst die erste aktive Art; Prüfung „nirgends aktiv“). Gibt es
  schon eine Person mit gleichem Namen und Geburtsdatum, entsteht ein Klärfall (dieselbe Person
  / andere Person) unter Verbund › Kopplung; zusammengeführt wird nie automatisch.
- Wer die Untereinheit verlässt oder nicht mehr im Stand steht, bleibt Vereinsmitglied: Die
  Zuordnung zur Untereinheit endet, der Verein pflegt die Person wieder selbst. Beim Lösen der
  Kopplung gilt das für alle.

**8e: Sammelaustritt zum Stichtag (Weg B).** Nach der Bestätigung zeigt die Ausgliederung
„Sammelaustritt vorbereiten“ (Recht „Mitglieder bearbeiten“): Vorschau aller Mitglieder der
Untereinheit, Häkchen für die, die bleiben (vorbelegt bei Mitgliedern weiterer Untereinheiten).
Danach treten die übrigen zum Stichtag mit Grund „Wechsel“ aus; Art, Zuordnungen und Rollen enden
mit, die Zeiträume bleiben, die Löschfrist läuft wie bei jedem Austritt. Einmalig, mit Protokoll.
