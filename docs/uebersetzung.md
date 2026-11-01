# Übersetzung (Deutsch und Englisch)

Konzept: „HUBIplan auf Englisch“ (Projektordner `konzepte/englisch.md`). Begriffe:
[glossar-en.md](glossar-en.md).

## Sprachen

- **Nutzersprache** (`User.language`, Mein Konto › Profil): Oberfläche, Fehlermeldungen,
  Hinweis-Mails und Push an das Konto, App.
- **Vereinssprache** (`Organization.language`, vorerst immer Deutsch): Belege, Briefe,
  Rechnungen, Ausweis, Vereinswebseite.
- Vor der Anmeldung gilt Deutsch; unten auf der Anmeldeseite lässt sich umschalten (Cookie
  `hp_lang`). Die Browsersprache wird nicht ausgewertet.
- Welche Sprachen wählbar sind, steuert `HUBIPLAN_LANGUAGES` (Standard `de`; zum Testen
  `de,en`). Ohne Freischaltung erscheinen weder Auswahl noch Umschalter.

## Im Code

**Backend** (Django-Bordmittel):

```python
from django.utils.translation import gettext as _, gettext_lazy, ngettext, pgettext

raise ValidationError(_("Das Austrittsdatum liegt vor dem Eintritt."))
label = gettext_lazy("Mitgliedsart")              # Felder, Auswahllisten, Modulebene
ngettext("%(n)d Mitglied", "%(n)d Mitglieder", n) % {"n": n}
pgettext("social", "Beitrag")                       # zweideutige Wörter
```

Texte für eine andere Person (Mails, Push, Hintergrundaufgaben) in deren Sprache erzeugen,
Belege in der Vereinssprache:

```python
from core.i18n import language_of, language_of_org

with language_of(user):
    send_mail(...)
with language_of_org(org):
    pdf = render_receipt(...)
```

**Frontend** (`src/i18n/index.ts`):

```ts
import { t, tc, tn } from '../i18n/index.ts'
import { formatDay, formatEuro } from '../i18n/format.ts'

t('Speichern')
t('Hallo {name}', { name })
tn('{n} Mitglied', '{n} Mitglieder', count)
tc('social', 'Beitrag')
```

Der deutsche Text ist der Schlüssel; Englisch steht in `src/i18n/en.json` (Einzahl/Mehrzahl
als `{ "one": …, "other": … }`, Zusammenhang als `"social|Beitrag"`). Datum, Zahl und
Betrag nie mit festem `'de-DE'`, sondern über `locale()` bzw. `format.ts`.

### Platzhalter für Abteilung, Verein und Dachverband

Texte mit `{gen}`, `{im}`, `{e_sg}`, `{dv_akk}` usw. (`organizations/terms.py`, `src/org/terms.ts`)
dürfen im englischen Katalog dieselben Platzhalter nutzen. Auf Englisch liefern sie einfache Formen:
`{gen}`, `{akk}`, `{dat}`, `{nom}` „the department“, `{ein}` „a department“ (bzw. „an …“),
`{im}` „in the department“, `{zum}` „to the department“, `{diesem}` „this department“,
`{deinem}` „your department“, `{pl}`/`{pl_dat}` „departments“; `{adj}` ist leer.

Vorgaben (Abteilung, Verein, Dachverband, Einheit, Gruppe, Plattform) werden übersetzt. Eigene
Bezeichnungen wie „Zug“ bleiben deutsch, außer die Einheit trägt in den Einstellungen eine
englische Bezeichnung ein (Felder `label_en`, `department_label_en`, Fachfrage F7).

Auswahl-Beschriftungen (`TextChoices`) sind übersetzbar (`gettext_lazy`). Das
Revisionsprotokoll speichert sie immer deutsch (`audit.log.record`).

### Mails, Push und Belege

- **Hinweis-Mails an ein Konto** (Einladung, Passwort, Anmelde-E-Mail, Geräte, 2FA,
  Mitgliederzugang, Verbund) entstehen in der Nutzersprache des Empfängers: Text unter
  `with language_of(user):` erzeugen und `outbox.mail.send(..., language=user_language(user))`
  übergeben. Die Sprache gilt für die Fußzeile („im Auftrag von …“, Impressum, Datenschutz) und
  das `lang`-Attribut der HTML-Mail. Geht eine Mail an mehrere Konten, je Sprache eine Mail.
- Mails und Schreiben, die der **Verein herausgibt** (Rechnungen, Mahnungen, Lastschrift,
  Quittungen, Rundschreiben, Termine, Meldungen, Kontaktformular), bleiben in der Vereinssprache
  (vorerst Deutsch). `mail.send` ohne `language` schreibt die Fußzeile deutsch.
- Finanzbelege sind immer deutsch (Fachfrage F1). Auswahl-Bezeichnungen darin über
  `core.i18n.german(obj.get_x_display)`, sonst stünde dort die Sprache der Person, die den Beleg
  erzeugt.
- **Push-Titel**: `notify_membership(id, gettext_noop("…"), text)`; übersetzt wird beim Senden in
  der Sprache des Kontos. Der Text (Vereinsname, Antwort des Vorstands) bleibt, wie er ist.
- Hintergrundaufgaben bekommen keine Sprache mit, sondern bestimmen sie beim Ausführen aus dem
  Empfänger. Texte für später als deutschen Schlüssel mit `gettext_noop` weitergeben.
- Datum in Mails: `core.i18n.date_text`/`datetime_text` (01.11.2026 bzw. 01/11/2026).
- Alarme an den Betreiber (`core.alarm`) bleiben deutsch.

## Prüfen

- Backend: `python manage.py uebersetzung_pruefen [--liste] [--streng]` holt neue Texte in
  `backend/locale/en/LC_MESSAGES/django.po` und zählt fehlende (braucht GNU gettext; im
  Testabbild vorhanden).
- Frontend: `npm run i18n:check -- [--list] [--add] [--strict]`.
- `scripts/test.sh` zeigt beide Berichte; nach der Abnahme (Schritt Ü8) werden Lücken zum
  Fehler.

Die `.mo`-Datei entsteht beim Bauen des Docker-Abbilds und liegt nicht im Repository.
