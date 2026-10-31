# Schnittstelle für die HUBIplan-App

Die Android-App (Repository `hubiplan-android`) spricht nur mit der HUBIplan-Instanz
des Mitglieds. Konzept: `konzepte/android-app.md` im Projektordner.

## Anmelden (Schritt A1)

Die App bekommt einen **Geräteschlüssel** (`hpd_…`) und schickt ihn als
`Authorization: Bearer hpd_…`. In der Datenbank steht nur die SHA-256-Prüfsumme.

Wege zum Schlüssel:

| Weg | Ablauf |
|---|---|
| QR-Code | Im Browser unter „Mein Konto › App & andere Instanzen › App auf dem Telefon“ `POST /api/app/v1/pairing/` (nur mit Sitzung). Der QR-Code enthält `https://<Instanz>/app/verbinden#code=<Code>`, 10 Minuten gültig, einmal nutzbar. Die App schickt `POST /api/app/v1/pair/` mit `{"code", "name", "platform", "app_version"}`. Der Browser fragt `GET /api/app/v1/pairing/<id>/` alle 3 Sekunden ab und zeigt nach dem Scannen „Verbunden: <Gerät>“. Die App zeigt vor dem Verbinden die Adresse der Instanz und fragt nach. |
| Anmeldelink | Wie oben, aber `{"login_link": "<Token aus /anmelden/link/<Token>>"}`. Nicht für Vorstände und Konten mit 2FA (wie im Browser). |
| Passwort (+2FA) | allauth headless, Client `app`: `POST /_allauth/app/v1/auth/login`, ggf. `/auth/2fa/authenticate`; mit dem `session_token` dann `POST /api/app/v1/devices/` (Kopfzeile `X-Session-Token`). Die Sitzung wird danach gelöscht. |

Antwort jeweils `201` mit `token`, `device`, `user`.

## Was der Geräteschlüssel darf

Nur `/api/app/v1/…`, den Mitgliederbereich `/api/portal/<Zugang>/…` und `/api/me/contexts/`.
Auf allen anderen Pfaden antwortet HUBIplan mit `401`. Ein `401` mit
`code = device_not_authenticated` heißt: Gerät neu verbinden.

Der Schlüssel verfällt
- beim Abmelden des Geräts (`DELETE /api/app/v1/devices/<id>/`, auch im Browser),
- nach 180 Tagen ohne Nutzung,
- bei Passwortänderung oder -rücksetzung,
- wenn der letzte Zugang zum Mitgliederbereich entfernt wird.

Höchstens 10 aktive Geräte je Konto; beim elften fällt das am längsten ungenutzte weg.

## Schlüsselpaare, Erneuerung und Kopien (Härtung H7)

Ein Geräteschlüssel allein ist ein Inhabermerkmal. Damit ein abgegriffener Schlüssel nur kurz
wirkt, hält die App zwei Schlüsselpaare im Android-Keystore (P-256, nicht exportierbar).
Öffentliche Schlüssel als unkomprimierter Punkt (65 Byte), Unterschriften als DER, beides base64url.

- **Geräteschlüsselpaar:** Die App schickt beim Verbinden `device_key` mit (`pair/` und
  `devices/`). Ältere Verbindungen melden ihn einmal nach: `PUT /api/app/v1/devices/current/key/`
  mit `{"device_key"}` (ein anderer Schlüssel als der gemeldete: 409). `device` nennt `key`
  (gemeldet) und `renew_due`.
- **Erneuern alle 7 Tage:** `POST /api/app/v1/devices/current/renew/` ohne Inhalt liefert
  `challenge` (5 Minuten, einmal nutzbar). Die App unterschreibt
  `hubiplan-renew\n<Geräte-Nr.>\n<challenge>` und schickt `{"challenge", "signature"}` an
  denselben Pfad; Antwort 201 mit neuem `token`. Der alte Schlüssel gilt weiter, bis der neue
  zum ersten Mal benutzt wird, danach noch 5 Minuten. Kam die Antwort nicht an, erneuert die
  App mit dem alten Schlüssel noch einmal.
- **Nach 14 Tagen ohne Erneuerung** antwortet jeder Pfad außer `renew/` mit 401 und
  `code = device_renew`; die App erneuert und wiederholt die Anfrage. Geräte ohne
  Schlüsselpaar (Apps vor 0.15) erneuern nicht, gelten aber höchstens 60 Tage ab dem
  Verbinden; danach verbindet sich die App neu (Fachfrage 3, 31.10.b).
