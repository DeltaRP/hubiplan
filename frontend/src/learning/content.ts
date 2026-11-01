// Lernhilfen: alle Texte an einer Stelle. Vorlagen rufen nur <Why k="…" />,
// <Term k="…">, <HowTo k="…" /> und die Prüflisten mit dem Schlüssel auf.
//
// Regeln (Tests in src/test/Lernhilfen.test.tsx):
// - höchstens drei Sätze je Text, Kurzbeleg im Text, Quelle vollständig unten
// - „Warum?“ nennt, was dafür und was dagegen spricht und wann man was nimmt
// - jeder Begriff hat ein Beispiel mit Zahl und einer Lesart in Alltagssprache
// - Schlüssel der Entscheidungen = backend/accounts/learning_keys.json
//
// Sprachen: die Oberfläche ist nur deutsch. Jeder Text ist trotzdem ein Objekt je
// Sprache, damit weitere Sprachen ohne Umbau dazukommen können.

export const LANGUAGES = ['de'] as const
export type Lang = (typeof LANGUAGES)[number]
export type Text = Record<Lang, string>

export function tr(text: Text): string {
  const lang = (typeof document !== 'undefined' && document.documentElement.lang) || 'de'
  return text[lang as Lang] ?? text.de
}

// --- Quellen (wiederverwendbar, jede nur einmal) ---

export interface Source {
  /** vollständige Angabe */
  full: string
  url?: string
}

const SOURCES_DATA = {
  bgb: {
    full: 'Bürgerliches Gesetzbuch (BGB) in der Fassung der Bekanntmachung vom 2. Januar 2002 (BGBl. I S. 42, 2909; 2003 I S. 738), in der jeweils geltenden Fassung.',
    url: 'https://www.gesetze-im-internet.de/bgb/',
  },
  ao: {
    full: 'Abgabenordnung (AO) in der Fassung der Bekanntmachung vom 1. Oktober 2002 (BGBl. I S. 3866; 2003 I S. 61), in der jeweils geltenden Fassung.',
    url: 'https://www.gesetze-im-internet.de/ao_1977/',
  },
  ustg: {
    full: 'Umsatzsteuergesetz (UStG) in der Fassung der Bekanntmachung vom 21. Februar 2005 (BGBl. I S. 386), in der jeweils geltenden Fassung.',
    url: 'https://www.gesetze-im-internet.de/ustg_1980/',
  },
  ustae: {
    full: 'Bundesministerium der Finanzen: Umsatzsteuer-Anwendungserlass (UStAE) vom 1. Oktober 2010 (BStBl. I S. 846), Abschnitt 1.4 „Mitgliederbeiträge“, in der jeweils geltenden Fassung.',
    url: 'https://www.bundesfinanzministerium.de/Web/DE/Themen/Steuern/Steuerarten/Umsatzsteuer/Umsatzsteuer-Anwendungserlass/umsatzsteuer-anwendungserlass.html',
  },
  kstg: {
    full: 'Körperschaftsteuergesetz (KStG) in der Fassung der Bekanntmachung vom 15. Oktober 2002 (BGBl. I S. 4144), in der jeweils geltenden Fassung.',
    url: 'https://www.gesetze-im-internet.de/kstg_1977/',
  },
  gobd: {
    full: 'Bundesministerium der Finanzen: Grundsätze zur ordnungsmäßigen Führung und Aufbewahrung von Büchern, Aufzeichnungen und Unterlagen in elektronischer Form sowie zum Datenzugriff (GoBD), BMF-Schreiben vom 28. November 2019 (BStBl. I S. 1269), in der jeweils geltenden Fassung.',
    url: 'https://www.bundesfinanzministerium.de/Content/DE/Downloads/BMF_Schreiben/Weitere_Steuerthemen/Abgabenordnung/2019-11-28-GoBD.html',
  },
  dsgvo: {
    full: 'Verordnung (EU) 2016/679 des Europäischen Parlaments und des Rates vom 27. April 2016 (Datenschutz-Grundverordnung, DSGVO), ABl. L 119 vom 4. Mai 2016, S. 1.',
    url: 'https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32016R0679',
  },
  bdsg: {
    full: 'Bundesdatenschutzgesetz (BDSG) vom 30. Juni 2017 (BGBl. I S. 2097), in der jeweils geltenden Fassung.',
    url: 'https://www.gesetze-im-internet.de/bdsg_2018/',
  },
  kug: {
    full: 'Gesetz betreffend das Urheberrecht an Werken der bildenden Künste und der Photographie (Kunsturhebergesetz, KUG) vom 9. Januar 1907 (RGBl. S. 7), in der jeweils geltenden Fassung.',
    url: 'https://www.gesetze-im-internet.de/kunsturhg/',
  },
  ddg: {
    full: 'Digitale-Dienste-Gesetz (DDG) vom 6. Mai 2024 (BGBl. 2024 I Nr. 149), in der jeweils geltenden Fassung.',
    url: 'https://www.gesetze-im-internet.de/ddg/',
  },
  epcSdd: {
    full: 'European Payments Council (2024). SEPA Direct Debit Core Scheme Rulebook (EPC016-06, 2025 Version 1.0, gültig ab 5. Oktober 2025).',
    url: 'https://www.europeanpaymentscouncil.eu/what-we-do/sepa-direct-debit/sepa-direct-debit-core-rulebook',
  },
  epcQr: {
    full: 'European Payments Council (2022). Quick Response Code: Guidelines to Enable Data Capture for the Initiation of a SEPA Credit Transfer (EPC069-12, Version 3.0).',
    url: 'https://www.europeanpaymentscouncil.eu/document-library/guidance-documents/quick-response-code-guidelines-enable-data-capture-initiation',
  },
  bbkCi: {
    full: 'Deutsche Bundesbank: Gläubiger-Identifikationsnummer (Antragstellung und Ausgabe).',
    url: 'https://www.bundesbank.de/de/aufgaben/unbarer-zahlungsverkehr/serviceangebot/sepa/glaeubiger-identifikationsnummer',
  },
  estg: {
    full: 'Einkommensteuergesetz (EStG) in der Fassung der Bekanntmachung vom 8. Oktober 2009 (BGBl. I S. 3366, 3862), in der jeweils geltenden Fassung.',
    url: 'https://www.gesetze-im-internet.de/estg/',
  },
  estdv: {
    full: 'Einkommensteuer-Durchführungsverordnung 2000 (EStDV 2000) in der Fassung der Bekanntmachung vom 10. Mai 2000 (BGBl. I S. 717), in der jeweils geltenden Fassung.',
    url: 'https://www.gesetze-im-internet.de/estdv_1955/',
  },
  ustdv: {
    full: 'Umsatzsteuer-Durchführungsverordnung (UStDV) in der Fassung der Bekanntmachung vom 21. Februar 2005 (BGBl. I S. 434), in der jeweils geltenden Fassung.',
    url: 'https://www.gesetze-im-internet.de/ustdv_1980/',
  },
  mstv: {
    full: 'Staatsvertrag zur Modernisierung der Medienordnung in Deutschland, Artikel 1: Medienstaatsvertrag (MStV), in Kraft seit 7. November 2020, in der jeweils geltenden Fassung.',
    url: 'https://www.die-medienanstalten.de/service/rechtsgrundlagen/gesetze-und-staatsvertraege',
  },
  tdddg: {
    full: 'Telekommunikation-Digitale-Dienste-Datenschutz-Gesetz (TDDDG) vom 23. Juni 2021 (BGBl. I S. 1982), in der jeweils geltenden Fassung.',
    url: 'https://www.gesetze-im-internet.de/ttdsg/',
  },
  eughFashionId: {
    full: 'Gerichtshof der Europäischen Union, Urteil vom 29. Juli 2019, Rechtssache C-40/17 (Fashion ID), ECLI:EU:C:2019:629.',
    url: 'https://curia.europa.eu/juris/liste.jsf?num=C-40/17',
  },
  wcag: {
    full: 'World Wide Web Consortium (W3C): Web Content Accessibility Guidelines (WCAG) 2.2, W3C Recommendation vom 5. Oktober 2023.',
    url: 'https://www.w3.org/TR/WCAG22/',
  },
  dkCamt: {
    full: 'Die Deutsche Kreditwirtschaft: Spezifikation der Datenformate, Anlage 3 der Schnittstellenspezifikation für die Datenfernübertragung (DFÜ-Abkommen), Kontoauszug camt.053 nach ISO 20022, in der jeweils geltenden Fassung.',
    url: 'https://www.ebics.de/de/datenformate',
  },
  dsbSpo: {
    full: 'Deutscher Schützenbund e. V.: Sportordnung (Regelwerk für das sportliche Schießen), in der jeweils geltenden Fassung.',
    url: 'https://www.dsb.de/fileadmin/dsb/sportordnung/',
  },
} satisfies Record<string, Source>

export type SourceKey = keyof typeof SOURCES_DATA
export const SOURCES: Record<SourceKey, Source> = SOURCES_DATA

// --- Entscheidungen („Warum?“) ---

export const PHASES = {
  setup: { de: 'Einrichten' },
  billing: { de: 'Abrechnen' },
  closing: { de: 'Buchen und Abschließen' },
  privacy: { de: 'Mitglieder und Datenschutz' },
  donations: { de: 'Spenden bestätigen' },
  website: { de: 'Webseite und Verbund' },
  competitions: { de: 'Wettbewerbe' },
} satisfies Record<string, Text>
export type PhaseKey = keyof typeof PHASES

/** Freischaltung: Modul der Organisation, ohne das eine Hilfe nicht erscheint. */
export type Feature = 'billing' | 'finance' | 'events' | 'platform' | 'website' | 'competitions'

export interface Decision {
  title: Text
  text: Text
  sources: SourceKey[]
  /** Ort in der Anwendung, fürs Glossar */
  place: Text
  phase: PhaseKey
  /** Grundlagen: nur bei eingeschalteten Lernhilfen */
  basic?: boolean
  /** nur beim ersten Vorkommen pro Seite */
  once?: boolean
  feature?: Feature
}

const d = (de: string): Text => ({ de })

