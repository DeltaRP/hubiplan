# Lernhilfen

Lernhilfen erklären an der Stelle, an der man etwas entscheidet oder einen Fachbegriff
liest, worum es geht. Sie sind für Vorstände, Kassierer und Schriftführer gedacht, die
das Thema zum ersten Mal übernehmen. Die Hilfen erscheinen nur in der Oberfläche für
angemeldete Bearbeitende, nicht im Mitgliederbereich und nicht auf öffentlichen Seiten.

## Bausteine

| Baustein | Wo | Wann sichtbar |
| --- | --- | --- |
| **Warum?** (Abwägung) | an Entscheidungen, z. B. Zahlungsziel, Mahnstufen, Steuerbereiche | immer; einzeln mit „Nicht mehr zeigen“ ausblendbar |
| **Warum?** (Grundlage) | an Entscheidungen mit Basiswissen, z. B. Belege, Kassenprüfung | nur mit eingeschalteten Lernhilfen |
| **?** an Begriffen | an Fachwörtern in Überschriften, Tabellenköpfen und Texten | nur mit eingeschalteten Lernhilfen; einfache Begriffe nur beim ersten Vorkommen pro Seite |
| **Wie gerechnet?** / **So funktioniert es:** | an berechneten Werten und Abläufen | immer |
| **Prüfliste** | vor dem Beitragslauf, dem Lastschriftlauf, dem Jahresabschluss, den Jahresbestätigungen für Zuwendungen und dem endgültigen Abschluss eines Wettbewerbs | immer; blockiert nie |
| **Glossar** | `/glossar`, verlinkt aus „Mein Konto“ und aus jeder „?“-Box | immer |

Hilfen zu Funktionen, die eine Einheit nicht freigeschaltet hat (Beiträge, Finanzen,
Termine, Webseite, Wettbewerbe), erscheinen weder an der Stelle noch im Glossar.

## Schalter und Ausblenden

- **Mein Konto › Profil › Lernhilfen**: Hauptschalter. Neue Konten starten mit EIN, Konten, die es
  vor der Einführung schon gab, mit AUS.
- „Nicht mehr zeigen“ blendet genau diese Erklärung für das eigene Konto überall aus.
  Für einige Sekunden steht „Rückgängig“ bereit. Unter „Mein Konto“ holt „Ausgeblendete
  Erklärungen wieder zeigen“ alle zurück.
- Gespeichert wird nur am Konto (`learning_aids`, `learning_hidden`); nichts wird
  ausgewertet. Die Datenschutzhinweise der Plattform nennen das (Abschnitt 5).

API (angemeldet, mit CSRF-Token):

| Aufruf | Wirkung |
| --- | --- |
| `GET /api/me/learning/` | Schalter und ausgeblendete Schlüssel |
| `PATCH /api/me/learning/` | `{"learning_aids": bool}` oder `{"learning_hidden": []}` (alle wieder zeigen) |
| `POST /api/me/learning/<schluessel>/hide/` | eine Erklärung ausblenden |
| `POST /api/me/learning/<schluessel>/show/` | eine Erklärung wieder zeigen |

Ein unbekannter Schlüssel gibt 404.

## Inhalte pflegen

Alle Texte stehen in `frontend/src/learning/content.ts`:

- `DECISIONS`: Entscheidungen („Warum?“), mit `basic: true` als Grundlage, mit `once: true`
  nur einmal pro Seite.
- `TERMS`: Begriffe („?“), mit `simple: true` nur beim ersten Vorkommen pro Seite.
- `HOWTOS`: „Wie gerechnet?“ und „So funktioniert es:“.
- `SOURCES`: Quellen. Jede Erklärung zu Recht oder Steuern nennt mindestens eine echte
  Quelle mit Fundstelle (z. B. § 64 Abs. 3 AO). Nichts erfinden; bei Zahlen und Fristen
  den aktuellen Stand prüfen (z. B. Freigrenze § 64 Abs. 3 AO: 50.000 € ab 2026,
  Aufbewahrung von Buchungsbelegen: 8 Jahre seit 2025).
- Jeder Text höchstens drei Sätze; jeder Begriff mit einem Beispiel mit Zahlen.
- Texte haben eine Fassung je Sprache (`LANGUAGES`, zurzeit nur Deutsch).

Wer eine Entscheidung hinzufügt oder entfernt, muss die Schlüsselliste
`backend/accounts/learning_keys.json` mitpflegen (sortiert). Der Frontend-Test
`src/test/Lernhilfen.test.tsx` vergleicht beide und prüft außerdem, dass jeder Schlüssel
an einer Stelle verwendet wird, jeder Tabellenkopf mit einem Glossarbegriff das „?“
trägt und die Texte die Regeln oben einhalten.

Im Code:

```tsx
import { HowTo, Term, Why } from '../../learning/Aids.tsx'
import { Checklist } from '../../learning/Checklist.tsx'

<th><Term k="mandate">Mandat</Term></th>
<Why k="due_days" />
<HowTo k="calc_fee" />
<Checklist title="Vor dem Beitragslauf" items={feeRunChecks(...)} />
```

Die Prüfpunkte und ihre Schwellen stehen in `frontend/src/learning/checks.ts`; die
Zahlen dafür liefern die Vorschau des Beitragslaufs (`checks`), die Lastschrift-Vorschläge
(`creditor_valid`, `expiring_soon`, `has_email`) und die Abschlussübersicht (`checks`).

## Bedienung und Barrierefreiheit

- Tab erreicht jedes „?“ und jedes „Warum?“; Enter oder Leertaste öffnet, Esc schließt,
  der Fokus kehrt zurück. Immer ist höchstens eine Hilfe offen.
- Breite Fenster zeigen die Hilfe neben oder unter der Stelle, schmale als Blatt von unten.
- Klickflächen mindestens 24 × 24 px; der Test prüft die Seiten mit axe-core.
- Beim Drucken werden alle Hilfen ausgeschrieben.

## Bereiche

Lernhilfen gibt es bei Mitgliedern, Beiträgen und Rechnungen, SEPA-Lastschrift, Kasse und
Abschluss (auch Kassenzählung und Kassenbericht Fest, Abschluss aufheben, Aufbewahrungsende,
Rücklagen, DATEV-Konten und E-Rechnung), Zuwendungsbestätigungen, Quittungen und Kontoauszug (camt.053), Webseite (Namen,
Fotos, Einwilligung, Suchmaschinen, Social Media, Alternativtext, Impressum), Verbund,
Untereinheiten, App-Geräten, dem verketteten Änderungsprotokoll, Würden (Ordnungszahlen) sowie
Wettbewerben (eigener oder fremder Wettbewerb, Wertung, Zugwertung, Preisplätze, Stechen,
vorläufig und endgültig, Zurücksetzen, Standzugang, Vogelschießen, Webseite; Schießscheiben:
Gleichstandsregeln, Foto nur als Vorschlag, Summe gegen Foto, Spiegelausschnitte sammeln, die
Begriffe Zehntelwertung, Innenzehner, Teiler, Spiegel und Loch in Loch und der Rechenweg vom
Trefferpunkt zu Ring, Zehntel und Teiler; Quellen BGB,
DSGVO, KUG und DSB-Sportordnung). Die Prüfliste der Webseite
behält ihre eigene Form, weil dort offene Pflichtpunkte das Veröffentlichen sperren; sie
trägt aber das „?“ an Impressum und „Verantwortlich“.
