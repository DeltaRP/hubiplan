# Ehrungen

Vereine und Dachverbände legen ihre Ehrungen selbst an (Mitglieder › Einrichtung ›
Ehrungen), z. B. Ehrenmitglied, Ehrenmajor, Ehrenoberst. Verliehen wird in der
Mitgliederakte (Reiter „Rollen & Ehrungen“) mit Beginn, optional Ende und Bemerkung.
Ein Mitglied kann mehrere Ehrungen gleichzeitig haben; beendete Verleihungen bleiben im
Verlauf. (Bis Oktober 2026 hießen Ehrungen „Ehrentitel“; im Code heißen sie weiter
`HonoraryTitle`, der Listenfilter weiter `ehrentitel`.)

## Beitrag

Je Ehrung: keine Beitragsänderung, beitragsfrei, fester Jahresbeitrag oder Abschlag in
Prozent. Hat ein Mitglied mehrere solcher Ehrungen, gilt die günstigste. Maßgeblich ist der
Stichtag des Beitragslaufs (wie bei der Mitgliedsart).

- Ehrungen des Vereins ändern den Vereinsbeitrag (`billing.services.plan_run`).
- Ehrungen des Dachverbands ändern den Verbandsbeitrag, den der Verein für das Mitglied
  zahlt (`billing.services.plan_federation_run`, eigener Rechnungsposten je Ehrung).

## Sichtbarkeit

- Der Verein sieht die Ehrungen, die der Dachverband seinen Mitgliedern verliehen hat (nur
  lesen), und kann danach filtern.
- Der Dachverband verleiht seine Ehrungen in seiner Mitgliederansicht. Dafür genügt der
  Lesezugriff auf die Mitgliedsdaten der Vereine; ohne Freigabe der Plattform geht es nicht.
- RLS: `core/migrations/0019_rls_ehrentitel.py`.

## Listen, Rundschreiben, Export

- Mitgliederliste: Filter `ehrentitel=<Nummer>` oder `ehrentitel=mit`, Sortierung
  `ehrentitel`, Spalte „Ehrungen“ (auch im Listen-Export). Dachverbandsliste: Filter
  nach eigenen Ehrungen.
- Rundschreiben: Empfängerfilter `honorary_titles` (Verein: eigene und Ehrungen des
  Dachverbands; Dachverband: eigene).
- JSON-Datenübernahme: Tabellen `members.honorarytitle` und `members.honorarytitleaward`
  (mit den Mitgliedsdaten, nicht im Export einer Abteilung).
- Rückgängig: Änderungen an Ehrungen und Verleihungen lassen sich zurücknehmen (App
  `members` wird erfasst).

Code: `backend/members/honorary.py`, Frontend `pages/members/HonoraryTitlesPage.tsx`,
`pages/members/HonoraryAwards.tsx`.

## Beitragsfreie Untereinheit

Statt jedes Mitglied einzeln zu ehren, kann eine ganze Untereinheit beitragsfrei sein:
Schalter „Mitglieder von … sind beitragsfrei“ in der Maske der Untereinheit (nur mit
Beitragsmodul). Wer am Stichtag des Beitragslaufs dieser Untereinheit oder einer Einheit
darunter angehört, zahlt keinen Vereinsbeitrag und steht in der Prüfliste als
„beitragsfrei (Name der Untereinheit)“. Stillgelegte Untereinheiten zählen nicht. Der
Verbandsbeitrag an den Dachverband bleibt unberührt.
