# Sicherheitsprüfung Phase 1

Stand: 24.10.2026 · geprüft: Code der Meilensteine 0–6, Konfiguration des Testservers.

## Ergebnis in Kürze

Keine bekannten offenen Schwachstellen. Bei der Prüfung wurden drei Schwachstellen
gefunden und behoben (siehe unten). Einige Punkte sind für den Echtbetrieb noch zu
erledigen.

## Geprüft

### Rechte

- Jede API-Ansicht innerhalb einer Organisation prüft serverseitig, ob der Benutzer dort
  eine aktive Rolle hat (sonst **404** – fremde Organisationen sind nicht einmal sichtbar)
  und ob die Rolle die nötige Berechtigung hat (sonst 403).
- Berechtigungen kommen aus einem festen Katalog; Rollen können nur Berechtigungen ihrer
  Organisationsart erhalten.
- Der Plattformbereich verlangt die Berechtigung „Plattform verwalten“.
- Fremde Objekte (Rollen, Abteilungen, Mitgliedsarten, Zusatzfelder) lassen sich nicht
  über IDs einschleusen; dafür gibt es eigene Tests.

### Mandantentrennung

Doppelt gesichert:

1. Filter in jeder Abfrage der Anwendung.
2. **PostgreSQL Row-Level Security** auf allen mandantenbezogenen Tabellen. Die
   Anwendung arbeitet in der Rolle `hubiplan_app` ohne BYPASSRLS. Die Regeln werten die
   aktive Organisation, den Verbandsbereich und die Dachverbandsfreigabe aus.

24 Tests prüfen das direkt auf Datenbankebene, z. B.:
- Verein A sieht ohne jeden Filter keine Zeilen von Verein B.
- Schreiben in fremde Organisationen wird von PostgreSQL abgelehnt.
- Der Dachverband sieht Mitgliedsdaten nur mit Freigabe, nur seiner Vereine und kann
  bei „nur lesen“ nicht schreiben.
- Wechselanfragen sehen nur der alte und der neue Verein.
- Import, Export und Vereinswechsel funktionieren Ende zu Ende unter RLS.

Bewusste Ausnahme: Personen (Name, Vorname, Geburtsdatum) und Verbandsnummern sind auf
Datenbankebene im ganzen Dachverband lesbar, weil die Dublettenprüfung sie braucht. Die
Anwendung zeigt anderen Vereinen davon nur Name, Geburtsdatum, Verbandsnummer und –
falls freigegeben – die Vereine.

### OWASP-Grundlagen

| Thema | Umsetzung |
| --- | --- |
| Anmeldung | E-Mail/Passwort, optionale 2FA (TOTP, Wiederherstellungscodes), Ratenbegrenzung bei Fehlversuchen (allauth), Passwortregeln von Django |
| Sitzung | HttpOnly-, Secure- und SameSite-Cookies, 12 Stunden Laufzeit |
| CSRF | Django-CSRF-Schutz für alle schreibenden Aufrufe (getestet) |
| XSS | React maskiert Ausgaben; Content-Security-Policy ohne Inline-Skripte; keine SVG-Uploads |
| SQL-Injection | nur Django-ORM; die wenigen SQL-Bausteine (RLS) enthalten keine Benutzereingaben |
| Uploads | Logos nur PNG/JPG/WebP bis 2 MB (Pillow prüft die Datei); Importdateien bis 10 MB im privaten Speicher, nicht per Web erreichbar |
| Downloads | Exporte und Fehlerlisten nur über die API mit Berechtigungsprüfung |
| Transport | HTTPS mit Let's Encrypt, HTTP→HTTPS, HSTS (180 Tage) |
| Header | CSP, X-Content-Type-Options, X-Frame-Options DENY, Referrer-Policy, Permissions-Policy |
| Protokoll | Änderungen, Exporte und Dachverbandszugriffe werden protokolliert |
| Datensparsamkeit | Löschfrist mit automatischer Bereinigung inkl. Protokollinhalten |

### Abhängigkeiten

- `pip-audit`: keine bekannten Schwachstellen.
- `npm audit`: keine bekannten Schwachstellen.
- Versionen sind festgeschrieben; Dependabot meldet Updates wöchentlich.

### Mitgliederfotos (Ergänzung)

- Nur JPEG/PNG/WebP bis 10 MB und 40 Megapixel; Pillow prüft und kodiert neu, die
  EXIF-Ausrichtung wird angewendet, **alle Metadaten (auch GPS) werden entfernt**.
- Speicherung im privaten Speicher, Abruf nur über die API (Recht „Mitglieder lesen“),
  Ändern nur mit „Fotos verwalten“; RLS auf Fotos und Upload-Links.
- Persönlicher Upload-Link: zufälliges Token ohne Personenbezug, gespeichert nur als
  SHA-256-Hash, 14 Tage gültig, einmal nutzbar (atomar gesperrt), widerrufbar;
  die öffentliche Seite zeigt nur Vorname und Vereinslogo; Ratenbegrenzung je IP
  (geteilt über Redis); Einwilligung per Checkbox mit Datum.
- Widerruf der Einwilligung und Löschfrist entfernen Fotos und Links.

## Gefunden und behoben

1. **Zwei-Faktor-Anmeldung umgehbar über den Django-Admin.** Die Admin-Anmeldeseite
   fragte nur das Passwort ab. Jetzt leitet `/admin/login/` zur normalen Anmeldung
   (mit 2FA) weiter; der Admin nutzt danach dieselbe Sitzung.
2. **Formel-Injektion im Excel-Export.** Werte wie `=HYPERLINK(…)` aus Mitgliedsdaten
   wären in Excel als Formel ausgeführt worden. Solche Werte werden jetzt als Text
   geschrieben (auch in der Fehlerliste des Imports).
3. **Markup im PDF-Export.** Sonderzeichen wie `<` in Namen wurden als Formatierung
   gedeutet. Alle Werte werden jetzt maskiert.

Außerdem während der Entwicklung behoben: Der Vereinswechsel scheiterte unter RLS, weil
der alte Verein die Mitgliedsarten des neuen nicht lesen darf (Meilenstein 3).

## Offen für den Echtbetrieb

- **SMTP-Zugang** einrichten (bis dahin landen Mails als Dateien auf dem Server).
- **Zweiter Backup-Ort** (`BACKUP_REMOTE`) festlegen.
- **Startpasswörter**: Beim Anlegen neuer Konten wird zusätzlich zur Einladung ein
  Startpasswort einmalig angezeigt. Sobald E-Mails zuverlässig ankommen, sollte nur noch
  die Einladung genutzt werden.
- **2FA für Vorstände** verbindlich machen (heute optional).
- **Admin-Zugang** (`/admin/`) auf wenige Personen beschränken.
- Eigene **Domain** statt des Hostnamens des Anbieters.
- **Auftragsverarbeitungsvertrag** zwischen Betreiber und Vereinen (organisatorisch).
- Die API-Dokumentation (`/api/docs/`) ist für einige Endpunkte unvollständig (nur
  Dokumentation, keine Sicherheitsfrage).
