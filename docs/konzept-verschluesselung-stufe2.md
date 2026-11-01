# Verschlüsselung Stufe 2: Name und Geburtsdatum

Stand: 01.11.2026, Code-Stand main `208b9ce`. Konzept, noch nicht umgesetzt.

Stufe 1 (PR #7, #9, #10) verschlüsselt private Dateien, Kontaktdaten, SEPA-Mandate,
Bank-IBANs, Zusatzfelder, Änderungsprotokoll und Postausgang mit dem Schlüssel des
Vereins (`core/crypto.py`, `core/encfields.py`). Name, Vorname und Geburtsdatum der
`Person` stehen weiter im Klartext, weil die Datenbank danach sucht, sortiert und
Dubletten findet. Dieses Dokument beschreibt, wie auch diese drei Felder verschlüsselt
werden können, und schätzt den Aufwand.

## Was es bringt und was nicht

- Schützt gegen den Diebstahl der **Datenbank allein** (Dump, Backup ohne
  Hauptschlüssel, Zugriff auf den Postgres-Container). Dann sind keine Personen mehr
  benennbar; zusammen mit Stufe 1 bleibt nur noch Pseudonymes (Mitgliedsnummern,
  Zeiträume, Beträge, Geschlecht).
- Schützt **nicht** gegen jemanden, der die laufende Anwendung samt Hauptschlüssel
  übernimmt. Der sieht die Namen ohnehin.
- Name und Geburtsdatum sind weniger heikel als IBAN oder Anschrift. Der Nutzen ist
  deshalb kleiner als bei Stufe 1, der Aufwand größer.

## Bestand: wo die Datenbank heute mit Name und Geburtsdatum arbeitet

Nur Stellen, an denen die **Datenbank** sucht, vergleicht oder sortiert. Lesen und
Schreiben am Objekt (`person.last_name`) bleibt unverändert, das erledigt das
verschlüsselte Feld.

**Standardsortierung:** `members/models.py:59`, `Person.Meta.ordering =
["last_name", "first_name"]`, und zwei Indizes (Zeilen 61–62). Wichtig: `order_by` auf
einem verschlüsselten Feld bricht heute **nicht** ab, sondern sortiert still nach
Chiffrat. Diese Lücke muss vor der Umstellung geschlossen werden (siehe unten).

**Teilsuche (`icontains`), 5 Stellen:**

| Datei | Zweck |
|---|---|
| `members/views.py:205` | Suche in der Mitgliederliste |
| `members/federation_views.py:72` | Suche in der Verbandsansicht |
| `billing/views.py:1347` | Suche in der Abrechnung |
| `competitions/views.py:646` | Personenauswahl bei Wettbewerben |
| `honors/views.py:472` | Personenauswahl bei Ehrungen |

**Sortierung (`order_by`), 13 Stellen:**

| Datei | Zweck |
|---|---|
| `members/views.py:283–294` | Mitgliederliste, auch nach Geburtsdatum, mit Seitenweise-Anzeige (50 je Seite) |
| `members/federation_views.py:99–103` | Verbandsansicht |
| `billing/services.py:253`, `billing/units.py:38` | Abrechnungslisten |
| `cards/views.py:204` | Ausweise |
| `circulars/recipients.py:276, 311, 418` | Empfängerlisten der Rundschreiben |
| `competitions/views.py:649`, `honors/views.py:474` | Auswahllisten (je 10–12 Treffer) |
| `events/rsvp.py:53` | Zusagen zu Veranstaltungen |
| `peering/spinoff.py:214` | Abspaltung in eine eigene Instanz |
| `portal/views.py:621` | Ämterliste im Portal |

**Exakter Vergleich / Dubletten, 5 Stellen:**

| Datei | Zweck |
|---|---|
| `members/services.py:243–247` | `find_duplicates`: gleiches Geburtsdatum (oder nur Geburtsjahr) **und** Name **oder** Vorname gleich (ohne Groß/klein) |
| `datatransfer/load.py:646–648` | Einspielen einer Datenübernahme |
| `peering/packet_unit_members.py:282–284` | Mitglieder einer Untereinheit aus dem Verbund |
| `peering/register.py:287–289, 632–634` | Verbandsregister im Verbund |

**Alter und Jahr, 2 Stellen:** `circulars/recipients.py:227–229` (Rundschreiben
nach Mindest-/Höchstalter, `birth_date__lte/__gt`), `members/services.py:244`
(`birth_date__year`).

**Unkritisch:** `values_list(..., "person__birth_date")` in `members/statistics.py` und
`billing/services.py:254`. Django ruft dabei `from_db_value` auf, das entschlüsselt.
Sortierungen in Python (`members/birthdays.py:76`, `members/duration.py:266`)
laufen schon heute im Speicher.

`circulars/models.py:187` (Empfänger eines Rundschreibens) und `accounts`
(`user__last_name`) haben eigene Namensfelder. Sie gehören nicht zur `Person` und sind
hier nicht berücksichtigt. Die Empfängerkopie im Rundschreiben wäre ein eigener,
kleiner Folgeschritt.

## Entwurf

### 1. Schlüssel

`Person` gehört dem Verbandsbereich (`scope`), nicht einem Verein, damit die
Dublettenprüfung dieselbe Person in mehreren Vereinen findet. `encfields` kann das
schon: Hat ein Modell weder `encryption_org_id()` noch `organization_id`, wird
`scope_id` als Inhaber genommen (wie bei `ContactDetails`). Es ist also **kein neuer
Schlüsseltyp** nötig, `Person` bekommt den Schlüssel des Verbandsbereichs.

### 2. Suchmarken für exakte Treffer (Blind Index)

Neue Spalten an `Person`, gefüllt beim Speichern:

- `last_name_mark`, `first_name_mark`: HMAC-SHA256 des normalisierten Werts
  (`strip`, `casefold`, Unicode NFC), gekürzt auf 16 Byte, Base64.
- `birth_mark`: HMAC des Geburtsdatums (ISO-Format).
- `birth_year_mark`: HMAC des Geburtsjahrs (für `birth_year_only` und die Löschfrist).

Der HMAC-Schlüssel wird aus dem Schlüssel des Verbandsbereichs abgeleitet (HKDF,
eigener Zweck „person-mark“), nicht der Datenschlüssel selbst. Gleiche Werte im
selben Verbandsbereich ergeben gleiche Marken, in anderen Bereichen andere.

`find_duplicates` und die vier anderen Dublettenstellen fragen dann
`birth_mark=… OR (birth_year_only AND birth_year_mark=…)` und
`last_name_mark=… OR first_name_mark=…`. Das ist genau die heutige Logik, nur über
Marken. Indizes: `(scope, birth_mark)`, `(scope, birth_year_mark)`.

Grenze: Marken verraten, **dass** zwei Personen gleich heißen oder am selben Tag
geboren sind, aber nicht wie. Bei sehr häufigen Namen und bekanntem Verein kann man
durch Häufigkeit raten. Das ist für Name/Geburtsdatum vertretbar.

### 3. Teilsuche und Sortierung in HUBIplan

Neues Modul `members/personsearch.py` mit einer zentralen Funktion, z. B.:

```python
def persons_sorted(qs, *, search="", sort=("last_name", "first_name"), limit=None)
```

Sie lädt die Kandidaten (`pk`, Name, Vorname, Geburtsdatum; entschlüsselt durch das
Feld), filtert die Teilsuche im Speicher (`casefold`, „enthält“), sortiert so wie
heute Postgres (Umlaute, Groß/klein; per Test festgehalten) und gibt eine Liste von
IDs in Reihenfolge zurück.
Die Aufrufer holen die Objekte danach mit `in_bulk` bzw. sortieren nach der
ID-Reihenfolge.

- **Seitenweise Anzeige** (Mitgliederliste, 50 je Seite): erst alle IDs sortieren,
  dann die Seite herausschneiden, dann nur diese Objekte laden. Der DRF-Paginator
  bekommt dafür eine Liste statt eines QuerySets.
- **Größe:** Ein Verein hat einige hundert Personen (Dogado: 128 Mitgliedschaften,
  Testserver: 186), das ist im Speicher unkritisch. Ein großer Dachverband mit vielen
  tausend Personen (Verbandsansicht) braucht einen Zwischenspeicher je Prozess
  (Schlüssel: Verbandsbereich und letzter `updated_at`), der bei Änderungen verfällt.
  Erst messen, dann bauen.
- **Auswahllisten** (Wettbewerbe, Ehrungen, 10–12 Treffer): dieselbe Funktion mit
  `limit`.

### 4. Alter

Rundschreiben nach Alter: Kandidaten laden und das Alter in Python berechnen. Die
Mengen sind klein. Alternative: Geburtsjahr im Klartext lassen. Das Jahr allein ist
wenig heikel und hält Altersgruppen und Statistik billig. **Entscheidung offen**,
Empfehlung: in Python rechnen, alles verschlüsseln.

### 5. Felder

- `last_name`, `first_name` → `EncryptedCharField` (gibt es).
- `birth_date` → neues `EncryptedDateField` (Speicherung als Text `enc1:…`, Spalte
  wird von `date` zu `varchar`; die Migration wandelt um).
- `Meta.ordering` und die zwei Indizes entfallen.
- **Lücke schließen:** `order_by` auf einem verschlüsselten Feld muss laut abbrechen,
  wie heute schon `filter`. Weg: ein Systemcheck plus ein Test, der alle `order_by`-
  und `ordering`-Ausdrücke im Code gegen die verschlüsselten Felder prüft, und eine
  `resolve_expression`-Sperre im Feld, soweit Django das erlaubt. Ohne das sortiert
  eine übersehene Stelle still falsch.

### 6. Verbund (peering)

Pakete an andere Instanzen enthalten Name und Geburtsdatum im Klartext innerhalb des
ohnehin verschlüsselten Verbund-Kanals (`peering/crypto.py`). Das bleibt so: lesen am
Objekt (entschlüsselt), senden, dort mit dem eigenen Schlüssel speichern. Die
Dublettensuche beim Empfang (`register.py`, `packet_unit_members.py`) läuft über die
Marken der Empfänger-Instanz. Kein Protokollwechsel nötig.

### 7. Ausrollen und Rückweg

Wie Stufe 1: Backup, ausrollen, `daten_verschluesseln --probe`, dann echt (füllt auch
die Marken), `--probe` muss 0 zeigen, Health. Rückweg: `daten_verschluesseln
--entschluesseln` vor `deploy/zurueck.sh`; die Migration für `birth_date` muss
rückwärts wieder `date` herstellen können.

## Umsetzung in Schritten (je ein PR)

| Schritt | Inhalt | Verhalten ändert sich? | Größe (geschätzt) |
|---|---|---|---|
| a) | `members/personsearch.py`; alle 5 Teilsuchen, 13 Sortierungen und die 2 Altersfilter darauf umstellen; Mitgliederliste blättert über die ID-Liste; `Meta.ordering` bleibt vorerst | nein (gleiche Treffer, gleiche Reihenfolge) | groß: ~15 Dateien, ~400–600 Zeilen Code, ~300 Zeilen Tests |
| b) | Marken-Spalten, Ableitung des HMAC-Schlüssels, Füllen beim Speichern und per Befehl; die 5 Dublettenstellen auf Marken umstellen | nein | mittel: ~8 Dateien, ~250 Zeilen + Tests |
| c) | Sperre für `order_by` auf verschlüsselten Feldern; `EncryptedDateField`; Felder umstellen; `Meta.ordering`/Indizes entfernen; Migration | ja (Daten verschlüsselt) | mittel: ~6 Dateien, ~250 Zeilen + Tests |
| d) | Testserver, dann Dogado: Backup, ausrollen, Bestand verschlüsseln | – | Betrieb, ~30 Minuten je Server |