- **Kopie erkannt:** Wird ein Vorgänger nach seiner Frist oder ein noch älterer Schlüssel
  benutzt, gibt es den Schlüssel zweimal. HUBIplan meldet das Gerät ab
  (`revoked_reason`), schickt dem Konto eine Mail und dem Betreiber einen Alarm.
- **Vorstands-Schlüsselpaar:** nur kurz nach Fingerabdruck oder PIN nutzbar. Die App schickt
  beim Freischalten `admin_key` mit; ohne `admin_key` oder ohne Geräteschlüsselpaar wird die
  Verwaltung nicht freigeschaltet (400, „App aktualisieren“), und Freischaltungen ohne
  Schlüsselpaar gelten nicht mehr (Fachfrage 3, 31.10.b); die Antwort nennt dann `signed: true`. Ab dann trägt jede
  Anfrage unter `/api/app/v1/admin/u|d/…` die Köpfe `X-Hubiplan-Time` (Unix-Sekunden, höchstens
  5 Minuten Abweichung) und `X-Hubiplan-Signature`, die Unterschrift über
  `hubiplan-admin\n<METHODE>\n<Pfad mit Abfrage, percent-kodiert>\n<Zeit>\n<SHA-256 des Inhalts, hex>`.
  Jede Unterschrift gilt nur einmal. Fehlt sie oder stimmt sie nicht: 401 mit
  `code = admin_signature`. Sperren der Verwaltung löscht den Schlüssel. Ohne das Telefon und
  dessen Entsperren ist ein abgegriffener `hpa_…` damit wertlos.

## Endpunkte

| Methode und Pfad | Zweck |
|---|---|
| `GET /api/app/v1/instance/` | Selbstauskunft ohne Anmeldung: `api_version`, `min_app_version`, `url`, `push` |
| `GET /api/app/v1/me/` | Konto, dieses Gerät, Zugänge (`portal`, je mit `theme`: Farben und Wappen der Einheit) |
| `GET /api/app/v1/devices/` | eigene Geräte (`current` = dieses Gerät) |
| `GET /api/portal/<Zugang>/events/?from=&to=` | Termine (wie Mitgliederbereich) |
| `PUT/DELETE /api/portal/<Zugang>/events/<id>/response/` | Zu-/Absage |
| `GET /api/portal/<Zugang>/circulars/` | Rundschreiben |
| `GET /api/portal/<Zugang>/` | eigenes Profil |
| `GET /api/app/v1/send/` | Einheiten, an deren Mitglieder dieses Konto Kurzmitteilungen senden darf (`circulars.send` im Verein, `dept.circulars.send` im Zug) |
| `POST /api/app/v1/send/<org|dept>/<id>/` | Kurzmitteilung an alle Mitglieder der Einheit: `subject`, `body`, `confirm` (false: nur Empfängerzahl, true: senden) |
| `PUT /api/app/v1/devices/current/key/` | Geräteschlüsselpaar nachmelden (H7) |
| `POST /api/app/v1/devices/current/renew/` | Geräteschlüssel erneuern (H7) |
| `PUT/DELETE /api/app/v1/devices/current/push/` | Push-Endpunkt dieses Geräts melden bzw. abmelden (`kind`, `endpoint`, `p256dh`, `auth`) |
| `GET /api/portal/<Zugang>/card/` | eigener Mitgliedsausweis: `state`, `url` (Inhalt des QR-Codes), bei gültigem Ausweis `display` (Name, Status, Mitgliedsart, Einheit, Untereinheiten, Mitgliedsnummer, `photo_url`, Farben); die App speichert ihn und zeigt ihn auch ohne Netz |
| `GET /api/portal/<Zugang>/photo/` | eigenes Foto: Stand (`approved`, `pending`, Einwilligung) |
| `POST /api/portal/<Zugang>/photo/` | Foto hochladen (multipart `file`, `consent=true`); wartet immer auf Freigabe durch den Vorstand |
| `DELETE /api/portal/<Zugang>/photo/` | Einwilligung widerrufen, alle Fotos löschen |
| `GET /api/portal/<Zugang>/photo/image/?status=&size=thumb` | eigenes Foto als Bild |
| `POST /api/portal/<Zugang>/change-requests/` | Änderung melden (wie im Browser) |