const DECISIONS_DATA = {
  member_type_active: {
    title: d('Wann ist eine Mitgliedsart „aktiv“?'),
    text: d(
      'Aktive Mitglieder zählen getrennt, etwa beim Verbandsbeitrag je aktivem Mitglied und in der Entwicklung; passive zahlen oft weniger und nehmen weniger am Vereinsleben teil. Eine feine Einteilung hilft bei Meldung und Beitrag, kostet aber Pflege, wenn Mitglieder oft wechseln. Richte dich nach Satzung oder Beitragsordnung, die festlegen, welche Gruppen es gibt und was sie zahlen (§§ 25, 58 Nr. 2 BGB).',
    ),
    sources: ['bgb'],
    place: d('Mitgliedsart bearbeiten'),
    phase: 'setup',
  },
  member_type_duration: {
    title: d('Welche Zeiten zählen für die Mitgliedsdauer?'),
    text: d(
      'Zählt eine Art für die Dauer, fließen ihre Zeiten in Jubiläen und Ehrungen ein. Dafür spricht, dass Treue auch als passives Mitglied gewürdigt wird; dagegen, wenn eure Ehrenordnung nur aktive Jahre zählt. Übernimm die Regel aus Satzung oder Ehrenordnung, damit Ehrungen für alle gleich berechnet werden (§ 25 BGB).',
    ),
    sources: ['bgb'],
    place: d('Mitgliedsart bearbeiten'),
    phase: 'setup',
  },
  member_type_reported: {
    title: d('Welche Mitglieder an den Dachverband melden?'),
    text: d(
      'Gemeldete Mitglieder gibt der Verein mit ihren Daten an den Dachverband weiter, der danach seine Beiträge berechnet. Jede Weitergabe braucht eine Rechtsgrundlage und soll sich auf das Nötige beschränken (Art. 5 Abs. 1 lit. c, Art. 6 Abs. 1 DSGVO). Melde die Arten, die laut Satzung des Dachverbands zu melden sind, und keine darüber hinaus.',
    ),
    sources: ['dsgvo'],
    place: d('Mitgliedsart bearbeiten (mit Dachverband)'),
    phase: 'setup',
  },
  fiscal_year: {
    title: d('Kalenderjahr oder abweichendes Geschäftsjahr?'),
    text: d(
      'Das Kalenderjahr passt zur Steuer, denn die Körperschaftsteuer wird nach dem Kalenderjahr ermittelt (§ 7 Abs. 3 KStG). Ein abweichendes Geschäftsjahr passt, wenn sich das Vereinsjahr nach einer Saison oder einem Fest richtet, kann aber zusätzliche Aufstellungen für das Finanzamt nötig machen. Maßgeblich ist, was die Satzung bestimmt (§ 25 BGB).',
    ),
    sources: ['kstg', 'bgb'],
    place: d('Organisation bearbeiten → Geschäftsjahr'),
    phase: 'setup',
  },
  age_brackets: {
    title: d('Altersstufen oder eigene Mitgliedsart?'),
    text: d(
      'Altersstufen setzen den Beitrag automatisch nach dem Alter zu Beginn des Geschäftsjahrs, ohne dass du die Mitgliedsart wechseln musst. Eine eigene Mitgliedsart wie „Jugend“ ist besser, wenn sich mit dem Alter auch Rechte oder die Meldung ändern. Unterschiedliche Beiträge brauchen eine Grundlage in Satzung oder Beitragsordnung (§ 58 Nr. 2 BGB).',
    ),
    sources: ['bgb'],
    place: d('Beitragsregeln → Altersstufen'),
    phase: 'setup',
    feature: 'billing',
  },
  billing_cycle: {
    title: d('Jährlich oder öfter abrechnen?'),
    text: d(
      'Jährlich abrechnen spart Arbeit, Porto und Bankgebühren je Lastschrift. Halb- oder vierteljährlich verteilt hohe Beiträge auf kleinere Beträge, vervielfacht aber Läufe und Mahnungen. Was gilt, legen Satzung oder Beitragsordnung fest (§ 58 Nr. 2 BGB).',
    ),
    sources: ['bgb'],
    place: d('Beitragsregeln → Abrechnung und Rechnung'),
    phase: 'setup',
    feature: 'billing',
  },
  pro_rata: {
    title: d('Beitrag bei Eintritt im laufenden Zeitraum anteilig?'),
    text: d(
      'Anteilig heißt: Wer im Lauf des Zeitraums eintritt, zahlt je angefangenem Monat. Das wirkt gerecht und erleichtert den Eintritt im Herbst, macht die Beträge aber krumm und erklärungsbedürftig. Steht dazu nichts in Satzung oder Beitragsordnung, sollte der Vorstand eine Regel beschließen und für alle gleich anwenden (§ 58 Nr. 2 BGB).',
    ),
    sources: ['bgb'],
    place: d('Beitragsregeln → Abrechnung und Rechnung'),
    phase: 'setup',
    feature: 'billing',
  },
  due_days: {
    title: d('Wie lang soll das Zahlungsziel sein?'),
    text: d(
      'Das Zahlungsziel ist die Frist vom Rechnungsdatum bis zur Fälligkeit. Ohne Mahnung gerät ein Mitglied spätestens 30 Tage nach Fälligkeit und Zugang der Rechnung in Verzug, bei Verbrauchern aber nur, wenn die Rechnung darauf hinweist (§ 286 Abs. 3 BGB). Eine kurze Frist bringt das Geld früher, aber mehr Mahnungen; eine lange Frist wirkt umgekehrt.',
    ),
    sources: ['bgb'],
    place: d('Beitragsregeln → Abrechnung und Rechnung'),
    phase: 'setup',
    basic: true,
    feature: 'billing',
  },
  giro_qr: {
    title: d('QR-Code auf der Rechnung?'),
    text: d(
      'Der QR-Code enthält Empfänger, IBAN, Betrag und Verwendungszweck, sodass Mitglieder ihn mit der Banking-App scannen, statt abzutippen (EPC069-12). Das vermeidet Tippfehler und falsche Verwendungszwecke; nicht jede Banking-App liest ihn. Er lohnt sich, sobald Mitglieder überweisen statt per Lastschrift zu zahlen.',
    ),
    sources: ['epcQr'],
    place: d('Beitragsregeln → Abrechnung und Rechnung'),
    phase: 'setup',
    basic: true,
    feature: 'billing',
  },
  sepa_use: {
    title: d('Lastschrift oder Überweisung?'),
    text: d(
      'Per Lastschrift kommt der Beitrag pünktlich und ohne Mahnung; dafür brauchst du Gläubiger-ID, Mandate und eine Vorabankündigung. Zahler können eine Lastschrift innerhalb von acht Wochen ohne Begründung zurückgeben, was den Verein Bankgebühren kosten kann (§ 675x BGB, EPC016-06). Je mehr Mitglieder zahlen, desto mehr Arbeit spart die Lastschrift; bei wenigen reicht oft die Überweisung.',
    ),
    sources: ['bgb', 'epcSdd'],
    place: d('Beitragsregeln → SEPA-Lastschrift'),
    phase: 'setup',
    feature: 'billing',
  },
  prenotification: {
    title: d('Wie viele Tage Vorabankündigung?'),
    text: d(
      'Vor jedem Einzug kündigst du Betrag und Datum an, nach dem SEPA-Regelwerk 14 Kalendertage vorher, wenn nichts anderes vereinbart ist (EPC016-06). Eine kürzere Frist beschleunigt den Lauf, gilt aber nur, wenn sie im Mandat oder in den Beitragsbedingungen steht. Ohne solche Vereinbarung nimm 14 Tage.',
    ),
    sources: ['epcSdd'],
    place: d('Beitragsregeln → SEPA-Lastschrift'),
    phase: 'setup',
    feature: 'billing',
  },
  vat_show: {
    title: d('Umsatzsteuer auf Rechnungen ausweisen?'),
    text: d(
      'Echte Mitgliedsbeiträge, die alle für den Vereinszweck zahlen, sind kein steuerbarer Umsatz; auf sie gehört keine Umsatzsteuer (UStAE 1.4). Steuer weist du nur für Leistungen gegen Entgelt aus, etwa Verkauf oder Werbung, und nur, wenn der Verein kein Kleinunternehmer ist (§ 19 UStG: Vorjahr bis 25.000 €, laufendes Jahr bis 100.000 €). Wer Steuer ausweist, ohne sie zu schulden, schuldet sie trotzdem (§ 14c UStG); frag im Zweifel das Finanzamt oder eine Steuerberatung.',
    ),
    sources: ['ustae', 'ustg'],
    place: d('Beitragsregeln → Umsatzsteuer'),
    phase: 'setup',
    feature: 'billing',
  },
  dunning_levels: {
    title: d('Wie viele Mahnstufen und welche Gebühr?'),
    text: d(
      'Mehr Stufen geben säumigen Mitgliedern mehr Gelegenheit, kosten aber Zeit und verzögern Ausschluss oder Mahnbescheid. Gebühren über die tatsächlichen Kosten wie Porto hinaus brauchen eine Grundlage in Satzung oder Beitragsordnung (§§ 280 Abs. 2, 286, 58 Nr. 2 BGB). Beginne mit einer freundlichen Erinnerung ohne Gebühr und füge Stufen hinzu, wenn danach noch viel offen bleibt.',
    ),
    sources: ['bgb'],
    place: d('Beitragsregeln → Mahnstufen'),
    phase: 'setup',
    feature: 'billing',
  },
  tax_areas: {
    title: d('Kategorien steuerlichen Bereichen zuordnen?'),
    text: d(
      'Gemeinnützige Vereine trennen ideellen Bereich, Vermögensverwaltung, Zweckbetrieb und wirtschaftlichen Geschäftsbetrieb, weil nur Letzterer steuerpflichtig sein kann (§§ 14, 64, 65 AO). Die Zuordnung erleichtert die Steuererklärung, verlangt aber saubere Kategorien. Schalte sie ein, sobald der Verein Einnahmen aus Verkauf, Festen oder Werbung hat; bleiben diese einschließlich Umsatzsteuer bis 50.000 € im Jahr, fallen darauf keine Körperschaft- und Gewerbesteuer an (§ 64 Abs. 3 AO, seit 2026; vorher 45.000 €).',
    ),
    sources: ['ao'],
    place: d('Finanzen → Einrichtung → Kategorien'),
    phase: 'setup',
    feature: 'finance',
  },
  opening_balance: {
    title: d('Anfangsbestand mit Stichtag?'),
    text: d(
      'Der Anfangsbestand ist der Kontostand am Stichtag, ab dem du in HUBIplan buchst, meist der Beginn des Geschäftsjahrs. Nimm ihn aus Kontoauszug oder letztem Kassenbericht; ein geschätzter Wert geht schneller, zieht sich aber als Differenz durch jeden späteren Bericht. Die Rechenschaft des Vorstands verlangt eine lückenlose Zusammenstellung von Einnahmen und Ausgaben (§ 259 Abs. 1 BGB).',
    ),
    sources: ['bgb'],
    place: d('Finanzen → Einrichtung → Konten'),
    phase: 'setup',
    basic: true,
    feature: 'finance',
  },
  role_represents: {
    title: d('Wer vertritt die Einheit nach § 26 BGB?'),
    text: d(
      'Wer die Einheit nach § 26 BGB vertritt, schließt Verträge für sie und steht im Vereinsregister und im Impressum (§ 5 DDG). Kreuze das nur bei Rollen an, die die Satzung als Vorstand im Sinne des § 26 BGB nennt, nicht beim erweiterten Vorstand. Viele Vertretungsberechtigte machen den Verein beweglich, erhöhen aber das Risiko ungewollter Verpflichtungen.',
    ),
    sources: ['bgb', 'ddg'],
    place: d('Rollen bearbeiten'),
    phase: 'setup',
  },
  role_permissions: {
    title: d('Nur die nötigen Berechtigungen vergeben?'),
    text: d(
      'Jede Berechtigung öffnet Personendaten; vergib nur, was eine Rolle für ihre Aufgabe braucht (Art. 5 Abs. 1 lit. f, Art. 25 Abs. 2 DSGVO). Weite Rechte sind bequem, wenn wenige alles machen, erhöhen aber Fehler und Schaden bei verlorenen Zugangsdaten. Leg lieber eine Rolle mehr an, etwa „Kasse“ ohne Mitgliederverwaltung, als eine Sammelrolle für alle.',
    ),
    sources: ['dsgvo'],
    place: d('Rollen bearbeiten'),
    phase: 'setup',
  },
  collection_date: {
    title: d('Welches Einzugsdatum wählen?'),
    text: d(
      'Das Einzugsdatum muss ein Bankarbeitstag sein und nach Ablauf der Vorabankündigung liegen (EPC016-06). Ein frühes Datum bringt das Geld schneller; ein Datum kurz nach dem Monatsanfang trifft oft gedeckte Konten und kann Rücklastschriften sparen. Zieh nicht vor der Fälligkeit der Rechnungen ein.',
    ),
    sources: ['epcSdd'],
    place: d('Neuer Lastschriftlauf'),
    phase: 'billing',
    feature: 'billing',
  },
  paper_mandate: {
    title: d('Was gehört zu einem schriftlichen Mandat?'),
    text: d(
      'Ein Mandat nennt unter anderem Zahler, IBAN, Gläubiger-ID, Mandatsreferenz, Datum und Unterschrift (EPC016-06). Bewahre das Original auf, solange du darauf einziehst, und danach, solange Rückfragen möglich sind; ohne Nachweis muss der Verein eine bestrittene Lastschrift noch bis 13 Monate später erstatten (§§ 675u, 676b Abs. 2 BGB). Mandate aus dem Mitgliederbereich speichert HUBIplan selbst.',
    ),
    sources: ['epcSdd', 'bgb'],
    place: d('Lastschrift → Mandate → Schriftliches Mandat erfassen'),
    phase: 'billing',
    basic: true,
    feature: 'billing',
  },
  invoice_date: {
    title: d('Welches Rechnungsdatum für den Beitragslauf?'),
    text: d(
      'Ab dem Rechnungsdatum läuft das Zahlungsziel und damit auch die Frist bis zum Verzug (§ 286 Abs. 3 BGB). Ein Datum kurz vor dem Versand ist richtig; ein rückdatiertes verkürzt den Mitgliedern die Frist, ein spätes verschiebt den Geldeingang.',
    ),
    sources: ['bgb'],
    place: d('Neuer Beitragslauf'),
    phase: 'billing',
    basic: true,
    feature: 'billing',
  },
  dunning_send: {
    title: d('Mahnung per E-Mail oder Brief?'),
    text: d(
      'Per E-Mail ist die Mahnung schnell und kostenlos, per Brief lässt sich der Zugang besser belegen. Eine Mahnung wirkt erst, wenn sie zugeht (§ 130 Abs. 1, § 286 Abs. 1 BGB). Für die Erinnerung reicht meist E-Mail; vor Ausschluss oder Mahnbescheid ist ein Brief sicherer.',
    ),
    sources: ['bgb'],
    place: d('Rechnungen → Fällige Mahnungen'),
    phase: 'billing',
    feature: 'billing',
  },
  receipts: {
    title: d('Zu jeder Buchung ein Beleg?'),
    text: d(
      'Ohne Beleg lässt sich eine Buchung bei der Kassenprüfung und vor dem Finanzamt nicht nachweisen; der Grundsatz lautet „keine Buchung ohne Beleg“ (GoBD). Buchungsbelege sind acht Jahre aufzubewahren (§ 147 Abs. 1 Nr. 4, Abs. 3 AO). Den Beleg gleich bei der Buchung hochzuladen kostet einen Moment, spart aber die Suche vor dem Abschluss.',
    ),
    sources: ['gobd', 'ao'],
    place: d('Kassenbuch → Buchung erfassen'),
    phase: 'closing',
    basic: true,
    once: true,
    feature: 'finance',
  },
  closing_lock: {
    title: d('Abgeschlossenes Jahr sperren, statt es zu ändern?'),
    text: d(
      'Nach dem Abschluss ist das Jahr gesperrt, damit der geprüfte Kassenbericht gilt und spätere Änderungen sichtbar bleiben (§ 146 Abs. 4 AO). Das schützt vor stillen Korrekturen, kostet aber Beweglichkeit: Fehler korrigierst du dann mit einer Gegenbuchung im laufenden Jahr. Schließe erst ab, wenn die Kassenprüfer fertig sind.',
    ),
    sources: ['ao'],
    place: d('Abschluss → Jahresabschluss'),
    phase: 'closing',
    feature: 'finance',
  },
  booking_fixed: {
    title: d('Warum nur noch Storno statt Ändern oder Löschen?'),
    text: d(
      'Der ursprüngliche Inhalt einer Buchung muss feststellbar bleiben (§ 146 Abs. 4 AO), deshalb ist sie nach Ablauf des Folgemonats festgeschrieben (GoBD) und nur am Tag der Erfassung löschbar. Danach korrigierst du mit einem Storno: Eine Gegenbuchung hebt die falsche Buchung auf, beide bleiben sichtbar, und die richtige legst du neu an. Das ist umständlicher, macht aber jede Korrektur für Kassenprüfer und Finanzamt nachvollziehbar.',
    ),
    sources: ['ao', 'gobd'],
    place: d('Kassenbuch → Buchung'),
    phase: 'closing',
    feature: 'finance',
  },
  cash_audit: {
    title: d('Was prüfen die Kassenprüfer?'),
    text: d(
      'Kassenprüfer sieht das Gesetz nicht vor; ihre Aufgaben bestimmt die Satzung. Sie prüfen meist, ob jede Buchung belegt ist, die Bestände zu Kontoauszügen und Barkasse passen und Ausgaben durch Beschlüsse gedeckt sind. Ihr Bericht hilft der Mitgliederversammlung, über die Entlastung des Vorstands zu entscheiden, der Rechenschaft schuldet (§ 27 Abs. 3, §§ 666, 259 BGB).',
    ),
    sources: ['bgb'],
    place: d('Abschluss → Jahresabschluss'),
    phase: 'closing',
    basic: true,
    feature: 'finance',
  },
  cash_count: {
    title: d('Warum die Barkasse regelmäßig zählen, und zu zweit?'),
    text: d(
      'Die Barkasse muss jederzeit nachprüfbar sein: Gezähltes Geld und Kassenbuch sollen übereinstimmen (Kassensturzfähigkeit, § 146 Abs. 1 AO). Ein Zählprotokoll mit Stückelung belegt den Stand und macht eine Differenz mit Grund nachvollziehbar; eine zweite Person schützt den Kassierer vor Verdacht, kostet aber einen Termin mehr. Zähle mindestens zum Monats- und Jahresende und immer, wenn die Kasse übergeben wird.',
    ),
    sources: ['ao'],
    place: d('Finanzen → Kassenzählung'),
    phase: 'closing',
    feature: 'finance',
  },
  event_cash: {
    title: d('Warum die Tageseinnahme am Fest rückwärts ermitteln?'),
    text: d(
      'Ohne Registrierkasse wird nicht jeder Verkauf einzeln erfasst; die Einnahme ergibt sich aus Endbestand minus Wechselgeld plus bar bezahlte Ausgaben und Entnahmen (offene Ladenkasse, § 146 Abs. 1 AO). Das ist einfach, verlangt aber ein lückenloses Zählprotokoll am Ende, denn ohne es lässt sich die Einnahme nicht belegen. Eine elektronische Kasse wäre genauer, braucht aber eine zertifizierte Sicherheitseinrichtung (§ 146a AO).',
    ),
    sources: ['ao'],
    place: d('Finanzen → Kassenzählung → Kassenbericht Fest'),
    phase: 'closing',
    feature: 'finance',
  },
  reopen_closing: {
    title: d('Warum braucht das Aufheben eines Abschlusses einen Grund?'),
    text: d(
      'Ein abgeschlossenes Jahr ist die Grundlage für Kassenprüfung und Entlastung; wird es wieder geöffnet, muss erkennbar bleiben, was vorher galt (§ 146 Abs. 4 AO, GoBD). Deshalb bleibt der alte Stand mit Grund, Person und Zeit erhalten, und beim erneuten Abschluss siehst du die Unterschiede. Hebe einen Abschluss nur für echte Fehler auf, etwa einen vergessenen Beleg, und informiere die Kassenprüfer.',
    ),
    sources: ['ao', 'gobd'],
    place: d('Abschluss → Jahresabschluss'),
    phase: 'closing',
    feature: 'finance',
  },
  retention_end: {
    title: d('Wann dürfen alte Kassendaten weg?'),
    text: d(
      'Belege sind 8 Jahre, Bücher und Abschlüsse 10 Jahre aufzubewahren, gerechnet ab Ende des Kalenderjahres (§ 147 Abs. 3 und 4 AO); danach verlangt der Datenschutz, Personendaten zu löschen (Art. 5 Abs. 1 lit. e DSGVO). Bereinigen schützt ehemalige Mitglieder und Spender, ist aber endgültig. Bereinige nicht, solange Steuern dieser Jahre noch festgesetzt werden können, etwa während einer Betriebsprüfung, denn so lange läuft die Frist nicht ab (§ 147 Abs. 3 AO).',
    ),
    sources: ['ao', 'dsgvo'],
    place: d('Abschluss → Jahresabschluss'),
    phase: 'closing',
    feature: 'finance',
  },
  reserves: {
    title: d('Wann braucht der Verein eine Rücklage?'),
    text: d(
      'Ein steuerbegünstigter Verein muss seine Mittel grundsätzlich bis Ende des übernächsten Jahres verwenden (§ 55 Abs. 1 Nr. 5 AO); wer für ein Vorhaben spart, etwa ein Zelt oder ein Jubiläumsfest, bildet dafür eine Rücklage (§ 62 Abs. 1 AO). Rücklagen machen Sparen nachvollziehbar, binden aber Geld und brauchen einen Beschluss mit Zweck. Kleine Vereine unter der Einnahmengrenze in § 55 Abs. 1 Nr. 5 AO müssen nicht zeitnah verwenden, eine Rücklage hilft dann trotzdem bei der Planung.',
    ),
    sources: ['ao'],
    place: d('Finanzen → Rücklagen'),
    phase: 'closing',
    feature: 'finance',
  },
  datev_accounts: {
    title: d('Warum braucht jede Kategorie ein DATEV-Konto?'),
    text: d(
      'Die Steuerberatung bucht nach einem Kontenrahmen wie SKR 42 oder SKR 49; jede Einnahme und Ausgabe muss dort einem Sachkonto zugeordnet sein, sonst landet sie auf einem Sammelkonto und muss von Hand umgebucht werden (GoBD). Einmal sauber zugeordnet, geht der Export jedes Jahr ohne Nacharbeit. Stimme die Konten vorher mit der Steuerberatung ab, statt sie zu raten.',
    ),
    sources: ['gobd'],
    place: d('Finanzen → Einrichtung → Konten'),
    phase: 'setup',
    feature: 'finance',
  },
  deletion_period: {
    title: d('Wie lange Daten nach dem Austritt behalten?'),
    text: d(
      'Personendaten dürfen nicht länger gespeichert werden als nötig (Art. 5 Abs. 1 lit. e, Art. 17 Abs. 1 lit. a DSGVO). Eine kurze Frist schützt ehemalige Mitglieder, eine längere erlaubt Rückfragen, Wiedereintritte und Ehrungen; Rechnungen und Buchungen bleiben wegen der steuerlichen Aufbewahrung ohnehin länger (§ 147 AO). Orientiere die Frist an möglichen Rückfragen, etwa an der dreijährigen Verjährung (§ 195 BGB).',
    ),
    sources: ['dsgvo', 'ao', 'bgb'],
    place: d('Plattform → Einstellungen'),
    phase: 'privacy',
    feature: 'platform',
  },
  person_data_mode: {
    title: d('Personendaten gemeinsam oder je Einheit?'),
    text: d(
      'Gemeinsam gepflegt ändert eine Anschrift überall auf einmal, so bleiben Daten richtig (Art. 5 Abs. 1 lit. d DSGVO). Dafür sehen und ändern mehrere Einheiten dieselben Daten, was klare Absprachen über die Verantwortung verlangt (Art. 26 DSGVO). Eigene Kopien je Einheit trennen die Verantwortung, führen aber zu abweichenden Ständen.',
    ),
    sources: ['dsgvo'],
    place: d('Plattform → Einstellungen'),
    phase: 'privacy',
    feature: 'platform',
  },
  photo_consent: {
    title: d('Fotos nur mit Einwilligung?'),
    text: d(
      'Ein Foto erleichtert das Erkennen am Ausweis, zeigt aber eine Person erkennbar; dafür stützt sich der Verein in der Regel auf ihre Einwilligung (§ 22 KUG, Art. 6 Abs. 1 lit. a DSGVO). Die Einwilligung ist freiwillig und jederzeit widerrufbar, danach muss das Foto weg (Art. 7 Abs. 3 DSGVO). Der Ausweis funktioniert auch ohne Foto, also frag nur, wenn es wirklich hilft.',
    ),
    sources: ['kug', 'dsgvo'],
    place: d('Mitgliedsakte → Foto'),
    phase: 'privacy',
  },
  doc_visibility: {
    title: d('Wer soll die Dokumente eines Ordners sehen?'),
    text: d(
      'Je weiter ein Ordner sichtbar ist, desto leichter finden Mitglieder Satzung und Protokolle, desto größer ist aber das Risiko, dass Personendaten zu weit gehen (Art. 5 Abs. 1 lit. c und f DSGVO). Allgemeines wie die Satzung kann breit sichtbar sein, Protokolle mit Namen, Verträge und Listen nur für den Vorstand. Fang im Zweifel eng an und erweitere später.',
    ),
    sources: ['dsgvo'],
    place: d('Dokumente → Ordner'),
    phase: 'privacy',
  },
  event_visibility: {
    title: d('Termin öffentlich oder nur für Mitglieder?'),
    text: d(
      'Öffentliche Termine erreichen Gäste und Presse und lassen sich als Kalender abonnieren. Interne Termine schützen Ort, Zeit und Teilnehmende, etwa bei Vorstandssitzungen oder Treffen der Jugend (Art. 5 Abs. 1 lit. c DSGVO). Mach öffentlich, was ohnehin bekannt sein soll, und lass alles andere intern.',
    ),
    sources: ['dsgvo'],
    place: d('Termin bearbeiten'),
    phase: 'privacy',
    feature: 'events',
  },
  dpo: {
    title: d('Brauchen wir eine(n) Datenschutzbeauftragte(n)?'),
    text: d(
      'Pflicht ist das, wenn in der Regel mindestens 20 Personen ständig mit der automatisierten Verarbeitung personenbezogener Daten beschäftigt sind (§ 38 Abs. 1 BDSG) oder die Kerntätigkeit es verlangt (Art. 37 DSGVO). In kleinen Vereinen ist das selten der Fall. Freiwillig benannt hilft eine Ansprechperson trotzdem, kostet aber Zeit und Fachwissen.',
    ),
    sources: ['bdsg', 'dsgvo'],
    place: d('Einstellungen → Impressum und Datenschutz'),
    phase: 'privacy',
    basic: true,
  },
  donation_enabled: {
    title: d('Wer darf Zuwendungsbestätigungen ausstellen?'),
    text: d(
      'Jede steuerbegünstigte Körperschaft mit eigenem Bescheid, auch ein nicht eingetragener Verein (§ 10b Abs. 1 Satz 2 Nr. 2 EStG, § 5 Abs. 1 Nr. 9 und § 1 Abs. 1 Nr. 5 KStG). Entscheidend ist der Bescheid des Finanzamts, nicht der Eintrag im Vereinsregister. Unselbständige Untereinheiten wie Züge oder Abteilungen haben meist keinen eigenen Bescheid; ihre Spenden bestätigt der Verein.',
    ),
    sources: ['estg', 'kstg'],
    place: d('Finanzen → Zuwendungsbestätigungen → Einstellungen'),
    phase: 'donations',
    basic: true,
    feature: 'finance',
  },
  donation_notice: {
    title: d('Wie lange trägt der Bescheid des Finanzamts?'),
    text: d(
      'Zuwendungsbestätigungen darf der Verein nur ausstellen, solange der Freistellungsbescheid höchstens 5 Jahre oder die Feststellung nach § 60a AO höchstens 3 Kalenderjahre zurückliegt (§ 63 Abs. 5 AO). Danach stellt HUBIplan nichts mehr aus, bis der neue Bescheid eingetragen ist. Reich die Steuererklärung deshalb rechtzeitig ein, damit kein Spender auf seine Bestätigung warten muss.',
    ),
    sources: ['ao'],
    place: d('Finanzen → Zuwendungsbestätigungen → Einstellungen'),
    phase: 'donations',
    basic: true,
    feature: 'finance',
  },
  donation_fees: {
    title: d('Auch Mitgliedsbeiträge bestätigen?'),
    text: d(
      'Fördert der Verein vor allem Sport, Heimatpflege, Brauchtum oder Freizeitkultur, sind Mitgliedsbeiträge nicht als Spende abziehbar (§ 10b Abs. 1 Satz 8 EStG); das trifft auf Schützen-, Sport- und Karnevalsvereine meist zu. Eine Bestätigung dafür wäre unrichtig, und der Verein haftet für die entgangene Steuer (§ 10b Abs. 4 EStG). Schalte es nur ein, wenn der Bescheid andere Zwecke nennt, etwa Jugendhilfe oder Denkmalschutz.',
    ),
    sources: ['estg'],
    place: d('Finanzen → Zuwendungsbestätigungen → Einstellungen'),
    phase: 'donations',
    feature: 'finance',
  },
  donation_goods: {
    title: d('Was muss bei einer Sachspende belegt sein?'),
    text: d(
      'Bestätigt wird der Wert der Sache, bei gebrauchten Dingen der Marktwert (gemeiner Wert), bei Sachen aus einem Betrieb der Entnahmewert (§ 10b Abs. 3 Satz 2 und 3 EStG). Bezeichne die Sache genau und bewahre Unterlagen zum Wert auf, etwa Kaufbeleg oder Gutachten; ohne sie lässt sich der Betrag bei einer Prüfung nicht halten. Sachspenden stellt HUBIplan immer einzeln aus, nie in einer Sammelbestätigung.',
    ),
    sources: ['estg'],
    place: d('Finanzen → Zuwendungsbestätigungen → Zuwendung erfassen'),
    phase: 'donations',
    feature: 'finance',
  },
  donation_waiver: {
    title: d('Wann ist ein Verzicht auf Auslagen eine Spende?'),
    text: d(
      'Nur wenn ein Anspruch auf Erstattung vorher durch Vertrag oder Satzung bestand und dann darauf verzichtet wurde; der Anspruch darf nicht schon unter der Bedingung des Verzichts eingeräumt sein (§ 10b Abs. 3 Satz 5 und 6 EStG). Typisch sind Fahrtkosten nach einer Reisekostenregelung des Vereins. Fehlt so eine Regelung, ist der Verzicht keine abziehbare Spende.',
    ),
    sources: ['estg'],
    place: d('Finanzen → Zuwendungsbestätigungen → Zuwendung erfassen'),
    phase: 'donations',
    feature: 'finance',
  },
  donation_liability: {
    title: d('Wer haftet für eine falsche Bestätigung?'),
    text: d(
      'Wer vorsätzlich oder grob fahrlässig eine unrichtige Bestätigung ausstellt, haftet für die entgangene Steuer, pauschal 30 % des bestätigten Betrags (§ 10b Abs. 4 EStG). Der Verein bewahrt von jeder Bestätigung ein Doppel auf (§ 50 Abs. 7 EStDV); HUBIplan speichert das PDF dafür. Fehler korrigierst du durch Stornieren und neu Ausstellen, nicht durch Ändern.',
    ),
    sources: ['estg', 'estdv'],
    place: d('Finanzen → Zuwendungsbestätigungen'),
    phase: 'donations',
    basic: true,
    feature: 'finance',
  },
  donation_year_end: {
    title: d('Einzeln bestätigen oder einmal zum Jahresende?'),
    text: d(
      'Die Sammelbestätigung fasst alle Geldzuwendungen eines Spenders aus einem Kalenderjahr zusammen und spart Arbeit und Porto, die Einzelbestätigung kommt sofort; beide stehen im amtlichen Muster (§ 50 Abs. 1 EStDV). Bis 300 € reicht dem Spender oft schon der Kontoauszug zusammen mit einem Beleg des Vereins (§ 50 Abs. 4 Satz 1 Nr. 2 EStDV). Üblich ist: Großspenden sofort einzeln, alles andere im Januar gesammelt.',
    ),
    sources: ['estdv'],
    place: d('Finanzen → Zuwendungsbestätigungen'),
    phase: 'donations',
    feature: 'finance',
  },
  receipt_vat: {
    title: d('Umsatzsteuer auf der Quittung ausweisen?'),
    text: d(
      'Nur wenn die Zahlung zu einem umsatzsteuerpflichtigen Bereich gehört und der Verein kein Kleinunternehmer ist (§ 19 UStG). Wer Steuer ausweist, ohne dazu berechtigt zu sein, schuldet sie trotzdem dem Finanzamt (§ 14c Abs. 2 UStG). Bis 250 € genügt eine Kleinbetragsrechnung mit Steuersatz statt Steuerbetrag (§ 33 UStDV).',
    ),
    sources: ['ustg', 'ustdv'],
    place: d('Finanzen → Quittungen'),
    phase: 'closing',
    feature: 'finance',
  },
  web_names: {
    title: d('Wie viel vom Namen zeigt die Webseite?'),
    text: d(
      'Der volle Name macht Vorstand und Würdenträger eindeutig erkennbar, „Vorname N.“ schützt mehr, weil Suchmaschinen weniger finden (Art. 5 Abs. 1 lit. c DSGVO). Für Funktionen mit Außenwirkung wie den Vorstand ist der volle Name üblich. Bei Chronik und Würden reicht oft die kurze Form.',
    ),
    sources: ['dsgvo'],
    place: d('Webseite → Menü und Bereiche → Personen'),
    phase: 'website',
    feature: 'website',
  },
  web_consent: {
    title: d('Was zeigt die Webseite ohne Einwilligung?'),
    text: d(
      'Namen von Mitgliedern auf einer öffentlichen Seite brauchen eine Rechtsgrundlage, meist ihre Einwilligung (Art. 6 Abs. 1 lit. a DSGVO). „Auslassen“ ist am sichersten, ein Platzhalter hält dafür Listen wie die Königsliste vollständig. Einwilligungen und Widersprüche pflegst du in der Mitgliederakte unter „Veröffentlichung“.',
    ),
    sources: ['dsgvo'],
    place: d('Webseite → Menü und Bereiche → Personen'),
    phase: 'website',
    feature: 'website',
  },
  web_photos: {
    title: d('Welche Fotos dürfen auf die Webseite?'),
    text: d(
      'Bilder von erkennbaren Personen brauchen deren Einwilligung (§ 22 KUG, Art. 6 Abs. 1 lit. a DSGVO). Ausnahmen gelten etwa für Bilder von Versammlungen und Umzügen, auf denen die Menge im Vordergrund steht (§ 23 Abs. 1 Nr. 3 KUG). Im Zweifel nimm Gruppenbilder von öffentlichen Auftritten und frag bei Nahaufnahmen nach.',
    ),
    sources: ['kug', 'dsgvo'],
    place: d('Webseite → Bilder'),
    phase: 'website',
    feature: 'website',
  },
  web_indexing: {
    title: d('Sollen Suchmaschinen die Webseite aufnehmen?'),
    text: d(
      'Mit Aufnahme finden Interessierte den Verein über Suchmaschinen, ohne sie bleibt die Seite nur über die Adresse erreichbar. Dafür tauchen dann auch Namen auf der Seite in Suchergebnissen auf (Art. 5 Abs. 1 lit. c DSGVO). Schalte es ein, sobald Impressum, Datenschutz und Namensform stimmen.',
    ),
    sources: ['dsgvo'],
    place: d('Webseite → Internetadresse → Suchmaschinen'),
    phase: 'website',
    feature: 'website',
  },
  web_social: {
    title: d('Warum holt HUBIplan die Beiträge selbst ab?'),
    text: d(
      'Ein eingebetteter Instagram- oder Facebook-Beitrag schickt beim Seitenaufruf Daten an Meta; dafür bräuchte die Seite eine Einwilligung (§ 25 TDDDG), und der Verein wäre mitverantwortlich (EuGH, C-40/17). HUBIplan holt die Beiträge deshalb alle 30 Minuten selbst ab und zeigt sie ohne Verbindung zu Meta. Der Preis: Neue Beiträge erscheinen mit etwas Verzögerung, und jede Einheit braucht eine eigene Meta-App.',
    ),
    sources: ['tdddg', 'eughFashionId'],
    place: d('Webseite → Social Media'),
    phase: 'website',
    feature: 'website',
  },
  web_alt_text: {
    title: d('Wozu ein Alternativtext?'),
    text: d(
      'Screenreader lesen ihn blinden Besuchern vor, und er erscheint, wenn ein Bild nicht lädt (WCAG 2.2, Kriterium 1.1.1). Beschreib in einem Satz, was zu sehen ist und was davon wichtig ist. Reiner Schmuck wie ein Muster braucht keinen Text.',
    ),
    sources: ['wcag'],
    place: d('Webseite → Bilder'),
    phase: 'website',
    basic: true,
    feature: 'website',
  },
  peering_named: {
    title: d('Namentlich melden oder nur Zahlen?'),
    text: d(
      'Zahlen reichen für Beiträge und Statistik, namentliche Meldungen braucht der Verband etwa für Ehrungen oder Startberechtigungen. Namen dürfen nur fließen, wenn Satzung oder Mitgliedschaft im Verband das vorsehen (Art. 6 Abs. 1 lit. b DSGVO) und nicht mehr als nötig (Art. 5 Abs. 1 lit. c DSGVO). Nenn den Verband außerdem in den Datenschutzhinweisen als Empfänger.',
    ),
    sources: ['dsgvo'],
    place: d('Einstellungen → Verbund'),
    phase: 'website',
  },
  unit_self_managed: {
    title: d('Soll sich die Untereinheit selbst verwalten?'),
    text: d(
      'Selbst verwaltet arbeiten die Rolleninhaber der Untereinheit mit eigenem Zugang und entlasten den Vorstand darüber. Jeder weitere Zugang heißt aber: mehr Personen sehen Mitgliederdaten, und jemand muss die Rechte pflegen (Art. 5 Abs. 1 lit. f, Art. 32 DSGVO). Schalte es ein, wenn die Untereinheit wirklich eigene Aufgaben hat, etwa Mitglieder betreuen oder Termine planen.',
    ),
    sources: ['dsgvo'],
    place: d('Untereinheiten → Bearbeiten → Verwaltung'),
    phase: 'setup',
  },

  // --- Wettbewerbe (Ralf 2026-11-01: „Alles wie in der Liste“) ---
  comp_own: {
    title: d('Eigener oder fremder Wettbewerb?'),
    text: d(
      'Beim eigenen Wettbewerb erfasst ihr Schützen und Werte selbst, und HUBIplan rechnet Plätze, Zugwertung und Stechen. Beim fremden tragt ihr nur ein, was der Ausrichter bekannt gegeben hat: Platz und Wert eurer Teilnehmer. Wie dort gewertet wird, regelt die Schießordnung des Ausrichters (§ 25 BGB).',
    ),
    sources: ['bgb'],
    place: d('Wettbewerbe → Neuer Wettbewerb'),
    phase: 'competitions',
    feature: 'competitions',
  },
  comp_shots: {
    title: d('Wozu Schusszahl und Höchstwert je Schuss?'),
    text: d(
      'Mit gewerteten Schüssen und Höchstwert weist HUBIplan unmögliche Werte beim Erfassen ab, etwa 31 bei 3 gewerteten Schüssen mit höchstens 10. So fallen Tippfehler am Stand auf, bevor sie Plätze verschieben. Die Zahlen stehen in der Schießordnung des Vereins oder in der DSB-Sportordnung.',
    ),
    sources: ['dsbSpo'],
    place: d('Wettbewerb → Einrichten → Einzelwertung'),
    phase: 'competitions',
    feature: 'competitions',
  },
  comp_target: {
    title: d('Wozu Scheibe und Wertungsart?'),
    text: d(
      'Kennt HUBIplan die Scheibe, rechnet es aus jedem Trefferpunkt Ring, Zehntel, Innenzehner und Teiler nach der DSB-Sportordnung: Berührt der Lochrand die Ringlinie, zählt der höhere Ring. Ohne erfasste Treffer bleibt alles wie bisher, ihr gebt die Summe ein, und bei Gleichstand entscheidet das Stechen. Die Ergebnisse sind vereinsintern, nicht amtlich.',
    ),
    sources: ['dsbSpo'],
    place: d('Wettbewerb → Einrichten → Einzelwertung'),
    phase: 'competitions',
    feature: 'competitions',
  },
  comp_team_mode: {
    title: d('Warum zählen nur die besten Schützen einer Einheit?'),
    text: d(
      'Mit „Summe der besten 5“ gewinnt ein großer Zug nicht schon durch mehr Schützen, und schwache Ergebnisse ziehen niemanden herunter. Ein Zug mit weniger als 5 Schützen wird deshalb nicht gewertet, sonst stünde er gegen volle Züge schlechter da. Auch die DSB-Sportordnung wertet Mannschaften mit fester Schützenzahl.',
    ),
    sources: ['dsbSpo'],
    place: d('Wettbewerb → Einrichten → Wertung der Untereinheiten'),
    phase: 'competitions',
    feature: 'competitions',
  },
  comp_prize_places: {
    title: d('Wozu Preisplätze?'),
    text: d(
      'Nur auf Preisplätzen entscheidet ein Gleichstand über einen Preis, deshalb verlangt HUBIplan nur dort ein Stechen; darunter teilen sich Gleichstände den Platz. Wie viele Plätze einen Preis bekommen, steht in der Ausschreibung. Ein öffentlich ausgeschriebener Preis ist eine Auslobung, an die der Verein gebunden ist (§§ 657, 661 BGB).',
    ),
    sources: ['bgb'],
    place: d('Wettbewerb → Einrichten → Wertung'),
    phase: 'competitions',
    feature: 'competitions',
  },
  comp_shootoff_rules: {
    title: d('Warum die Stechregeln erst beim Anlegen?'),
    text: d(
      'Ob 1 oder 3 Schuss gestochen werden, entscheidet oft die Schießleitung am Stand. HUBIplan schlägt die Regel aus „Einrichten“ vor; ändern geht, bis der erste Wert eingetragen ist, sonst würden sich die Bedingungen mitten im Stechen ändern. Für Verbandswettkämpfe regelt die DSB-Sportordnung das Stechen, im Verein die eigene Schießordnung.',
    ),
    sources: ['dsbSpo'],
    place: d('Wettbewerb → Auswertung oder Standmodus → Stechen anlegen'),
    phase: 'competitions',
    feature: 'competitions',
  },
  comp_provisional: {
    title: d('Wann ist das Schießen beendet?'),
    text: d(
      'HUBIplan erkennt das Ende nicht selbst, denn Nachzügler, Fehlende und Stechen kennt nur die Schießleitung. „Schießen beenden“ kennzeichnet die Ergebnisse als vorläufig, Nachträge und Stechen bleiben möglich. Gebt vorläufige Listen nur mit diesem Hinweis heraus, damit niemand sie für richtig und fertig hält (Art. 5 Abs. 1 lit. d DSGVO).',
    ),
    sources: ['dsgvo'],
    place: d('Wettbewerb → Einrichten → Zustand; Standmodus → Abschluss'),
    phase: 'competitions',
    feature: 'competitions',
  },
  comp_final: {
    title: d('Was bedeutet endgültig abschließen?'),
    text: d(
      'Danach sind Eingaben gesperrt, und nur endgültige Ergebnisse sind für Webseite und Ehrungen gedacht. Offene Stechen sperren den Abschluss, weil sonst Plätze ungeklärt blieben. Veröffentlichte Ergebnisse müssen sachlich richtig sein (Art. 5 Abs. 1 lit. d DSGVO), „Wieder öffnen“ bleibt für Korrekturen.',
    ),
    sources: ['dsgvo'],
    place: d('Wettbewerb → Einrichten → Zustand'),
    phase: 'competitions',
    feature: 'competitions',
  },
  comp_reset: {
    title: d('Was passiert beim Zurücksetzen?'),
    text: d(
      'Zurücksetzen löscht alle erfassten Werte, Stechen, Schüsse und gefallenen Pfänder; Regeln, Pfänder, Standzugang und Termin bleiben. Tablets, die ohne Empfang noch alte Eingaben gespeichert haben, verwerfen sie beim nächsten Abgleich. Ob ein Durchgang wiederholt wird, regelt die Schießordnung (§ 25 BGB), rückgängig machen lässt es sich nicht.',
    ),
    sources: ['bgb'],
    place: d('Wettbewerb → Einrichten → Zustand'),
    phase: 'competitions',
    feature: 'competitions',
  },
  comp_stand_access: {
    title: d('Warum ein Standzugang statt Anmeldung?'),
    text: d(
      'Ein geliehenes Tablet bekommt einen eigenen Schlüssel, der nur diesen Wettbewerb erfassen kann und am Ende des Wettbewerbstags abläuft. So gibt niemand sein Passwort auf einem fremden Gerät ein, und das Tablet sieht nur Name und Untereinheit (Art. 5 Abs. 1 lit. c, Art. 32 DSGVO). Geht ein Gerät verloren, beende den Zugang sofort.',
    ),
    sources: ['dsgvo'],
    place: d('Wettbewerb → Erfassen → Anderes Gerät per QR-Code'),
    phase: 'competitions',
    feature: 'competitions',
  },
  comp_lots: {
    title: d('Wozu „Lose im Hut“?'),
    text: d(
      'Ohne diese Angabe zieht „Nummer ziehen“ nur bis zur Zahl der bisherigen Schützen, und ein Nachzügler bekommt meist die nächste Nummer. Mit der Zahl der Lose im Hut zieht HUBIplan wie aus einem echten Hut; wer lieber alle zugleich auslost, nimmt „Alle ohne Nummer auslosen“. Wie die Reihenfolge bestimmt wird, regelt die Schießordnung (§ 25 BGB).',
    ),
    sources: ['bgb'],
    place: d('Wettbewerb → Einrichten → Vogelschießen'),
    phase: 'competitions',
    feature: 'competitions',
  },
  comp_bird_rules: {
    title: d('Ausscheiden und feste Reihenfolge?'),
    text: d(
      'Scheidet aus, wer ein Pfand errungen hat, kommen mehr Schützen zu einem Preis. In fester Reihenfolge wird Pfand für Pfand geschossen, und HUBIplan bietet nach jedem Treffer gleich das nächste an. Welche Regel gilt, steht in der Schießordnung des Vereins (§ 25 BGB).',
    ),
    sources: ['bgb'],
    place: d('Wettbewerb → Einrichten → Vogelschießen'),
    phase: 'competitions',
    feature: 'competitions',
  },
  comp_website: {
    title: d('Ergebnisse auf der Webseite?'),
    text: d(
      'Namen mit Ergebnissen zu zeigen stützt sich meist auf das berechtigte Interesse des Vereins (Art. 6 Abs. 1 lit. f DSGVO); Mitglieder können widersprechen (Art. 21 DSGVO), bei Minderjährigen fragt die Eltern. Für Fotos der Sieger gelten zusätzlich §§ 22 und 23 KUG. „Nach Abschluss“ zeigt nur geprüfte Ergebnisse, „live“ auch Zwischenstände.',
    ),
    sources: ['dsgvo', 'kug'],
    place: d('Wettbewerb → Einrichten → Auf der Webseite'),
    phase: 'competitions',
    feature: 'competitions',
  },
} satisfies Record<string, Decision>

