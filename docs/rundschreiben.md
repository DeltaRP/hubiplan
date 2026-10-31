# Rundschreiben

Mails und Serienbriefe an ausgewählte Mitglieder (App `backend/circulars`).

## Wer schreibt an wen

Rundschreiben ist ein eigener Menüpunkt (`/rundschreiben`) für Dachverband,
Verein und Abteilung. Alte Adressen unter `/mitglieder/rundschreiben` und
`/abteilung/rundschreiben` leiten dorthin weiter.

- **Dachverband** (Recht `circulars.send`): an die Vorstände seiner Vereine
  (Inhaber von Vorstandsrollen mit Zugang, sonst die Kontaktadresse des Vereins),
  an Mitglieder der Vereine nur mit Zugriff auf die Mitgliedsdaten.
- **Verein** (Recht `circulars.send`): an seine aktuellen Mitglieder oder an die
  Rolleninhaber in den Abteilungen (Empfängerkreis `departments`, Filter nach
  Abteilung und Rollenname, z. B. alle Zugführer) oder an die Rolleninhaber des
  Vereins selbst (Empfängerkreis `roles`, Filter `club_roles`, z. B. nur der
  Kassierer, nur der Schriftführer oder „Alle Vorstandsrollen auswählen“; ohne die
  Rollen der Abteilungen). Inhaber von Vereinsrollen sind Konten; mit Mitgliedsakte
  zählt die Akte, fehlt dort die Mail, geht sie an die Adresse des Kontos.
- **Abteilung** (Recht `dept.circulars.send`): nur an die Mitglieder der eigenen
  Abteilung.

Reiter **Empfangen** (Verein): Rundschreiben des Dachverbands an die Vorstände
(`/api/orgs/<id>/circulars/received/`). Mitglieder sehen ihre Rundschreiben
weiter im Mitgliederbereich.

Die Migration `core/0018` gibt das Recht allen Rollen, die Rollen verwalten.

## Empfänger

Filter (mit UND verknüpft, mehrere Werte je Filter mit ODER): Mitgliedsart,
Abteilung, Abteilungsrollen, Vorstandsrolle, Alter, Jubilare eines Jahres;
beim Dachverband Vereine und „nur gemeldete“. Dazu einzeln hinzufügen und
abwählen. Wer eine E-Mail-Adresse hat, bekommt eine Mail, alle anderen einen
Brief (Serienbrief-PDF mit Briefkopf und Anschriftfeld).

## Arten und Abmeldung

- **Information** an Mitglieder: Mitglieder können sich abmelden – Link in jeder Mail
  (`/rundschreiben/abmelden/<token>`, signiert), im Mitgliederbereich oder durch
  den Vorstand in der Mitgliedsakte (`Membership.info_opt_out_at`). Abgemeldete
  bekommen weder Mail noch Brief. Vorstände und Rolleninhaber können sich nicht
  abmelden.
- **Vereinsmitteilung** (z. B. Einladung zur Versammlung): geht an alle.

## Text

Einfache Auszeichnung: `**fett**`, `*kursiv*`, `[Text](https://…)`, Zeilen mit
`- ` oder `1. ` als Liste. Platzhalter: `{Vorname}`, `{Nachname}`,
`{Abteilung}`, `{Verein}`, `{Mitgliedsjahre}`, `{Jubiläumsjahre}`. Unbekannte
Platzhalter verhindern den Versand.

## Versand

Beim Versand werden die Empfänger festgehalten (`CircularRecipient`, zugleich
Versandprotokoll), die Mails gehen einzeln im Hintergrund (Celery) über den
Postausgang. PDF-Anhänge (bis 5, je 10 MB) liegen einmal im privaten Speicher;
der Postausgang verweist darauf, statt sie je Mail zu kopieren. Versendete
Rundschreiben lassen sich nicht ändern oder löschen, nur „erneut verwenden“.
Mitglieder sehen ihre Rundschreiben im Mitgliederbereich.

Mit `MAIL_RATE_PER_HOUR` (z. B. 100 beim Hestia-Postfach) gehen höchstens 90 % davon
je Stunde als Rundschreiben hinaus (alle Mails der letzten Stunde im Postausgang
zählen mit); der Rest folgt automatisch alle 5 Minuten, bis alles versendet ist.

## Mailverteiler (aus dem eigenen Mailprogramm)

Reiter **Verteiler** unter Rundschreiben (Verein, Dachverband und Untereinheiten mit
eigenem Recht). Ein Verteiler hat einen Namen und eine Adresse auf der
Verteiler-Domain, z. B. `alle@verein.example.org`. Wer das Recht
„Rundschreiben versenden“ für die Einheit hat, schreibt aus Outlook, Thunderbird oder
vom Handy an diese Adresse. HUBIplan macht daraus ein Rundschreiben
(`backend/circulars/inbound.py`):

Adressen: Kleinbuchstaben, Ziffern, Punkt, Binde- und Unterstrich; Umlaute werden
umgeschrieben (`schriftführer` wird `schriftfuehrer`), denn Umlaut-Adressen kommen
bei vielen Mailservern nicht an. Je Verteiler gibt es bis zu fünf **weitere
Adressen** (`aliases`, z. B. `schriftfuehrerin`, `sf`); alle Adressen sind auf der
ganzen Instanz eindeutig. `name+zusatz@` zählt als `name@`.

**Wer darf schreiben:** alle mit dem Recht, nur ausgewählte Konten, oder **alle**
(`open_senders`, Ralf 2026-10-31, gedacht für sehr kleine Empfängerkreise). Beim
Einschalten fragt die Oberfläche nach. Fremde Absender (ohne Recht oder ohne Konto)
gehen dann ohne Bestätigung direkt an den Verteiler (im Modus „Entwurf“ als Entwurf),
Antworten an den Absender; sie bekommen keine Rückmail. Verworfen werden weiter
automatische Mails, DMARC-Fehler und vom Spamfilter markierte Mails (`X-Spam-Flag`),
und je fremdem Absender gehen höchstens drei Mails am Tag durch.