Bescheid per Push (`{"t":"info","access":…,"title":…,"text":…}`), wenn der Vorstand ein Foto
freigibt oder ablehnt und wenn er über eine Änderungsmeldung entscheidet.

## Push (Schritt A4)

- Web-Push nach RFC 8030, Inhalt verschlüsselt nach RFC 8291 (`aes128gcm`), Absender per VAPID
  (RFC 8292). Der Push-Dienst (UnifiedPush-Verteiler wie ntfy oder das Push-Gateway der
  Play-Variante) sieht nur Gerät, Zeit und Größe.
- Der VAPID-Schlüssel der Instanz liegt in `PRIVATE_ROOT/push/vapid.json` (Einstellung
  `PUSH_VAPID_KEY_FILE`) und wird beim ersten Gebrauch erzeugt; er ist Teil der Sicherung des
  privaten Speichers. Den öffentlichen Teil nennt `instance/` unter `push`.
- Endpunkte nur über https und nie an interne Adressen; keine Weiterleitungen. Antwortet der
  Dienst mit 404/410, fällt das Gerät auf Abruf zurück, bis die App den Endpunkt neu meldet.
- Nutzlast (JSON, höchstens 3000 Bytes, sonst nur `{"v":1,"t":"sync"}`):
  `{"v":1,"t":"circular","access":<Zugang>,"id":<Rundschreiben>,"kind":…,"title":…,"text":…,"from":…}`.
  Hinweise an das Mitglied (Foto freigegeben, Änderung übernommen): `{"t":"info","access":…,"title":…,"text":…}`.

## Google-Push über das Push-Gateway (Schritt A6)

Die Play-Fassung der App nutzt Firebase Cloud Messaging (FCM), wenn keine UnifiedPush-App
installiert ist. FCM nimmt Nachrichten nur mit dem Schlüssel des App-Herausgebers an. Deshalb
schicken die Instanzen ihre Web-Pushes an ein gemeinsames **Push-Gateway**, das sie an FCM
weiterreicht. Das Gateway sieht keinen Inhalt (der Web-Push bleibt für das Gerät verschlüsselt;
FCM bekommt ihn base64-kodiert im Feld `b`) und speichert nichts.

- Instanz: `PUSH_GATEWAY_URL=https://push.example.org` (leer: kein Google-Push). `instance/`
  nennt dann `{"kind":"fcm","gateway":…}`; die App meldet `kind=fcm` mit dem Endpunkt
  `<Gateway>/fcm/<FCM-Token>`. Andere Gateways nimmt die Instanz nicht an.
- Nutzlast über das Gateway höchstens 2600 Bytes (FCM erlaubt 4 KB), sonst nur `sync`.
- Gateway: dasselbe Backend-Abbild, Start mit
  `gunicorn pushgateway.app:application --bind 0.0.0.0:8000 --workers 2` (ohne Datenbank).
  Einstellungen: `PUSH_GATEWAY_PUBLIC_URL` (eigene https-Adresse, für die VAPID-Prüfung),
  `PUSH_GATEWAY_FCM_CREDENTIALS` (Datei mit dem Dienstkonto-Schlüssel des Firebase-Projekts,
  nur auf dem Server, nie im Repo), `PUSH_GATEWAY_RATE` (Nachrichten je Minute und Absender,
  Standard 600).
- Prüft je Nachricht: Größe (höchstens 2800 Bytes), `Content-Encoding: aes128gcm`, gültiges
  VAPID-Token für die eigene Adresse (höchstens 24 Stunden gültig). `Urgency: high` wird zu
  FCM-Priorität HIGH, sonst NORMAL. Antwort 201; unbekanntes Gerät 410; `GET /health`.

### Härtung H5

- **Bindung an die Instanz:** `instance/` nennt beim Weg `fcm` auch `vapid_public_key`. Die App
  meldet den Endpunkt `<Gateway>/fcm/<FCM-Token>/<Kennung>`; die Kennung sind die ersten 16
  Hex-Zeichen von SHA-256 über den rohen VAPID-Schlüssel. Das Gateway leitet nur weiter, wenn das
  VAPID-Token mit genau diesem Schlüssel signiert ist (sonst 403 „anderer Absender“). Wer nur das
  FCM-Token kennt, kann das Gerät also nicht wecken. Ältere Endpunkte ohne Kennung nimmt das
  Gateway weiter an, solange `PUSH_GATEWAY_ALLOW_UNBOUND=1` (Standard); nach dem Umstieg aller
  Apps auf 0 stellen.