### Schritt a) genauer

Schritt a) ist der größte Teil und lässt sich ohne jedes Risiko für die Daten bauen
und ausrollen, weil noch nichts verschlüsselt wird. Er besteht aus:

1. `personsearch.py` mit Suche, Sortierung (inkl. Umlaute und Groß/klein wie bisher),
   Begrenzung und Seitenschnitt. Tests gegen die heutige Postgres-Reihenfolge mit
   Umlauten, Bindestrichen, Leerzeichen und „von/van“.
2. Mitgliederliste (`members/views.py`) mit allen Sortierungen inkl. Geburtsdatum und
   Seitenweise-Anzeige. Das ist die aufwendigste Stelle, weil Filter (Status, Art,
   Abteilung, Geschlecht) weiter in der Datenbank laufen und nur Suche und Sortierung
   in Python.
3. Verbandsansicht, Abrechnung (2), Ausweise, Rundschreiben (3 + Altersfilter),
   Wettbewerbe, Ehrungen, Zusagen, Abspaltung, Portal: je eine kleine Umstellung.
4. Ein Test, der sicherstellt, dass im Code kein `order_by`/`icontains` mehr auf
   `last_name`, `first_name`, `birth_date` der Person steht (Grep-Test), damit
   Schritt c) nichts übersieht.
5. Messung: Mitgliederliste mit 5 000 erfundenen Personen, Ziel unter 300 ms
   Serverzeit.

## Offene Entscheidungen

1. Geburtsjahr im Klartext lassen (billige Altersfilter, Statistik) oder alles
   verschlüsseln (Empfehlung)?
2. Lohnt der Aufwand gegenüber dem kleineren Nutzen (siehe oben)? Alternative:
   nur das volle Geburtsdatum verschlüsseln, Name im Klartext lassen. Das spart die
   Schritte für Suche und Sortierung nach Namen fast ganz, schützt aber weniger.
3. Empfängerkopie im Rundschreiben (`circulars.Recipient`) gleich mit verschlüsseln?