1. Das Sammelpostfach (Catch-all der Domain) wird jede Minute per IMAP abgeholt
   (Celery-Beat `verteiler-abholen`); verarbeitete Mails werden dort gelöscht,
   Mails mit Verarbeitungsfehler bleiben gelesen liegen.
2. Verworfen ohne Antwort: Rückläufer, Abwesenheitsnotizen (`Auto-Submitted`,
   `Precedence`), Mails von HUBIplan selbst, `dmarc=fail` des eigenen Mailservers,
   unbekannte Adressen und Absender ohne Konto mit dem Recht. Der Vorstand sieht
   alle Eingänge beim Verteiler.
3. Absender ist das Konto mit dieser E-Mail-Adresse. Rechte: `circulars.send` in der
   Einheit des Verteilers, bei Verteilern einer Untereinheit auch `dept.circulars.send`
   dort. Je Verteiler lässt sich der Kreis weiter einschränken („Wer darf an den
   Verteiler schreiben?“ → nur ausgewählte, `MailingList.senders`); zur Auswahl stehen
   nur Konten mit dem Recht, und auch Ausgewählte brauchen das Recht weiterhin. Leere
   Auswahl heißt: alle mit dem Recht.
4. Betreff wird Betreff, Text wird Text (HTML-Mails als einfacher Text mit fett,
   Listen und Links), Platzhalter wie `{Vorname}` wirken, andere geschweifte Klammern
   werden zu runden. Nur PDF-Anhänge werden übernommen (wie in der Oberfläche).
5. Empfänger, Art (Information oder Vereinsmitteilung), Empfängerkreis und Zustellung
   stehen im **Muster** des Verteilers: einem Rundschreiben-Entwurf, der nie versendet
   wird und nicht in der Liste erscheint. Die Auswahl wird bei jedem Eingang neu
   berechnet.
6. **Versand** je Verteiler:
   - *Absender bestätigt per Link* (Standard): Mail an die Kontoadresse des Absenders
     mit Empfängerzahlen und Link `/rundschreiben/bestaetigen/<token>` (7 Tage gültig).
     Erst der Knopf „Jetzt versenden“ versendet (das Öffnen allein nicht, weil
     Virenscanner Links vorab laden). Ein gefälschter Absender bekommt den Link nie.
     Beim Klick wird das Recht erneut geprüft.
   - *als Entwurf ablegen*: Das Rundschreiben liegt unter Rundschreiben und wird dort
     versendet.
   - *direkt versenden (ohne Bestätigung)*: Mails berechtigter Absender (Konto und
     Recht) gehen sofort hinaus; der Absender bekommt nur eine Versandmeldung. Vor
     gefälschten Absendern schützt dann nur die DMARC-Prüfung, daher fragt die
     Oberfläche beim Einschalten nach. Nur für kleine Empfängerkreise gedacht.
7. Antwort-an ist der Absender: Antworten der Mitglieder gehen nie an alle.

Im „Von“ jeder Rundschreiben-Mail steht „Person (Verein)“ bzw. „Person (Untereinheit)“,
ohne Konto die Adresse des Absenders; die Adresse selbst bleibt `DEFAULT_FROM_EMAIL`
(nur für sie unterschreibt der Server, sonst scheitert DMARC). Die Fußzeile ist die
des Postausgangs („im Auftrag von … über HUBIplan versandt“, Impressum, Datenschutz),
bei Informationen an Mitglieder ergänzt um den Abmeldelink.

Ohne Sammelpostfach (Testserver) gibt es beim Verteiler den **Probe-Eingang**: als
käme eine Mail von der eigenen Adresse (`INBOUND_SIMULATION`, Standard: an, solange
`INBOUND_IMAP_HOST` leer ist).

Einstellungen (`.env`): `INBOUND_DOMAINS`, `INBOUND_IMAP_HOST`, `INBOUND_IMAP_PORT`
(993, TLS), `INBOUND_IMAP_USER`, `INBOUND_IMAP_PASSWORD`, `INBOUND_IMAP_FOLDER`
(`INBOX`), `MAIL_RATE_PER_HOUR`. Einrichtung auf dem Hestia-Server:
[echtbetrieb.md](echtbetrieb.md#mailverteiler).

## An einen Verteiler

Hat die Einheit Verteiler, zeigt „An“ im Rundschreiben nur diese (Ralf 2026-10-31).
Das Rundschreiben merkt sich den Verteiler (`Circular.mailing_list`); Empfängerkreis
und Auswahl kommen aus dessen Muster und werden bei Vorschau und Versand neu
übernommen (`services.apply_list`). Die Filter sind dann ausgeblendet; geändert wird
die Auswahl beim Verteiler. Ohne Verteiler bleibt die freie Auswahl wie bisher.

## Zustellung

Je Rundschreiben (und im Muster eines Verteilers) wählt man die Zustellung:

- **per App, sonst E-Mail** (Standard): Mitglieder mit der HUBIplan-App und Mitteilungen
  bekommen es nur aufs Telefon, alle anderen per Mail (`via_app`).
- **per App und zusätzlich E-Mail**: App-Nutzer bekommen beides (`via_app` + `also_mail`).
  Die zusätzliche Mail zählt zur Stundengrenze.
- **nur per E-Mail**: niemand per App.

Ohne Mailadresse gibt es wie bisher einen Brief (Kurzmitteilung: nur im Mitgliederbereich).