- **Weitere Grenzen am Gateway:** `PUSH_GATEWAY_RATE_TOKEN` (je Minute und Gerät, Standard 30)
  und `PUSH_GATEWAY_RATE_IP` (je Minute und IP, Standard 1200). Hinter einem Proxy
  `PUSH_GATEWAY_TRUST_PROXY=1`, dann zählt die letzte Adresse aus `X-Forwarded-For` (die der Proxy selbst einträgt).
- **Füllbytes:** Jede Nachricht wird vor dem Verschlüsseln auf eine feste Größe gebracht
  (1024 Bytes oder die größte erlaubte Nutzlast). Der Push-Dienst kann an der Größe nicht mehr
  ablesen, was für eine Nachricht es ist.

## Rundschreiben per App

- Schalter „Per App, wo möglich“ (`via_app`, Standard an): Mitglieder, deren Zugang ein Gerät mit
  Push hat, bekommen das Rundschreiben als Push (Weg `app`); kommt bei keinem Gerät etwas an, geht
  es ersatzweise per Mail.
- Neue Art **Kurzmitteilung** (`short`): bis 500 Zeichen, keine Anhänge, nie als Brief. Wer weder
  App noch Mail hat, sieht sie nur im Mitgliederbereich (Weg `portal`). Höchstens 10
  Kurzmitteilungen je Einheit und Tag.
- Abbestellte Informationen gehen weiterhin weder per Mail noch per App hinaus.

## Verwaltung in der App (Schritt A8)

Konzept: `konzepte/android-verwaltung.md` im Projektordner. Wer in einer Einheit
Verwaltungsrechte hat, sieht in der App den Reiter „Verwaltung“.

- `GET /api/app/v1/admin/` (Geräteschlüssel): Einheiten mit Verwaltungsrechten
  (`members.*`, `photos.manage`, `cards.manage`, `events.manage`, `finance.*`, `billing.*`),
  ob 2FA eingerichtet ist und ob die Verwaltung freigeschaltet ist. Keine Daten.
- `POST /api/app/v1/admin/unlock/` mit `password` und `code` (TOTP): nur mit eingerichteter
  2FA, höchstens 5 Versuche je Gerät in 15 Minuten. Antwort 201 mit dem
  **Vorstandsschlüssel** `hpa_…` und `until`. `DELETE` sperrt wieder.
- Der Vorstandsschlüssel gilt nur unter `/api/app/v1/admin/u/<Einheit>/…`, der Geräteschlüssel
  dort nie. Er gilt 30 Tage und verfällt nach 14 Tagen ohne Nutzung; abgelaufen oder gesperrt:
  401 mit Hinweis zum Freischalten. Rechte und Datenbereich prüft jede Anfrage live wie im
  Browser (Rolle entzogen: sofort kein Zugriff). Höchstens 600 Anfragen je Stunde.
- Seit Härtung H3 gilt der Vorstandsschlüssel nur zusammen mit dem Geräteschlüssel desselben
  Geräts im Kopf `X-Hubiplan-Device: hpd_…`; fehlt er oder gehört er zu einem anderen Gerät: 401.
  Ein kopierter Vorstandsschlüssel allein reicht also nicht.
- Hinweise per Mail (Art „Sicherheit“, nicht abbestellbar): neues Gerät verbunden, Verwaltung in
  der App freigeschaltet, ab 3 Fehlversuchen beim Freischalten in einer Stunde (dann auch Alarm an
  den Betreiber).
- `GET /api/app/v1/admin/u/<Einheit>/tasks/`: offene Aufgaben wie auf der Startseite.
- Mein Konto › App & andere Instanzen › App auf dem Telefon zeigt „Verwaltung freigeschaltet bis …“ mit
  „Verwaltung sperren“ (`DELETE /api/app/v1/devices/<id>/admin/`); das Gerät bleibt angemeldet.

### Mitglieder und Freigaben (Schritt B2)