export type DecisionKey = keyof typeof DECISIONS_DATA
export const DECISIONS: Record<DecisionKey, Decision> = DECISIONS_DATA

// --- Begriffe („?“) ---

export const SECTIONS = {
  members: { de: 'Mitglieder' },
  invoices: { de: 'Beiträge und Rechnungen' },
  sepa: { de: 'SEPA-Lastschrift' },
  cash: { de: 'Kasse und Abschluss' },
  tax: { de: 'Steuer' },
  law: { de: 'Recht und Datenschutz' },
  donations: { de: 'Spenden' },
  web: { de: 'Webseite' },
  competitions: { de: 'Wettbewerbe' },
} satisfies Record<string, Text>
export type SectionKey = keyof typeof SECTIONS

export interface TermEntry {
  /** Kurzzeichen, falls üblich (z. B. „IBAN“) */
  symbol?: string
  name: Text
  meaning: Text
  example: Text
  sources: SourceKey[]
  section: SectionKey
  /** einfache Begriffe: „?“ nur beim ersten Vorkommen pro Seite */
  simple?: boolean
  feature?: Feature
}

const TERMS_DATA = {
  member_type: {
    name: d('Mitgliedsart'),
    meaning: d(
      'Gruppe von Mitgliedern mit gleichen Regeln, etwa „aktiv“, „passiv“ oder „Jugend“. Sie bestimmt Beitrag, Meldung an den Dachverband und ob die Zeit für die Mitgliedsdauer zählt (§ 58 Nr. 2 BGB).',
    ),
    example: d(
      'Beispiel: „Passiv“ mit 36,00 € Jahresbeitrag statt 72,00 € für „Aktiv“: Wer nicht mehr aktiv mitmacht, zahlt die Hälfte.',
    ),
    sources: ['bgb'],
    section: 'members',
  },
  active_passive: {
    name: d('aktiv / passiv'),
    meaning: d(
      'Kennzeichen einer Mitgliedsart: aktive Mitglieder nehmen voll am Vereinsleben teil, passive unterstützen vor allem mit ihrem Beitrag. Was das für Rechte und Beitrag bedeutet, regelt die Satzung (§ 25 BGB).',
    ),
    example: d(
      'Beispiel: 112 aktive und 38 passive Mitglieder: Der Dachverband berechnet seinen Beitrag für beide Gruppen getrennt.',
    ),
    sources: ['bgb'],
    section: 'members',
  },
  membership_duration: {
    name: d('Mitgliedsdauer'),
    meaning: d(
      'Summe der Zeiten, in denen jemand Mitglied war, ohne Lücken zwischen Austritt und Wiedereintritt. Es zählen nur Mitgliedsarten mit dem Kennzeichen „zählt für Dauer“ (§ 25 BGB).',
    ),
    example: d(
      'Beispiel: 1998 bis 2010 und wieder ab 2014 ergibt im Jahr 2026 zusammen 24 Jahre, das 25-jährige Jubiläum folgt 2027.',
    ),
    sources: ['bgb'],
    section: 'members',
  },
  federation_number: {
    symbol: 'Verbandsnr.',
    name: d('Verbandsnummer'),
    meaning: d(
      'Nummer, unter der der Dachverband ein Mitglied führt, damit Meldungen und Ehrungen eindeutig zugeordnet werden. Sie gehört zu den Daten, die an den Dachverband gehen (Art. 5 Abs. 1 lit. c DSGVO).',
    ),
    example: d(
      'Beispiel: Verbandsnr. 1920-0457: dasselbe Mitglied, auch wenn es den Zug wechselt.',
    ),
    sources: ['dsgvo'],
    section: 'members',
  },
  cutoff_date: {
    name: d('Stichtag'),
    meaning: d(
      'Der Tag, für den ein Stand gezählt oder berechnet wird, z. B. Mitglieder, Alter oder Kontostand. Wer an diesem Tag Mitglied ist, zählt mit (§ 259 Abs. 1 BGB).',
    ),
    example: d(
      'Beispiel: Stichtag 1. Januar 2026, 150 Mitglieder: Wer am 2. Januar eintritt, zählt erst beim nächsten Stichtag.',
    ),
    sources: ['bgb'],
    section: 'members',
    simple: true,
  },
  fee_run: {
    name: d('Beitragslauf'),
    meaning: d(
      'Erzeugt die Beitragsrechnungen für einen Zeitraum auf einmal, nach den Beitragsregeln jedes Mitglieds. Grundlage ist die Beitragspflicht aus Satzung oder Beitragsordnung (§ 58 Nr. 2 BGB).',
    ),
    example: d(
      'Beispiel: Beitragslauf 2026 mit 142 Rechnungen über zusammen 9.360,00 €: ein Klick statt 142 einzelner Rechnungen.',
    ),
    sources: ['bgb'],
    section: 'invoices',
    feature: 'billing',
  },
  collective_invoice: {
    name: d('Sammelrechnung'),
    meaning: d(
      'Eine Rechnung an eine Untereinheit, die die Beiträge ihrer Mitglieder gesammelt zahlt, statt jedem Mitglied einzeln. Die Untereinheit zieht die Beiträge dann selbst ein (§ 58 Nr. 2 BGB).',
    ),
    example: d(
      'Beispiel: Sammelrechnung Jägerzug: 18 Mitglieder, 1.296,00 €: Der Zug überweist einen Betrag für alle.',
    ),
    sources: ['bgb'],
    section: 'invoices',
    feature: 'billing',
  },
  due_date: {
    name: d('fällig'),
    meaning: d(
      'Ab der Fälligkeit darf der Verein die Zahlung verlangen; sie ergibt sich aus Rechnungsdatum und Zahlungsziel. Spätestens 30 Tage danach gerät ein Mitglied in Verzug, wenn die Rechnung darauf hinweist (§§ 271, 286 Abs. 3 BGB).',
    ),
    example: d('Beispiel: Rechnung vom 1. März, Zahlungsziel 14 Tage, also fällig am 15. März.'),
    sources: ['bgb'],
    section: 'invoices',
    simple: true,
    feature: 'billing',
  },
  outstanding: {
    name: d('offen'),
    meaning: d(
      'Der Teil einer Rechnung, der noch nicht bezahlt ist: Rechnungsbetrag abzüglich aller erfassten Zahlungen. Das Mitglied schuldet diesen Rest weiter (§ 362 Abs. 1 BGB).',
    ),
    example: d(
      'Beispiel: Rechnung 72,00 €, gezahlt 36,00 €, offen 36,00 €: die Hälfte fehlt noch.',
    ),
    sources: ['bgb'],
    section: 'invoices',
    simple: true,
    feature: 'billing',
  },
  overdue: {
    name: d('überfällig'),
    meaning: d(
      'Eine Rechnung, deren Fälligkeit vorbei ist und auf der noch etwas offen ist. Ob das Mitglied schon in Verzug ist, hängt zusätzlich von Mahnung oder Hinweis auf der Rechnung ab (§ 286 BGB).',
    ),
    example: d(
      'Beispiel: 9 von 142 Rechnungen überfällig, zusammen 648,00 €: Zeit für die Erinnerung.',
    ),
    sources: ['bgb'],
    section: 'invoices',
    feature: 'billing',
  },
  dunning_level: {
    name: d('Mahnstufe'),
    meaning: d(
      'Stufe im Mahnablauf, die eine bestimmte Zahl von Tagen nach der Fälligkeit erreicht wird, mit eigenem Text und gegebenenfalls Gebühr. Mit der ersten Mahnung nach Fälligkeit gerät das Mitglied in Verzug (§ 286 Abs. 1 BGB).',
    ),
    example: d(
      'Beispiel: Erinnerung nach 14 Tagen ohne Gebühr, 1. Mahnung nach 28 Tagen mit 2,50 € Porto.',
    ),
    sources: ['bgb'],
    section: 'invoices',
    feature: 'billing',
  },
  mandate: {
    name: d('SEPA-Mandat'),
    meaning: d(
      'Die Erlaubnis des Zahlers, dass der Verein Beträge von seinem Konto einzieht, und zugleich die Weisung an seine Bank, die Lastschrift einzulösen (EPC016-06). Ohne gültiges Mandat darf der Verein nicht einziehen (§ 675j Abs. 1 BGB).',
    ),
    example: d(
      'Beispiel: 104 von 142 Mitgliedern haben ein Mandat erteilt: Bei ihnen kommt der Beitrag ohne Überweisung.',
    ),
    sources: ['epcSdd', 'bgb'],
    section: 'sepa',
    feature: 'billing',
  },
  mandate_reference: {
    name: d('Mandatsreferenz'),
    meaning: d(
      'Eindeutige Kennung eines Mandats beim Verein, bis zu 35 Zeichen. Sie steht auf jeder Lastschrift und Vorabankündigung, damit der Zahler sie zuordnen kann (EPC016-06).',
    ),
    example: d(
      'Beispiel: Mandatsreferenz M-0042: Auf dem Kontoauszug erkennt das Mitglied, zu welchem Mandat der Einzug gehört.',
    ),
    sources: ['epcSdd'],
    section: 'sepa',
    feature: 'billing',
  },
  creditor_id: {
    name: d('Gläubiger-ID'),
    meaning: d(
      'Die Gläubiger-Identifikationsnummer kennzeichnet den Verein als Lastschrift-Einreicher; in Deutschland vergibt sie die Bundesbank auf Antrag. Zusammen mit der Mandatsreferenz macht sie jedes Mandat eindeutig (Bundesbank, EPC016-06).',
    ),
    example: d(
      'Beispiel: DE98ZZZ09999999999: Das „DE“ steht für Deutschland, „ZZZ“ ist ein fester Platzhalter.',
    ),
    sources: ['bbkCi', 'epcSdd'],
    section: 'sepa',
    feature: 'billing',
  },
  prenotification_term: {
    name: d('Vorabankündigung'),
    meaning: d(
      'Mitteilung an den Zahler über Betrag und Datum eines Einzugs, ohne andere Vereinbarung 14 Kalendertage vorher (EPC016-06). Sie kann auch auf der Rechnung stehen oder einmal für mehrere gleiche Einzüge gelten.',
    ),
    example: d(
      'Beispiel: Einzug am 15. März, Ankündigung spätestens am 1. März: Das Mitglied kann für Deckung sorgen.',
    ),
    sources: ['epcSdd'],
    section: 'sepa',
    feature: 'billing',
  },
  mandate_expiry: {
    name: d('Mandat verfallen'),
    meaning: d(
      'Ein Mandat verfällt, wenn 36 Monate lang keine Lastschrift darauf eingezogen wurde. Danach braucht es ein neues Mandat (EPC016-06).',
    ),
    example: d(
      'Beispiel: letzter Einzug im Mai 2023, dann verfallen im Mai 2026: Für den nächsten Beitrag muss das Mitglied neu unterschreiben.',
    ),
    sources: ['epcSdd'],
    section: 'sepa',
    feature: 'billing',
  },
  iban_bic: {
    symbol: 'IBAN / BIC',
    name: d('Kontonummer und Bankkennung'),
    meaning: d(
      'Die IBAN ist die internationale Kontonummer, in Deutschland 22 Zeichen; der BIC kennzeichnet die Bank und ist bei Zahlungen im SEPA-Raum nicht mehr nötig. Eine Prüfziffer in der IBAN fängt die meisten Tippfehler ab (EPC016-06).',
    ),
    example: d(
      'Beispiel: DE02 1203 0000 0000 2020 51: „DE“ für Deutschland, „02“ ist die Prüfziffer.',
    ),
    sources: ['epcSdd'],
    section: 'sepa',
    simple: true,
    feature: 'billing',
  },
  bank_file: {
    symbol: 'pain.008',
    name: d('Datei für die Bank'),
    meaning: d(
      'Die XML-Datei mit allen Lastschriften eines Laufs, die du im Online-Banking hochlädst. Ihr Format legt das SEPA-Regelwerk fest; die Bank zieht danach die Beträge ein (EPC016-06).',
    ),
    example: d(
      'Beispiel: eine Datei mit 104 Lastschriften über 7.488,00 €: einmal hochladen statt 104 Einzelaufträge.',
    ),
    sources: ['epcSdd'],
    section: 'sepa',
    feature: 'billing',
  },
  opening_balance_term: {
    name: d('Anfangsbestand'),
    meaning: d(
      'Geld auf einem Konto oder in der Barkasse zu Beginn des Zeitraums, meist der Endbestand des Vorjahrs. Er ist der Ausgangspunkt jeder Kassenrechnung (§ 259 Abs. 1 BGB).',
    ),
    example: d(
      'Beispiel: Anfangsbestand 4.250,00 € am 1. Januar: So viel lag auf dem Girokonto, bevor das Jahr begann.',
    ),
    sources: ['bgb'],
    section: 'cash',
    feature: 'finance',
  },
  closing_balance: {
    name: d('Endbestand'),
    meaning: d(
      'Geld auf einem Konto am Ende des Zeitraums: Anfangsbestand plus Einnahmen minus Ausgaben, plus oder minus Umbuchungen. Er muss zum Kontoauszug passen (§ 259 Abs. 1 BGB).',
    ),
    example: d(
      'Beispiel: 4.250,00 € + 9.800,00 € − 8.900,00 € = 5.150,00 €: Der Kontoauszug zum 31. Dezember zeigt denselben Betrag.',
    ),
    sources: ['bgb'],
    section: 'cash',
    feature: 'finance',
  },
  transfer: {
    name: d('Umbuchung'),
    meaning: d(
      'Geld wandert zwischen zwei eigenen Konten, etwa von der Barkasse auf das Girokonto. Das ist weder Einnahme noch Ausgabe und ändert das Ergebnis nicht (§ 259 Abs. 1 BGB).',
    ),
    example: d(
      'Beispiel: 600,00 € Kasseneinnahmen vom Fest auf das Girokonto eingezahlt: Kasse −600,00 €, Girokonto +600,00 €, Ergebnis unverändert.',
    ),
    sources: ['bgb'],
    section: 'cash',
    feature: 'finance',
  },
  balance: {
    name: d('Saldo'),
    meaning: d(
      'Differenz von Einnahmen und Ausgaben, etwa je Kategorie. Positiv heißt: mehr eingenommen als ausgegeben (§ 259 Abs. 1 BGB).',
    ),
    example: d(
      'Beispiel: Kategorie Schützenfest: Einnahmen 3.100,00 €, Ausgaben 2.700,00 €, Saldo 400,00 €.',
    ),
    sources: ['bgb'],
    section: 'cash',
    simple: true,
    feature: 'finance',
  },
  result: {
    name: d('Ergebnis'),
    meaning: d(
      'Alle Einnahmen minus alle Ausgaben eines Zeitraums oder einer Veranstaltung, ohne Umbuchungen. Ein negatives Ergebnis heißt, der Verein hat aus Rücklagen oder Beständen zugezahlt (§ 259 Abs. 1 BGB).',
    ),
    example: d(
      'Beispiel: Ergebnis 2026: +900,00 €: Der Verein hat im Jahr 900,00 € mehr eingenommen als ausgegeben.',
    ),
    sources: ['bgb'],
    section: 'cash',
    simple: true,
    feature: 'finance',
  },
  receipt: {
    name: d('Beleg'),
    meaning: d(
      'Nachweis zu einer Buchung, z. B. Rechnung, Quittung oder Kontoauszug. Buchungsbelege sind acht Jahre aufzubewahren (§ 147 Abs. 1 Nr. 4, Abs. 3 AO).',
    ),
    example: d(
      'Beispiel: Buchung 2026-0117 „Getränke Fest“ 412,30 € mit der eingescannten Rechnung des Getränkehändlers.',
    ),
    sources: ['ao'],
    section: 'cash',
    feature: 'finance',
  },
  fiscal_year_term: {
    name: d('Geschäftsjahr'),
    meaning: d(
      'Der Zeitraum, für den der Verein abrechnet und einen Kassenbericht vorlegt, meist das Kalenderjahr. Die Satzung kann ein anderes Jahr festlegen (§ 25 BGB).',
    ),
    example: d(
      'Beispiel: Geschäftsjahr 1. Juli 2025 bis 30. Juni 2026: Das Schützenfest im Juni fällt ans Ende desselben Jahres.',
    ),
    sources: ['bgb'],
    section: 'cash',
    simple: true,
    feature: 'finance',
  },
  cash_report: {
    name: d('Kassenbericht'),
    meaning: d(
      'Zusammenstellung von Anfangs- und Endbestand je Konto sowie Einnahmen und Ausgaben nach Kategorie für ein Geschäftsjahr. Mit ihm legt der Vorstand Rechenschaft gegenüber der Mitgliederversammlung ab (§ 27 Abs. 3, §§ 666, 259 BGB).',
    ),
    example: d(
      'Beispiel: Kassenbericht 2026 auf vier Seiten, unterschrieben von beiden Kassenprüfern, liegt der Jahreshauptversammlung vor.',
    ),
    sources: ['bgb'],
    section: 'cash',
    feature: 'finance',
  },
  auditors: {
    name: d('Kassenprüfer'),
    meaning: d(
      'Von der Mitgliederversammlung gewählte Mitglieder, die die Kasse prüfen und darüber berichten; ihre Aufgaben bestimmt die Satzung. Sie gehören nicht zum Vorstand, den sie prüfen (§ 25 BGB).',
    ),
    example: d(
      'Beispiel: zwei Kassenprüfer prüfen 312 Buchungen stichprobenartig und empfehlen die Entlastung.',
    ),
    sources: ['bgb'],
    section: 'cash',
    feature: 'finance',
  },
  ideal_area: {
    name: d('ideeller Bereich'),
    meaning: d(
      'Die eigentliche Vereinsarbeit für den Satzungszweck, finanziert vor allem durch Beiträge und Spenden. Bei gemeinnützigen Vereinen ist dieser Bereich steuerfrei (§ 52 AO, § 5 Abs. 1 Nr. 9 KStG).',
    ),
    example: d(
      'Beispiel: Mitgliedsbeiträge 9.360,00 € und Spenden 800,00 € gehören in den ideellen Bereich.',
    ),
    sources: ['ao', 'kstg'],
    section: 'tax',
    feature: 'finance',
  },
  asset_management: {
    name: d('Vermögensverwaltung'),
    meaning: d(
      'Einnahmen aus dem Vermögen des Vereins, etwa Zinsen oder langfristige Vermietung, ohne eigenen Geschäftsbetrieb. Bei gemeinnützigen Vereinen bleibt sie steuerfrei (§ 14 Satz 3 AO, § 5 Abs. 1 Nr. 9 KStG).',
    ),
    example: d('Beispiel: 1.200,00 € Pacht im Jahr für die verpachtete Vereinsgaststätte.'),
    sources: ['ao', 'kstg'],
    section: 'tax',
    feature: 'finance',
  },
  purpose_operation: {
    name: d('Zweckbetrieb'),
    meaning: d(
      'Ein Geschäftsbetrieb, der den Satzungszweck unmittelbar verwirklicht und anders nicht zu erreichen ist. Er bleibt steuerbegünstigt wie der ideelle Bereich (§§ 64 Abs. 1, 65 AO).',
    ),
    example: d(
      'Beispiel: Eintritt zum Vereinswettbewerb, 650,00 €: Die Veranstaltung selbst dient dem Vereinszweck.',
    ),
    sources: ['ao'],
    section: 'tax',
    feature: 'finance',
  },
  commercial_operation: {
    symbol: 'wGB',
    name: d('wirtschaftlicher Geschäftsbetrieb'),
    meaning: d(
      'Eine selbstständige, nachhaltige Tätigkeit, mit der der Verein Einnahmen erzielt und die über Vermögensverwaltung hinausgeht (§ 14 AO). Steuer fällt erst an, wenn diese Einnahmen einschließlich Umsatzsteuer 50.000 € im Jahr übersteigen (§ 64 Abs. 3 AO).',
    ),
    example: d(
      'Beispiel: Getränkeverkauf am Schützenfest, 14.000,00 €: steuerpflichtiger Bereich, aber unter der Freigrenze.',
    ),
    sources: ['ao'],
    section: 'tax',
    feature: 'finance',
  },
  vat: {
    symbol: 'USt',
    name: d('Umsatzsteuer'),
    meaning: d(
      'Steuer auf Lieferungen und Leistungen gegen Entgelt, regulär 19 %, ermäßigt 7 % (§ 12 UStG). Echte Mitgliedsbeiträge fallen nicht darunter (UStAE 1.4).',
    ),
    example: d('Beispiel: Werbebande für 500,00 € netto, mit 19 % Umsatzsteuer 595,00 € brutto.'),
    sources: ['ustg', 'ustae'],
    section: 'tax',
    feature: 'billing',
  },
  vat_id: {
    symbol: 'USt-IdNr.',
    name: d('Steuernummer und Umsatzsteuer-Identifikationsnummer'),
    meaning: d(
      'Die Steuernummer vergibt das Finanzamt, die USt-IdNr. das Bundeszentralamt für Steuern. Eine davon gehört auf jede Rechnung mit Umsatzsteuer (§ 14 Abs. 4 Satz 1 Nr. 2 UStG).',
    ),
    example: d('Beispiel: USt-IdNr. DE123456789: „DE“ und neun Ziffern.'),
    sources: ['ustg'],
    section: 'tax',
    feature: 'billing',
  },
  board_26: {
    symbol: '§ 26 BGB',
    name: d('Vorstand nach § 26 BGB'),
    meaning: d(
      'Die Personen, die den Verein gerichtlich und außergerichtlich vertreten; wer dazugehört, bestimmt die Satzung. Sie stehen im Vereinsregister (§§ 26, 64 BGB).',
    ),
    example: d(
      'Beispiel: Laut Satzung vertreten 2 von 3 Vorstandsmitgliedern gemeinsam; die 7 Beisitzer des erweiterten Vorstands nicht.',
    ),
    sources: ['bgb'],
    section: 'law',
  },
  register: {
    name: d('Registergericht und Registernummer'),
    meaning: d(
      'Ein eingetragener Verein steht im Vereinsregister beim Amtsgericht, unter einer Nummer mit „VR“. Beides gehört ins Impressum (§ 21 BGB, § 5 Abs. 1 Nr. 4 DDG).',
    ),
    example: d('Beispiel: Amtsgericht Neuss, VR 1234.'),
    sources: ['bgb', 'ddg'],
    section: 'law',
  },
  deletion_period_term: {
    name: d('Löschfrist'),
    meaning: d(
      'Zeit nach dem Austritt, nach der HUBIplan die Daten eines Mitglieds auf ein Minimum reduziert. Personendaten dürfen nur so lange gespeichert werden, wie es für den Zweck nötig ist (Art. 5 Abs. 1 lit. e DSGVO).',
    ),
    example: d(
      'Beispiel: Austritt am 31. Dezember 2025, Frist 24 Monate: Ab Januar 2028 bleiben nur Name, Geburtsdatum und Zeiten.',
    ),
    sources: ['dsgvo'],
    section: 'law',
  },
  consent: {
    name: d('Einwilligung'),
    meaning: d(
      'Freiwillige, informierte Zustimmung einer Person zu einer bestimmten Verarbeitung ihrer Daten, z. B. für ein Foto. Sie lässt sich jederzeit widerrufen (Art. 6 Abs. 1 lit. a, Art. 7 DSGVO).',
    ),
    example: d(
      'Beispiel: Einwilligung am 12. März erteilt, am 2. Mai widerrufen: Ab dem 2. Mai erscheint das Foto nicht mehr.',
    ),
    sources: ['dsgvo'],
    section: 'law',
  },
  opt_out: {
    name: d('Widerspruch'),
    meaning: d(
      'Ein Mitglied kann Informationsmails wie Rundschreiben abbestellen; HUBIplan schickt sie dann nicht mehr per E-Mail. Gegen Werbung per E-Mail ist ein Widerspruch jederzeit möglich (Art. 21 Abs. 2 und 3 DSGVO).',
    ),
    example: d(
      'Beispiel: 6 von 120 Mitgliedern haben abbestellt: Das Rundschreiben geht an 114 Adressen.',
    ),
    sources: ['dsgvo'],
    section: 'law',
  },
  donation_receipt: {
    name: d('Zuwendungsbestätigung'),
    meaning: d(
      'Bescheinigung des Vereins über eine Spende oder einen abziehbaren Beitrag, nach amtlichem Muster; erst mit ihr kann der Spender den Betrag von der Steuer absetzen (§ 10b Abs. 1 EStG, § 50 Abs. 1 EStDV). Umgangssprachlich heißt sie Spendenquittung.',
    ),
    example: d(
      'Beispiel: Frau Muster spendet im Jahr 3 × 50 €: Im Januar bekommt sie eine Sammelbestätigung über 150 €.',
    ),
    sources: ['estg', 'estdv'],
    section: 'donations',
    feature: 'finance',
  },
  exemption_notice: {
    name: d('Freistellungsbescheid'),
    meaning: d(
      'Bescheid des Finanzamts, dass der Verein wegen Gemeinnützigkeit von der Körperschaftsteuer befreit ist, meist als Anlage zum Körperschaftsteuerbescheid (§ 5 Abs. 1 Nr. 9 KStG). Er kommt nach der Steuererklärung, in der Regel alle drei Jahre.',
    ),
    example: d(
      'Beispiel: Bescheid vom 14. März 2024 über die Jahre 2021 bis 2023: Bestätigungen sind bis 14. März 2029 möglich.',
    ),
    sources: ['kstg', 'ao'],
    section: 'donations',
    feature: 'finance',
  },
  statute_notice: {
    name: d('Feststellung nach § 60a AO'),
    meaning: d(
      'Bescheid, dass die Satzung die Voraussetzungen der Gemeinnützigkeit erfüllt (§ 60a AO). Neu gegründete Vereine bekommen ihn, bevor es den ersten Freistellungsbescheid gibt.',
    ),
    example: d(
      'Beispiel: Feststellung vom 2. Mai 2025: HUBIplan stellt Bestätigungen bis 2. Mai 2028 aus.',
    ),
    sources: ['ao'],
    section: 'donations',
    feature: 'finance',
  },
  simplified_proof: {
    name: d('Vereinfachter Zuwendungsnachweis'),
    meaning: d(
      'Bis 300 € genügt dem Spender statt einer Zuwendungsbestätigung der Kontoauszug, wenn er zusätzlich einen Beleg des Vereins mit Zweck und Angaben zur Steuerbefreiung aufbewahrt (§ 50 Abs. 4 Satz 1 Nr. 2 Buchst. b EStDV). Der Verein darf trotzdem eine Bestätigung ausstellen.',
    ),
    example: d(
      'Beispiel: 50 € Spende per Überweisung: Kontoauszug und der Spendenbeleg aus dem Vereinsheft reichen.',
    ),
    sources: ['estdv'],
    section: 'donations',
    feature: 'finance',
  },
  expense_donation: {
    name: d('Aufwandsspende'),
    meaning: d(
      'Jemand verzichtet auf die Erstattung von Auslagen, die ihm der Verein schuldet; der Verzicht gilt dann als Geldspende (§ 10b Abs. 3 Satz 5 und 6 EStG).',
    ),
    example: d(
      'Beispiel: 120 km Fahrt zum Verbandstag zu 0,30 € nach Reisekostenregelung, also 36 €, und der Kassierer bestätigt 36 € als Spende.',
    ),
    sources: ['estg'],
    section: 'donations',
    feature: 'finance',
  },
  cash_receipt: {
    name: d('Quittung'),
    meaning: d(
      'Schriftliche Bestätigung, dass Geld empfangen wurde; wer Geld bekommt, muss sie auf Verlangen ausstellen (§ 368 BGB). Für die Kasse ist sie zugleich der Beleg zur Buchung.',
    ),
    example: d(
      'Beispiel: Ein Mitglied zahlt 40 € Beitrag bar beim Schützenfest und bekommt Quittung Q-2026-0012.',
    ),
    sources: ['bgb'],
    section: 'cash',
    feature: 'finance',
  },
  camt: {
    symbol: 'CAMT.053',
    name: d('Elektronischer Kontoauszug'),
    meaning: d(
      'Kontoauszug als Datei im Format camt.053 nach ISO 20022, den fast jedes Online-Banking anbietet; anders als eine CSV-Datei enthält er eindeutige Angaben wie IBAN, Verwendungszweck und Endsaldo.',
    ),
    example: d('Beispiel: Auszug Oktober mit 37 Umsätzen und Endsaldo 4.812,55 € als XML-Datei.'),
    sources: ['dkCamt'],
    section: 'cash',
    feature: 'finance',
  },
  return_debit: {
    name: d('Rücklastschrift'),
    meaning: d(
      'Lastschrift, die zurückkommt, etwa weil das Konto nicht gedeckt ist oder das Mitglied widerspricht; einer autorisierten Lastschrift kann es bis acht Wochen nach Belastung widersprechen (§ 675x Abs. 2 und 4 BGB, EPC-Regelwerk). Oft kommen Bankgebühren dazu.',
    ),
    example: d(
      'Beispiel: Beitrag 60 € eingezogen am 1. März, zurück am 6. März mit Grund „AM04“ (Konto nicht gedeckt) und 3 € Gebühr.',
    ),
    sources: ['bgb', 'epcSdd'],
    section: 'sepa',
    feature: 'billing',
  },
  imprint: {
    name: d('Impressum'),
    meaning: d(
      'Pflichtangaben zum Anbieter einer Webseite: Name, Anschrift, Vertretungsberechtigte, Kontakt und, falls eingetragen, Register und Nummer (§ 5 DDG). Es muss von jeder Seite aus leicht erreichbar sein.',
    ),
    example: d(
      'Beispiel: Ein Link „Impressum“ im Fuß jeder Seite, nicht mehr als 2 Klicks entfernt.',
    ),
    sources: ['ddg'],
    section: 'web',
    feature: 'website',
  },
  responsible: {
    name: d('Verantwortlich für den Inhalt'),
    meaning: d(
      'Person, die für journalistisch-redaktionelle Inhalte wie Berichte und Neuigkeiten einsteht, mit Name und Anschrift (§ 18 Abs. 2 MStV). Meist ist das der oder die Vorsitzende oder die Pressewartin.',
    ),
    example: d(
      'Beispiel: „Verantwortlich nach § 18 Abs. 2 MStV: Erika Muster, Hauptstraße 1, 41468 Neuss“.',
    ),
    sources: ['mstv'],
    section: 'web',
    feature: 'website',
  },
  e_invoice: {
    name: d('E-Rechnung'),
    meaning: d(
      'Rechnung in einem strukturierten Datenformat (XRechnung oder ZUGFeRD), die ein Programm lesen kann; ein PDF allein ist keine E-Rechnung (§ 14 Abs. 1 UStG). Seit 2025 muss jeder Unternehmer sie empfangen können, auch ein Verein mit wirtschaftlichem Geschäftsbetrieb.',
    ),
    example: d(
      'Beispiel: Die Brauerei schickt Rechnung RE-2026-0815 über 1.190,00 € als XML-Datei; HUBIplan liest Betrag und Datum aus und bewahrt die Datei als Beleg auf.',
    ),
    sources: ['ustg'],
    section: 'cash',
    feature: 'finance',
  },
  cash_count_term: {
    name: d('Kassensturz'),
    meaning: d(
      'Zählen des Bargelds und Vergleich mit dem Bestand laut Kassenbuch. Die Kasse muss jederzeit so prüfbar sein (§ 146 Abs. 1 AO).',
    ),
    example: d(
      'Beispiel: Gezählt 412,30 €, laut Kassenbuch 415,00 €: Die Differenz von 2,70 € wird mit Grund gebucht.',
    ),
    sources: ['ao'],
    section: 'cash',
    feature: 'finance',
  },
  open_till: {
    name: d('offene Ladenkasse'),
    meaning: d(
      'Bargeldkasse ohne Registrierkasse, etwa am Getränkestand; die Tageseinnahme wird am Ende aus dem gezählten Bestand zurückgerechnet (§ 146 Abs. 1 AO). Dafür braucht es ein Zählprotokoll.',
    ),
    example: d(
      'Beispiel: Endbestand 1.850,00 €, Wechselgeld 200,00 €, bar bezahltes Eis 50,00 €: Tageseinnahme 1.700,00 €.',
    ),
    sources: ['ao'],
    section: 'cash',
    feature: 'finance',
  },
  reserve: {
    name: d('Rücklage'),
    meaning: d(
      'Teil der Mittel, den der Verein für einen Zweck zurücklegt, ohne Geld zu bewegen (§ 62 AO). Er steht dann nicht mehr frei zur Verfügung.',
    ),
    example: d(
      'Beispiel: 3.000,00 € von 8.000,00 € auf den Konten sind als „Rücklage Festzelt“ gebunden, frei verfügbar sind 5.000,00 €.',
    ),
    sources: ['ao'],
    section: 'tax',
    feature: 'finance',
  },
  data_access: {
    name: d('Datenträgerüberlassung'),
    meaning: d(
      'Das Finanzamt darf bei einer Prüfung die Buchhaltung als maschinell auswertbare Dateien verlangen (§ 147 Abs. 6 AO). Der Datenexport liefert dafür alle Tabellen, Belege und eine Beschreibung (index.xml).',
    ),
    example: d(
      'Beispiel: Für die Prüfung 2025 lädt der Kassierer „Kasse-2025-Export.zip“ herunter und gibt die Datei dem Prüfer auf einem USB-Stick.',
    ),
    sources: ['ao', 'gobd'],
    section: 'cash',
    feature: 'finance',
  },
  retention_period: {
    name: d('Aufbewahrungsfrist'),
    meaning: d(
      'Zeit, in der Kassenunterlagen aufbewahrt werden müssen: Belege 8 Jahre, Bücher und Abschlüsse 10 Jahre, jeweils ab Ende des Kalenderjahres (§ 147 Abs. 3 und 4 AO).',
    ),
    example: d(
      'Beispiel: Belege aus 2025 dürfen ab dem 1.1.2034 gelöscht werden, die Buchungen von 2025 ab dem 1.1.2036 anonymisiert.',
    ),
    sources: ['ao'],
    section: 'cash',
    feature: 'finance',
  },
  chained_log: {
    name: d('verkettetes Protokoll'),
    meaning: d(
      'Jeder Eintrag im Änderungsprotokoll enthält eine Prüfsumme seines Vorgängers; wird einer geändert oder gelöscht, passt die Kette nicht mehr. So bleibt nachweisbar, dass Änderungen nicht unterdrückt wurden (§ 146 Abs. 4 AO, GoBD).',
    ),
    example: d(
      'Beispiel: Eintrag Nr. 1205 verweist auf die Prüfsumme von Nr. 1204; fehlt Nr. 1204, meldet die tägliche Prüfung „Nr. 1204 bis 1204 fehlen“.',
    ),
    sources: ['ao', 'gobd'],
    section: 'law',
  },
  // --- Wettbewerbe ---
  comp_shootoff: {
    name: d('Stechen'),
    meaning: d(
      'Zusätzliches Schießen bei Gleichstand auf einem Preisplatz, mit eigenen Regeln für Schusszahl und Wertung. Steht es danach wieder gleich, folgt ein weiteres Stechen; die Regeln stehen in der Schießordnung oder der DSB-Sportordnung.',
    ),
    example: d(
      'Beispiel: Anna und Paul haben beide 28 Ringe für Platz 1; im Stechen mit 1 Schuss schießt Anna 9, Paul 8, Anna wird Erste.',
    ),
    sources: ['dsbSpo'],
    section: 'competitions',
    feature: 'competitions',
  },
  comp_tie: {
    name: d('Gleichstand'),
    meaning: d(
      'Zwei oder mehr Schützen haben denselben Wert. Sie teilen sich den Platz, auf Preisplätzen entscheidet ein Stechen (Schießordnung des Vereins, DSB-Sportordnung).',
    ),
    example: d(
      'Beispiel: Zweimal 27 Ringe ergibt zweimal Platz 2, der nächste Schütze ist Vierter.',
    ),
    sources: ['dsbSpo'],
    section: 'competitions',
    feature: 'competitions',
  },
  comp_prize_place: {
    name: d('Preisplatz'),
    meaning: d(
      'Platz, für den es laut Ausschreibung einen Preis gibt, etwa die ersten drei. Nur hier braucht ein Gleichstand ein Stechen (§ 661 BGB).',
    ),
    example: d(
      'Beispiel: Bei 3 Preisplätzen muss ein Gleichstand auf Platz 3 gestochen werden, einer auf Platz 4 nicht.',
    ),
    sources: ['bgb'],
    section: 'competitions',
    feature: 'competitions',
  },
  comp_counted: {
    name: d('gewertete Schüsse'),
    meaning: d(
      'Die Schüsse, deren Ringe in den Wert eingehen; die übrigen sind Probe- oder Streichschüsse. Wie viele zählen, legt die Schießordnung des Vereins oder die DSB-Sportordnung fest.',
    ),
    example: d(
      'Beispiel: 5 Schuss, davon 3 gewertet: Wer 9, 10, 8, 10, 7 schießt, hat mit den besten drei 29 Ringe, wenn die Ordnung die besten zählt.',
    ),
    sources: ['dsbSpo'],
    section: 'competitions',
    feature: 'competitions',
  },
  comp_unit_scoring: {
    name: d('Wertung der Untereinheiten'),
    meaning: d(
      'Wertung der Züge oder Abteilungen aus den Einzelergebnissen ihrer Schützen, etwa als Summe der besten 5 (Zugwertung). Einheiten mit zu wenigen Schützen bleiben ungewertet, wie bei Mannschaften nach der DSB-Sportordnung.',
    ),
    example: d('Beispiel: Zug 1 mit 28, 27, 25, 24, 22 und 20 Ringen hat bei „beste 5“ 126 Ringe.'),
    sources: ['dsbSpo'],
    section: 'competitions',
    feature: 'competitions',
  },
  comp_ooc: {
    name: d('außer Konkurrenz'),
    meaning: d(
      'Der Schütze schießt mit und erscheint in der Liste, bekommt aber keinen Platz und keinen Preis. Üblich etwa für Schießleiter oder Gäste aus Nachbarvereinen (§ 25 BGB, Schießordnung).',
    ),
    example: d(
      'Beispiel: Der Schießleiter schießt 30 Ringe außer Konkurrenz; Platz 1 geht an die Beste mit 28.',
    ),
    sources: ['bgb'],
    section: 'competitions',
    simple: true,
    feature: 'competitions',
  },
  comp_guest: {
    name: d('Gast'),
    meaning: d(
      'Teilnehmer, der nicht Mitglied ist; von ihm speichert HUBIplan nur Name und Verein (Art. 5 Abs. 1 lit. c DSGVO). Ob Gäste um Preise schießen dürfen, regelt die Ausschreibung.',
    ),
    example: d(
      'Beispiel: „Gerd Gast, SV Nachbarort“ schießt 26 Ringe mit; für die Zugwertung kann er einer Untereinheit zugeordnet werden.',
    ),
    sources: ['dsgvo'],
    section: 'competitions',
    simple: true,
    feature: 'competitions',
  },
  comp_lot: {
    name: d('Losnummer'),
    meaning: d(
      'Nummer aus dem Hut, die beim Vogelschießen die Reihenfolge der Schützen bestimmt. Nachzügler ziehen eine noch freie Nummer; das Verfahren regelt die Schießordnung (§ 25 BGB).',
    ),
    example: d('Beispiel: Wer Los 7 zieht, schießt nach Nummer 6 und vor Nummer 8.'),
    sources: ['bgb'],
    section: 'competitions',
    feature: 'competitions',
  },
  comp_prize: {
    name: d('Pfand'),
    meaning: d(
      'Teil des Vogels, für dessen Abschuss es einen Preis gibt, etwa Kopf, Flügel oder Schweif. Wer es herunterholt, hat das Pfand errungen; Pfänder und Preise legt die Schießordnung fest (§ 25 BGB).',
    ),
    example: d(
      'Beispiel: Paul holt mit Schuss 54 den linken Flügel herunter und erhält den Flügelorden.',
    ),
    sources: ['bgb'],
    section: 'competitions',
    feature: 'competitions',
  },
  comp_round: {
    name: d('Runde'),
    meaning: d(
      'Ein Durchgang durch alle Losnummern; danach beginnt die nächste Runde wieder bei der kleinsten Nummer. Fehlende und Ausgeschiedene werden übersprungen (Schießordnung, § 25 BGB).',
    ),
    example: d('Beispiel: Bei 40 Schützen beginnt mit dem 41. Schuss die zweite Runde.'),
    sources: ['bgb'],
    section: 'competitions',
    feature: 'competitions',
  },
  comp_shots_for: {
    name: d('Schüsse für das Pfand'),
    meaning: d(
      'Schüsse seit dem vorher gefallenen Pfand bis zu dem, der dieses Pfand heruntergeholt hat. Beim ersten Pfand zählen alle Schüsse seit Beginn; wofür es Preise gibt, regelt die Schießordnung (§ 25 BGB).',
    ),
    example: d(
      'Beispiel: Der Kopf fällt mit Schuss 30, der Schweif mit Schuss 75: für den Schweif waren es 45 Schüsse.',
    ),
    sources: ['bgb'],
    section: 'competitions',
    feature: 'competitions',
  },
  comp_provisional_term: {
    name: d('vorläufig'),
    meaning: d(
      'Zustand nach „Schießen beenden“: Ergebnisse stehen, Nachträge und Stechen sind noch möglich. Listen tragen den Hinweis „vorläufig“, damit niemand sie für fertig hält (Art. 5 Abs. 1 lit. d DSGVO).',
    ),
    example: d(
      'Beispiel: Am Abend hängt die vorläufige Liste aus; ein Stechen am nächsten Morgen ändert noch Platz 3.',
    ),
    sources: ['dsgvo'],
    section: 'competitions',
    feature: 'competitions',
  },
  comp_final_term: {
    name: d('endgültig'),
    meaning: d(
      'Zustand nach dem Abschluss: Eingaben sind gesperrt, die Ergebnisse gelten. Nur endgültige Ergebnisse sind für Webseite und Ehrungen gedacht (Art. 5 Abs. 1 lit. d DSGVO).',
    ),
    example: d(
      'Beispiel: Nach dem 2. Stechen schließt der Schießmeister ab, danach lässt sich kein Wert mehr ändern.',
    ),
    sources: ['dsgvo'],
    section: 'competitions',
    feature: 'competitions',
  },
  comp_stand_mode: {
    name: d('Standmodus'),
    meaning: d(
      'Vollbildansicht für Tablet oder Handy am Schießstand, mit großer Suche und Eingabe; sie arbeitet auch ohne Empfang weiter. Sie zeigt nur, was zum Erfassen nötig ist (Art. 5 Abs. 1 lit. c DSGVO), und sendet, sobald wieder Verbindung besteht.',
    ),
    example: d(
      'Beispiel: Am Stand tippt die Aufsicht „Mül“, wählt Jürgen Müller und trägt 27 ein.',
    ),
    sources: ['dsgvo'],
    section: 'competitions',
    feature: 'competitions',
  },
  comp_stand_access_term: {
    name: d('Standzugang'),
    meaning: d(
      'Zugang per QR-Code für ein Gerät ohne Anmeldung, nur für diesen Wettbewerb und bis zum Ende des Wettbewerbstags (Art. 32 DSGVO).',
    ),
    example: d(
      'Beispiel: Das Leihtablet „Stand 2“ scannt den Code und kann bis 23:59 Uhr erfassen.',
    ),
    sources: ['dsgvo'],
    section: 'competitions',
    feature: 'competitions',
  },
  comp_organizer: {
    name: d('Ausrichter'),
    meaning: d(
      'Verein oder Verband, der einen fremden Wettbewerb veranstaltet und wertet. Er legt Regeln und Preise fest (§ 25 BGB).',
    ),
    example: d(
      'Beispiel: Beim Bezirksschießen 2027 ist der Bezirksverband der Ausrichter; ihr tragt nur eure Plätze ein, etwa Platz 3 mit 287 Ringen.',
    ),
    sources: ['bgb'],
    section: 'competitions',
    feature: 'competitions',
  },
} satisfies Record<string, TermEntry>

