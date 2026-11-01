# Anmeldung an der Nextcloud mit dem HUBIplan-Konto

App `backend/oidc`, Seite Einstellungen › Nextcloud (`frontend/src/pages/settings/NextcloudPage.tsx`),
Anmeldeseite `/oidc/anmelden` (`frontend/src/pages/NextcloudLoginPage.tsx`).
Konzept: `konzepte/nextcloud-anbindung.md` im Projektordner (Schritt N6).

HUBIplan ist Anmeldedienst nach OpenID Connect. Die Nextcloud eines Vereins (oder
Dachverbands) nutzt die offizielle App **„OpenID Connect user backend“ (`user_oidc`)**.
Wer sich dort mit „Mit HUBIplan anmelden“ anmeldet, landet kurz bei HUBIplan
(Anmeldung wie immer, mit Zwei-Faktor-Anmeldung, falls eingerichtet) und kommt ohne
Rückfrage zurück. Die Nextcloud legt das Konto bei der ersten Anmeldung selbst an und
übernimmt die Gruppen.

## Wer darf hinein

Nur, was bei der eintragenden Einheit gilt (Rechte höherer Einheiten zählen nicht):

- aktive Rollen der Einheit am Benutzerkonto (Vorstand, Kassierer, …),
- Ämter in Untereinheiten (z. B. Zugführer) über die eigene Mitgliedschaft,
- bei „Nur Rollen dieser Einheit“ zählen Ämter in Untereinheiten nicht (weder für den
  Zugang noch als Gruppe),
- bei „zusätzlich Mitglieder mit Zugang“ (nur Vereine): jedes Konto mit
  Mitgliederzugang und laufender Mitgliedschaft.

Austritt, Ende der Rolle oder gesperrtes Konto: Die nächste Anmeldung scheitert.
Laufende Nextcloud-Sitzungen beendet HUBIplan nicht; zum sofortigen Sperren das Konto in
der Nextcloud deaktivieren.

Optional „nur mit Zwei-Faktor-Anmeldung“: Die HUBIplan-Sitzung muss mit zweitem Faktor
entstanden sein (`amr` enthält `mfa`), sonst erklärt die Anmeldeseite, was zu tun ist.

## Was die Nextcloud erfährt

Im ID-Token und unter `userinfo` (je nach angefragtem `scope`):

| Angabe | Inhalt |
|---|---|
| `sub` | Kennung je Dienst (HMAC aus Benutzernummer und Salz des Eintrags), 32 Zeichen; zwei Dienste können Nutzer darüber nicht zusammenführen |
| `name`, `given_name`, `family_name` | aus der Mitgliedsakte, sonst aus dem Konto |
| `preferred_username` | nur bei Eintrag unter „Bisherige Benutzernamen“ (Scope `profile`): der vorhandene Benutzername in der Nextcloud |
| `email` | Anmelde-E-Mail |
| `groups` | je nach Einstellung „Vorstand“, Rollennamen, „Amt (Untereinheit)“, Namen der Untereinheiten, „Mitglieder“ (höchstens 64 Zeichen je Name) |
| `amr`, `auth_time` | wie und wann die HUBIplan-Sitzung angemeldet wurde |

Gruppennamen sind fest (nicht übersetzt). Wird eine Rolle oder Untereinheit umbenannt,
entsteht in der Nextcloud eine neue Gruppe; Freigaben dort ggf. anpassen.

## Vorhandene Nextcloud-Konten übernehmen

Gibt es die Nextcloud schon, legt `user_oidc` sonst bei der ersten Anmeldung ein neues,
leeres Konto an. Damit jemand in seinem bisherigen Konto landet, trägt die Einheit unter
„Bisherige Benutzernamen“ je Zeile `Anmelde-E-Mail = Benutzername` ein (z. B.
`maria.muster@example.org = mmuster`). HUBIplan schickt dann `preferred_username`.

In der Nextcloud dazu beim Anbieter:

- Benutzer-ID-Zuordnung (`mapping-uid`): `preferred_username`,
- „Eindeutige Benutzer-ID verwenden“ aus (`--unique-uid=0`), sonst bildet `user_oidc`
  eine Prüfsumme statt des Namens,