Unter `/api/app/v1/admin/u/<Einheit>/` liegen dieselben Ansichten wie im Browser unter
`/api/orgs/<Einheit>/`, nur mit dem Vorstandsschlüssel (`devices/admin_urls.py`). Gleiche
Prüfungen, gleiches Änderungsprotokoll, gleiches Rückgängig. **Diese Antworten sind damit Teil
der App-Schnittstelle:** Felder nur abwärtskompatibel ändern (neue Felder ja, umbenennen oder
entfernen nein), sonst brechen ältere Apps.

- Mitglieder: `members/` (Suche, seitenweise), `members/duplicates/`, `members/admit/` (mit
  `Idempotency-Key`), `members/<id>/` (GET/PATCH),
  `history/`, `change-type/`, `exit/`, `reentry/`, `fields/`, `photo/` (+ `approve/`,
  `rotate/`, `consent/`), `card/`, Unterobjekte `members/<id>/periods|departments|
  department-roles|honorary-titles/`.
- Auswahllisten nur lesen: `member-types/`, `fields/`, `departments/`, `honorary-titles/`.
- Freigaben: `change-requests/`, `change-requests/<id>/decide/`; offene Aufgaben enthalten
  dafür `ref` und `membership`.
- Rückgängig: `changes/<Paket>/undo/` mit dem Paket aus `X-Change-Set` der Antwort.
- Geburtstage und Jubiläen: `birthdays/`, `jubilees/`.
- Nur in der App:
  - `POST members/<id>/preview/` mit `action` (`change_type`, `exit`, `move`, `fee_self`,
    `bank`):
    Folgen als Sätze für die Bestätigungsseite, ändert nichts.
  - `POST members/<id>/move/` (`department`, `valid_from`): Untereinheit wechseln in einem
    Schritt (bisherige endet am Vortag), also ein Rückgängig.
  - `POST cards/check/` (`code`: gescannte Adresse `…/ausweis/<Schlüssel>` oder Schlüssel):
    Angaben wie auf der Prüfseite, dazu `membership`, wenn der Ausweis zu dieser Einheit gehört.
  - `billing/mandates/`: IBAN nur gekürzt (`iban_masked`), ganz nur mit `?voll=1` (die App
    fragt vorher die Gerätesperre ab).
- Das Änderungsprotokoll nennt bei Änderungen aus der App die Herkunft („über App (Pixel 8)“).

### Termine (Schritt B3)

Ebenfalls wie im Browser unter `/api/orgs/<Einheit>/events/…`, Lesen für alle mit
Vorstandsschlüssel, Ändern nur mit `events.manage`:

- `events/` (GET mit `from`/`to` oder `upcoming=1`; POST legt an, `notify` lädt per Mail ein),
  `events/<id>/` (GET/PATCH/DELETE; Absagen mit `is_cancelled` und `cancel_note`),
  `events/<id>/occurrence/` (einzelnen Serientermin absagen oder zurücksetzen),
  `events/<id>/notify/` (Mail über Änderung oder Absage).
- Rückmeldungen: `events/<id>/responses/` (GET: `summary` mit Zusagen, Absagen, Begleitung,
  Personen, offen; `items`, `open`; PUT `membership_id`, `status`, `guests`, `note` trägt
  für ein Mitglied ein, auch nach Anmeldeschluss und über die Höchstzahl hinaus),
  `events/<id>/responses/<Mitglied>/` (DELETE entfernt).
- Offene Aufgaben „Rückmeldungen“ enthalten den Termin in `ref`.
- Alles mit Änderungsprotokoll und Rückgängig.

### Kasse und Untereinheiten (Schritt B4)

Kasse unter `/api/app/v1/admin/u/<Einheit>/finance/…`, Rechte wie im Browser
(`finance.view` lesen, `finance.edit` buchen):

- Nur lesen: `accounts/`, `categories/`, `bookings/` (Filter wie im Browser, z. B.
  `?ohne_beleg=1`), `overview/`, `receipts/<id>/` (Beleg ansehen).
- `POST finance/app-booking/` (multipart): Buchung mit Beleg in einem Schritt, Felder wie
  `finance/bookings/`, dazu `file` (Pflicht). Kopfzeile `Idempotency-Key` ist Pflicht: Die App
  sendet Entwürfe, die ohne Netz auf dem Telefon lagen, später mit demselben Schlüssel, und
  gebucht wird nur einmal. Wie im Browser kein „Rückgängig“ (Belege sind Dateien).
- `POST finance/bookings/<id>/receipts/`: Beleg nachreichen. Ändern, Storno, Abschlüsse und
  Berichte nur im Browser.