export type TermKey = keyof typeof TERMS_DATA
export const TERMS: Record<TermKey, TermEntry> = TERMS_DATA

// --- „Wie gerechnet?“ und „So funktioniert es:“ ---

export interface HowEntry {
  kind: 'calc' | 'how'
  title: Text
  text: Text
  /** kleine Beispieltabelle */
  example?: { head: string[]; rows: string[][] }
  /** leer, wenn der Text nur beschreibt, wie HUBIplan rechnet */
  sources: SourceKey[]
  feature?: Feature
}

const HOWTOS_DATA = {
  calc_fee: {
    kind: 'how',
    title: d('Welcher Beitrag gilt?'),
    text: d(
      'Ausgangspunkt ist der Jahresbeitrag der Mitgliedsart; greift eine Altersstufe nach dem Alter zu Beginn des Geschäftsjahrs, ersetzt sie ihn. Eine Ehrung mit Beitragsanpassung senkt ihn weiter, bei mehreren gilt der günstigste. Beiträge und Ermäßigungen richten sich nach Satzung oder Beitragsordnung (§ 58 Nr. 2 BGB); wer am 29. Februar geboren ist, wird in Jahren ohne Schalttag erst am 1. März älter.',
    ),
    example: {
      head: ['Mitglied', 'Art', 'Alter am 1.1.', 'Beitrag'],
      rows: [
        ['A', 'Aktiv', '34', '72,00 €'],
        ['B', 'Aktiv', '16 (Stufe Jugend)', '24,00 €'],
        ['C', 'Aktiv, Ehrenmitglied', '71', '0,00 €'],
      ],
    },
    sources: ['bgb'],
    feature: 'billing',
  },
  calc_pro_rata: {
    kind: 'calc',
    title: d('Anteiliger Beitrag'),
    text: d(
      'Der Beitrag des Zeitraums wird durch dessen Monate geteilt und mit den Monaten der Mitgliedschaft malgenommen, wobei ein angefangener Monat voll zählt, und kaufmännisch auf Cent gerundet. Bei mehreren Raten im Jahr gehen übrige Cents auf die ersten Raten, damit alle zusammen genau den Jahresbeitrag ergeben (100,00 € monatlich: 4 × 8,34 € und 8 × 8,33 €).',
    ),
    example: {
      head: ['Eintritt', 'Monate', 'Rechnung', 'Beitrag'],
      rows: [
        ['1. Januar', '12 von 12', '72,00 € × 12/12', '72,00 €'],
        ['15. September', '4 von 12', '72,00 € × 4/12', '24,00 €'],
      ],
    },
    sources: [],
    feature: 'billing',
  },
  calc_federation_fee: {
    kind: 'calc',
    title: d('Verbandsbeitrag'),
    text: d(
      'Gezählt werden die gemeldeten Mitglieder jedes Vereins am Beginn des Zeitraums, getrennt nach aktiv und passiv. Jede Gruppe wird mit ihrem Satz je Mitglied malgenommen und für den Zeitraum anteilig berechnet (§ 58 Nr. 2 BGB).',
    ),
    example: {
      head: ['Gruppe', 'Mitglieder', 'Satz', 'Betrag'],
      rows: [
        ['aktiv', '112', '8,00 €', '896,00 €'],
        ['passiv', '38', '4,00 €', '152,00 €'],
      ],
    },
    sources: ['bgb'],
    feature: 'billing',
  },
  calc_earliest_collection: {
    kind: 'calc',
    title: d('Frühestes Einzugsdatum'),
    text: d(
      'Heute plus die eingestellte Vorabankündigung, mindestens aber zwei Tage, verschoben auf den nächsten Werktag. Das SEPA-Regelwerk verlangt die Ankündigung vor dem Einzug (EPC016-06).',
    ),
    sources: ['epcSdd'],
    feature: 'billing',
  },
  calc_mandate_expiry: {
    kind: 'calc',
    title: d('Wann ein Mandat verfällt'),
    text: d(
      'Ab dem letzten Einzug, oder ohne Einzug ab der Unterschrift, zählen 36 Monate. Ist bis dahin nichts eingezogen, gilt das Mandat als verfallen (EPC016-06).',
    ),
    sources: ['epcSdd'],
    feature: 'billing',
  },
  calc_dunning: {
    kind: 'how',
    title: d('Mahnstufen'),
    text: d(
      'Jede Stufe nennt die Tage nach Fälligkeit, ab denen sie fällig wird. Unter „Fällige Mahnungen“ schlägt HUBIplan für jede offene Rechnung die nächste erreichte Stufe vor; eine Gebühr kommt als eigener Posten dazu (§ 286 BGB).',
    ),
    example: {
      head: ['Stufe', 'ab Tag', 'Gebühr'],
      rows: [
        ['Erinnerung', '14', '—'],
        ['1. Mahnung', '28', '2,50 €'],
      ],
    },
    sources: ['bgb'],
    feature: 'billing',
  },
  calc_closing_balance: {
    kind: 'calc',
    title: d('Endbestand'),
    text: d(
      'Endbestand = Anfangsbestand + Einnahmen − Ausgaben ± Umbuchungen, je Konto. Die Summe aller Endbestände muss zu Kontoauszügen und Barkasse passen (§ 259 Abs. 1 BGB). „Bestand heute“ enthält nur Buchungen bis heute, spätere stehen als vorgemerkt daneben.',
    ),
    example: {
      head: ['Konto', 'Anfang', '+ Ein', '− Aus', '± Umb.', 'Ende'],
      rows: [
        ['Giro', '4.250,00', '9.800,00', '8.900,00', '+600,00', '5.750,00'],
        ['Kasse', '300,00', '700,00', '50,00', '−600,00', '350,00'],
      ],
    },
    sources: ['bgb'],
    feature: 'finance',
  },
  calc_members_on_date: {
    kind: 'calc',
    title: d('Mitglieder, Eintritte und Austritte'),
    text: d(
      'Mitglied am Stichtag ist, wessen Mitgliedschaft an diesem Tag läuft; der Bestand eines Tages ist der Stand nach den Austritten dieses Tages. Eintritte und Austritte zählen alle Wechsel im gewählten Zeitraum, ein Wiedereintritt also erneut als Eintritt.',
    ),
    sources: [],
  },
  calc_jubilee: {
    kind: 'calc',
    title: d('Jubiläum'),
    text: d(
      'Zusammengezählt werden alle Zeiten der Mitgliedschaft in Arten, die für die Dauer zählen; Lücken zwischen Austritt und Wiedereintritt zählen nicht, sich überschneidende Zeiten nur einmal. Erreicht die Summe in diesem Jahr eine runde Zahl, erscheint das Jubiläum.',
    ),
    example: {
      head: ['Zeitraum', 'Jahre'],
      rows: [
        ['1998–2010', '12'],
        ['2014–2027', '13'],
        ['Summe 2027', '25'],
      ],
    },
    sources: [],
  },
  how_units: {
    kind: 'how',
    title: d('Einheiten und Untereinheiten'),
    text: d(
      'Jede Einheit kann Untereinheiten haben, die selbst wieder welche haben dürfen, etwa Verein, Zug und Gruppe. Hängst du eine Einheit um, wandern ihre Untereinheiten und Mitglieder mit. Ohne „verwaltet sich selbst“ verwaltet die Einheit darüber alles; eingeschaltet arbeiten ihre Rolleninhaber mit eigenem Zugang, und mit eigenem Arbeitsbereich führt sie auch eine eigene Kasse.',
    ),
    sources: [],
  },
  how_bank_match: {
    kind: 'how',
    title: d('Wie ordnet HUBIplan Umsätze zu?'),
    text: d(
      'Zuerst sucht HUBIplan eine passende Buchung im Kassenbuch (gleicher Betrag, ±3 Tage), dann einen Lastschriftlauf in gleicher Höhe (±10 Tage), dann eine Rechnung über die Nummer im Verwendungszweck oder die IBAN eines Mandats. Du übernimmst den Vorschlag, buchst mit Kategorie oder übergehst den Umsatz. Ein zweites Einlesen derselben Umsätze erkennt HUBIplan und legt nichts doppelt an.',
    ),
    example: {
      head: ['Umsatz', 'Vorschlag'],
      rows: [
        ['+60,00 € „RE 2026-0042“', 'Rechnung 2026-0042'],
        ['+1.240,00 € Sammelgutschrift', 'Lastschriftlauf vom 1.3.'],
        ['−89,90 € Getränke Fest', 'Buchung vom 12.6.'],
      ],
    },
    sources: [],
    feature: 'finance',
  },
  how_peering: {
    kind: 'how',
    title: d('Verbund mit einer anderen Instanz'),
    text: d(
      'Eine Seite bietet die Kopplung an, die andere nimmt sie mit dem Code an; vergleicht dabei den Fingerabdruck am Telefon, damit sich niemand dazwischenschiebt. Danach fließen nur die Daten, die jede Seite freigibt, verschlüsselt und unterschrieben. Eine Kopplung lässt sich pausieren und beenden, die Daten auf der eigenen Instanz bleiben.',
    ),
    sources: [],
  },
  how_app_devices: {
    kind: 'how',
    title: d('App verbinden'),
    text: d(
      'Der QR-Code gilt nur kurz und nur einmal; das Telefon bekommt beim Scannen einen eigenen Schlüssel, ein Passwort wird nicht gespeichert. Unter „Angemeldete Geräte“ siehst du jedes Telefon und meldest es ab, etwa wenn es verloren ist. Danach funktioniert die App dort sofort nicht mehr.',
    ),
    sources: [],
  },
  how_regnal_number: {
    kind: 'how',
    title: d('Ordnungszahlen wie „Michael II.“'),
    text: d(
      'Mit Ordnungszahl zählt HUBIplan je Würde und Vorname: Der erste Michael ist Michael I., der nächste Michael II. Trägt jemand die Würde zweimal, behält er seine Zahl, außer „bei mehrfacher Würde neu zählen“ ist an. Eine Zahl aus alten Listen trägst du direkt an der Regentschaft ein, sie geht vor.',
    ),
    example: {
      head: ['Jahr', 'König', 'neu zählen aus', 'neu zählen an'],
      rows: [
        ['2019', 'Otto Muster', 'Otto I.', 'Otto I.'],
        ['2022', 'Otto Beispiel', 'Otto II.', 'Otto II.'],
        ['2025', 'Otto Muster', 'Otto I.', 'Otto III.'],
      ],
    },
    sources: [],
  },
  calc_takings: {
    kind: 'calc',
    title: d('Tageseinnahme im Kassenbericht'),
    text: d(
      'Tageseinnahme = gezählter Endbestand − Anfangsbestand (Wechselgeld) + bar bezahlte Ausgaben + Entnahmen. Ausgaben und Entnahmen buchst du wie gewohnt einzeln; HUBIplan bucht nur die Einnahme, aufgeteilt auf die Kategorien.',
    ),
    example: {
      head: ['Posten', 'Betrag'],
      rows: [
        ['gezählter Endbestand', '1.850,00 €'],
        ['− Wechselgeld', '200,00 €'],
        ['+ bar bezahlte Ausgaben', '50,00 €'],
        ['+ Entnahmen (zur Bank)', '500,00 €'],
        ['= Tageseinnahme', '2.200,00 €'],
      ],
    },
    sources: ['ao'],
    feature: 'finance',
  },
  calc_reserve_free: {
    kind: 'calc',
    title: d('Frei verfügbare Mittel'),
    text: d(
      'Frei verfügbar = Bestand aller Konten heute − Summe aller Rücklagen. Wird der Wert negativ, sind mehr Mittel gebunden als vorhanden, dann löst du Rücklagen auf.',
    ),
    example: {
      head: ['Posten', 'Betrag'],
      rows: [
        ['Bestand aller Konten', '8.000,00 €'],
        ['− Rücklage Festzelt', '3.000,00 €'],
        ['− Rücklage Jubiläum', '1.500,00 €'],
        ['= frei verfügbar', '3.500,00 €'],
      ],
    },
    sources: [],
    feature: 'finance',
  },
  // --- Wettbewerbe ---
  how_comp_ranking: {
    kind: 'calc',
    title: d('Plätze bei Gleichstand'),
    text: d(
      'Gleiche Werte teilen sich den Platz, der nächste Platz wird übersprungen. Auf Preisplätzen entscheidet ein Stechen, danach gilt die Reihenfolge des Stechens.',
    ),
    example: {
      head: ['Schütze', 'Wert', 'Platz'],
      rows: [
        ['A', '29', '1.'],
        ['B', '27', '2.'],
        ['C', '27', '2.'],
        ['D', '25', '4.'],
      ],
    },
    sources: [],
    feature: 'competitions',
  },
  how_comp_unit: {
    kind: 'calc',
    title: d('Wertung der Untereinheiten'),
    text: d(
      'Bei „Summe der besten k“ zählen die k besten Einzelwerte der Einheit; Schützen außer Konkurrenz zählen nicht. Hat eine Einheit weniger als k Werte, bleibt sie ohne Platz.',
    ),
    example: {
      head: ['Zug', 'Einzelwerte', 'beste 3'],
      rows: [
        ['Zug 1', '28, 27, 25, 20', '80'],
        ['Zug 2', '29, 26, 24', '79'],
        ['Zug 3', '30, 28', 'nicht gewertet'],
      ],
    },
    sources: [],
    feature: 'competitions',
  },
  how_comp_bird_order: {
    kind: 'how',
    title: d('Reihenfolge beim Vogelschießen'),
    text: d(
      'Geschossen wird nach Losnummer, Fehlende und Ausgeschiedene werden übersprungen. Nach der höchsten Nummer beginnt die nächste Runde wieder bei der kleinsten.',
    ),
    sources: [],
    feature: 'competitions',
  },
  how_comp_shots_for: {
    kind: 'calc',
    title: d('Schüsse für das Pfand'),
    text: d('Gezählt werden die Schüsse seit dem vorher gefallenen Pfand bis zum Treffer.'),
    example: {
      head: ['Pfand', 'Schuss Nr.', 'Schüsse für das Pfand'],
      rows: [
        ['Kopf', '30', '30'],
        ['Linker Flügel', '54', '24'],
        ['Schweif', '75', '21'],
      ],
    },
    sources: [],
    feature: 'competitions',
  },
  how_comp_tablets: {
    kind: 'how',
    title: d('Mehrere Tablets gleichzeitig'),
    text: d(
      'Alle Geräte gleichen sich etwa alle 3 Sekunden ab; für einen Schützen gilt der zuletzt eingetragene Wert, und doppelt angelegte Schützen werden zusammengeführt. Ohne Empfang wird weiter erfasst und später gesendet. Stechen anlegen und abschließen braucht Empfang.',
    ),
    sources: [],
    feature: 'competitions',
  },
} satisfies Record<string, HowEntry>

export type HowKey = keyof typeof HOWTOS_DATA
export const HOWTOS: Record<HowKey, HowEntry> = HOWTOS_DATA

/** Glossar-Anker */
export const termAnchor = (k: string) => `begriff-${k}`
export const decisionAnchor = (k: string) => `warum-${k}`