- in der `config.php` „soft auto provisioning“ an (`occ config:system:set user_oidc soft_auto_provision --type=boolean --value=true`),
  damit ein vorhandenes Konto mit diesem Namen übernommen statt abgelehnt wird.

Die Liste wird bewusst von Hand gepflegt und nicht aus Vor- und Nachnamen abgeleitet:
Sonst könnte jemand mit einer Namensänderung in HUBIplan ein fremdes Konto bekommen. Wer
die Liste ändern darf („Rollen und Benutzer verwalten“), kann damit jede Person mit jedem
Nextcloud-Konto verbinden, also nur eintragen, was sicher dieselbe Person ist. Nicht
aufgeführte Personen bekommen wie bisher ein neues Konto mit der Kennung `sub`.

Die Gruppen-Provisionierung von `user_oidc` setzt die Gruppen bei jeder Anmeldung neu.
Gruppen, die nur in der Nextcloud gepflegt werden (z. B. `admin`), vorher prüfen.

## Ablauf und Schutz

- Nur Authorization Code Flow, nur Clients mit Geheimnis (`client_secret_basic` oder
  `client_secret_post`). Gespeichert ist nur die SHA-256-Prüfsumme des Geheimnisses; es
  wird beim Anlegen bzw. „Neues Geheimnis“ einmal angezeigt.
- Rückleitung nur an `<Nextcloud>/apps/user_oidc/code` bzw. mit `/index.php` (genauer
  Vergleich). Unbekannte Rückleitungen werden nie benutzt.
- PKCE nur mit `S256` (`plain` wird abgelehnt), optional.
- Code 60 Sekunden, nur einmal einlösbar; Zugriffsschlüssel 5 Minuten; keine
  Refresh-Token. Beides nur im Cache (Redis), nie in der Datenbank.
- ID-Token RS256; Schlüssel `PRIVATE_ROOT/oidc/signing.pem` (in den Backups enthalten),
  wird beim ersten Gebrauch angelegt. Anderer Ort: `OIDC_KEY_FILE`.
- Aufrufbremsen: Token und Userinfo 60 je Minute und Adresse, Anmeldung 30 je 10 Minuten
  und Konto.
- Einträge stehen unter RLS (Tabelle `oidc_client`), Änderungen im Änderungsprotokoll
  (ohne Geheimnis). Beim Umzug auf eine andere Instanz werden sie nicht mitgenommen.
- Einstellen darf, wer „Rollen und Benutzer verwalten“ hat (damit auch die Pflicht zur
  Zwei-Faktor-Anmeldung für dieses Recht).

## Schnittstellen

| Pfad | Zweck |
|---|---|
| `/api/oidc/.well-known/openid-configuration` | Discovery (in der Nextcloud eintragen) |
| `/api/oidc/jwks` | öffentlicher Schlüssel |
| `/oidc/anmelden` | Anmeldeseite (Authorization Endpoint, Oberfläche) |
| `/api/oidc/authorize/` | GET: Dienst beschreiben, POST: Code ausstellen (angemeldet, CSRF) |
| `/api/oidc/token` | Code einlösen (Server der Nextcloud) |
| `/api/oidc/userinfo` | Angaben mit Zugriffsschlüssel |
| `/api/orgs/<id>/nextcloud/` | Einträge der Einheit; `<eintrag>/secret/` erneuert das Geheimnis |

Kennung als Anbieter (`issuer`): `FRONTEND_URL/api/oidc`, änderbar mit `OIDC_ISSUER`.

## In der Nextcloud einrichten

1. Als Administrator die App „OpenID Connect user backend“ installieren.
2. Verwaltung › OpenID Connect › Anbieter hinzufügen: Name (z. B. „HUBIplan“),
   Client-ID, Client-Geheimnis und Discovery-Endpunkt aus Einstellungen › Nextcloud.
3. „Gruppen-Provisionierung“ einschalten, Gruppen-Zuordnung `groups`; Anzeigename
   `name`, E-Mail `email`.
4. Mit einem Testkonto anmelden und die Gruppen prüfen, bevor Ordner danach
   freigegeben werden.