Untereinheiten für Rollen nur dort (z. B. Zugführung): `GET /api/app/v1/admin/` nennt sie in
`departments` (`id`, `name`, `club_id`, `club_name`, `events`, `permissions` mit `dept.*`);
freischalten wie oben. Pfade unter `/api/app/v1/admin/d/<Untereinheit>/` wie im Browser unter
`/api/depts/<Untereinheit>/`: `""` (Angaben), `members/`, `members/<id>/` (GET/PATCH),
`changes/<Paket>/undo/`, `events/…` wie in B3.

### Barzahlung und Quittung (Schritt B5)

Unter `/api/app/v1/admin/u/<Einheit>/billing/…`, Rechte wie im Browser (`billing.view` lesen,
`billing.edit` kassieren):

- Nur lesen: `invoices/` (Filter wie im Browser, z. B. `?offen=1&suche=Muster`),
  `invoices/<id>/`, `settings/` (darin `accounts` mit `kind`, für die Auswahl der Barkasse).
- `POST invoices/<id>/cash/` mit `account` (eine Barkasse, Pflicht), `amount` (ohne: der offene
  Rest) und `date` (ohne: heute). Kopfzeile `Idempotency-Key` ist Pflicht; doppelt gesendet wird
  nur einmal gebucht. Antwort: `invoice` (wie `invoices/<id>/`) und `payment`.
- `GET payments/<id>/receipt/`: Quittung als PDF (im Browser ebenso unter
  `/api/orgs/<Einheit>/billing/payments/<id>/receipt/`, Link „Quittung“ bei der Zahlung).

Beitragsläufe, Mahnungen, Storno, Zahlungen entfernen und SEPA bleiben im Browser.

### Quittung mit Unterschrift

Konzept `konzepte/digitale-quittung.md`, Ablauf und Prüfung in
[verfahrensdokumentation-kasse.md](verfahrensdokumentation-kasse.md). Unter
`/api/app/v1/admin/u/<Einheit>/finance/cash-receipts/`, gleich wie im Browser unter
`/api/orgs/<Einheit>/finance/cash-receipts/`, Rechte `finance.view` (lesen) und `finance.edit`:

- `GET ""` (seitenweise, `?status=draft|final|cancelled`, `?suche=`), `GET <id>/`.
- `POST ""` Entwurf: `direction` (`in` Verein erhält, `out` Verein zahlt), `counterparty_name`,
  `counterparty_address`, `membership` (übernimmt Anschrift und E-Mail), `email`, `amount`,
  `purpose`, `vat_rate` (nur bei Bedarf), `account` (eine Barkasse), `category`, `project`.
  `PATCH <id>/` ändert den Entwurf; ändern sich Richtung, Name, Betrag, Zweck oder Steuersatz,
  werden beide Unterschriften geleert. `DELETE <id>/` verwirft den Entwurf.
- `POST from-invoice/<Rechnung>/` mit `account`, `amount` (ohne: offener Rest): Entwurf zur
  Barzahlung einer Rechnung; der Abschluss bucht dann die Zahlung zur Rechnung.
- `PUT <id>/signatures/treasurer/` und `…/counterparty/` mit
  `{"width", "height", "strokes": [[[x, y], …], …], "signed_at"?}`: nur Linienzüge in
  Bildschirmpunkten, keine Zeit- oder Druckwerte. Kassierer auch `{"use_stored": true}`,
  Gegenseite beim Eingang auch `{"declined": "Grund"}`. `signed_at` (ISO, höchstens 30 Tage
  alt) für offline geleistete Unterschriften. `DELETE` entfernt die Unterschrift.
- `POST <id>/finalize/` mit `{"confirmed": true, "send"?: true}` und Kopfzeile
  `Idempotency-Key` (Pflicht): Buchung, Belegnummer (= Buchungsnummer), PDF. Nur wer als
  Kassierer unterschrieben hat. Die Barkasse darf dabei nicht unter null fallen.
- `GET <id>/pdf/` (Entwurf: Vorschau), `POST <id>/send/` (`email` optional),
  `POST <id>/cancel/` mit `reason` (Storno mit Gegenbuchung).
- Hinterlegte eigene Unterschrift: `GET/PUT/DELETE /api/app/v1/admin/signature/` (nur mit
  Vorstandsschlüssel; im Browser `/api/me/signature/`).
