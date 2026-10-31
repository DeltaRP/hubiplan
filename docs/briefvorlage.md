# Briefbogen und Briefvorlage

Vorstände erzeugen sich eine Word-Vorlage (`.dotx` oder `.docx`) für Schreiben
ihrer Einheit. Briefkopf, Fußzeile, Farben und Schrift kommen aus dem
**Briefbogen** der Einheit; die Person wählt nur Funktion und Kontaktangaben.
Code: App `backend/letterhead` (Daten `data.py`, Word-Datei `docx.py`,
PDF-Vorschau `preview.py`, Schnittstelle `views.py`). Konzept:
`/mnt/project-files/konzepte/briefvorlage.md` im Projekt.

## Briefbogen der Einheit (Einstellungen › Briefbogen, Recht `org.edit`)

- **Form A oder B** nach DIN 5008, Schrift (Standard Arial), Logo/Wappen rechts,
  links oder nicht, Zusatzzeile unter dem Namen (Standard „gegründet …“),
  Anrede und Grußformel als Vorbelegung.
- **Fußzeile**: Kontakt (E-Mail, Telefon, Web), Bankverbindung (ein Konto der
  Kasse), Vorstand, Registerangaben, Social Media. Jede Spalte einzeln
  abschaltbar.
- **Vorstand in der Fußzeile**: Inhaber der Rollen „vertritt die Einheit“, dazu
  Rollen mit „auf dem Briefbogen nennen“ (Einstellungen › Rollen & Benutzer bzw.
  bei Untereinheiten deren Rollen). Rollen können eine **Funktionsadresse**
  haben (z. B. kasse@…).
- **Untereinheiten** übernehmen den Briefbogen der Einheit darüber und bekommen
  eine Unterzeile mit ihrem Namen. Einen eigenen Briefbogen gibt es nur mit
  eigenem Arbeitsbereich.
- **Neutrale Vorlage** ohne Absender zum Herunterladen oder direkt als
  Dokument „Briefvorlage …“ in die Dokumentenablage (Recht `docs.manage`,
  ersetzt dort eine neue Version).

## Persönliche Vorlage (Mein Konto › Briefvorlage & Unterschrift, `/briefvorlage`)

- Wer eine Vorstandsrolle hat (Rolle mit „Vorstand“-Kennzeichen) oder eine Rolle
  in einer Untereinheit hält, sieht hier seine Einheiten und Funktionen.
- Im Informationsblock stehen Name, Funktion (frei änderbar), Titel und die
  gewählten Kontakte. **Private Angaben** (eigene E-Mail, Telefon, Anschrift als
  „Antwort an“) sind nie vorausgewählt.
- Logo optional; eine **Unterschrift als Bild** wird nur in die Datei
  geschrieben und nicht gespeichert. Die erzeugte Datei speichert HUBIplan nicht.
- Gespeichert werden nur die Auswahl und Prüfsummen (HMAC) der verwendeten
  Angaben. Ändern sich später z. B. Bankverbindung, Vorstand oder Anschrift,
  erscheint auf der Startseite „Briefvorlage veraltet“. Neue Funktionen (90 Tage)
  bekommen den Hinweis „Briefvorlage erstellen“. Beides lässt sich mit „Später“
  ausblenden.

## Word-Datei

Handgeschriebenes OOXML ohne Makros: Kopf, Logo und Falzmarken in Rahmen,
Anschrift und Informationsblock in einer Tabelle, Inhaltssteuerelemente für
Empfänger, Betreff und Datum (Datumsauswahl), Folgeseiten mit „Seite X von Y“,
Formatvorlagen (Brieftext, Betreff, Überschriften in der Hauptfarbe, Aufzählung,
Tabelle) und Designfarben aus den Farben der Einheit. Die PDF-Vorschau bildet
die erste Seite mit denselben Maßen nach.

## Rechnungen und Serienbriefe

Rechnungen, Mahnungen, Lastschrift-Ankündigungen und Serienbriefe aus
Rundschreiben nutzen denselben Briefbogen als PDF (`letterhead/pdf.py`,
`LetterDocument`): Kopf mit Logo, Falz- und Lochmarken, Rücksendeangabe,
Anschriftfeld, Informationsblock (z. B. Rechnungsnummer, Datum, Telefon,
E-Mail) und Fußzeile der ersten Seite; Folgeseiten mit kleinem Kopf und
Seitenzahl. Schrift und Farben folgen dem Briefbogen (im PDF als Helvetica bzw.
Times angenähert). Briefe einer Untereinheit tragen deren Unterzeile.

## Export und Demodaten

Der Briefbogen wird mit den Einheiten exportiert und importiert (ohne
Bankkonto). `seed_testdata` setzt erfundene Funktionsadressen und
Social-Media-Links (`.test`-Adressen) für die Demo-Einheiten.
