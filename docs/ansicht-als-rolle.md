# Ansicht als Rolle

Wer verstehen will, was andere in HUBIplan sehen, wählt oben in der Kopfleiste neben der
Einheiten-Auswahl eine Rolle der Einheit („Ansicht als Kassierer“). HUBIplan zeigt Menü,
Seiten und Knöpfe dann so, wie jemand mit nur dieser Rolle sie sieht.

## Wer darf das?

Die Auswahl erscheint nur mit dem Recht **„Ansicht als Rolle“** (Modul „Rollen und
Benutzer“, Code `roles.preview`). Am einfachsten legt man dafür eine eigene Rolle an,
z. B. „Rollenansicht“, und vergibt sie gezielt.

## Regeln

- **Nur lesen.** Solange eine Rolle gewählt ist, lehnt der Server jede ändernde Anfrage
  an die API ab (Speichern, Löschen, Versenden, Rückgängig). Erlaubt bleiben nur Beginn
  und Ende der Ansicht sowie An- und Abmelden.
- **Nie mehr als die eigenen Rechte.** In der Einheit gilt die Schnittmenge aus den
  eigenen Rechten und denen der Rolle (Entscheidung Ralf 01.11.2026). Über die Ansicht
  kommt niemand an Daten, die er sonst nicht sieht. Wer alle Rechte hat, sieht die Rolle
  genau so wie ihre Inhaber.
- **Nur Rollen der gewählten Einheit.** Für eine Untereinheit wechselt man wie bisher
  die Einheit; dabei endet die Ansicht.
- **Deutlicher Hinweis** über dem Inhalt mit dem Knopf „Ansicht beenden“.
- **Protokoll:** Beginn und Ende stehen im Änderungsprotokoll der Einheit
  (Aktion „angesehen“, Objekt die Rolle).

## Technik

- Server: `backend/access/preview.py` (Middleware, Sitzungsschlüssel `hubiplan_ansicht`),
  `permissions_in` schneidet die Rechte zu, `own_permissions_in` liefert die eigenen.
  API `GET/POST/DELETE /api/orgs/<id>/ansicht/`, `role_preview` in `/api/me/organizations/`.
- Die Wahl steht in der Sitzung: Dateien, Bilder und weitere Tabs zeigen dieselbe Ansicht.
- Wird das Recht entzogen oder die Rolle gelöscht, endet die Ansicht beim nächsten Laden.
- Die App (`/api/app/v1/`) ist nicht betroffen.
- Grenzen: Die Ansicht gilt nur in ihrer Einheit. Abteilungsbereiche („d:…“) und
  „Meine Daten“ zeigen weiter die eigene Sicht.
