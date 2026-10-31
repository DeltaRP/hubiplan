# Liste geleakter Passwörter

`geleakte-passwoerter.txt.gz` enthält die Einträge ab 8 Zeichen aus
„100k-most-used-passwords-NCSC.txt“ (SecLists, MIT-Lizenz,
https://github.com/danielmiessler/SecLists). Das ist die Liste des britischen
National Cyber Security Centre mit den häufigsten Passwörtern aus Datenlecks.

Herkunft und Lizenz:

- Quelle: SecLists, Datei `Passwords/Common-Credentials/100k-most-used-passwords-NCSC.txt`
  im Stand von Commit `1a7bb9127eca9e6ff2fc0301c597fe6e16a0cb56` (19.11.2025).
- Lizenz: MIT, Copyright (c) 2018 Daniel Miessler. Der Lizenztext liegt unverändert in
  [LICENSE-SecLists.txt](LICENSE-SecLists.txt) und gehört zu jeder Kopie der Liste.
- Umwandlung für HUBIplan: Leerzeichen am Rand entfernt, in Kleinbuchstaben umgewandelt,
  nur Einträge ab 8 Zeichen, doppelte Einträge entfernt, mit gzip gepackt.
- Offen (Lizenzaudit 31.10.2026, L04): die Nutzungsgrundlage der ursprünglichen
  NCSC-Sammlung selbst; siehe `docs/lizenzen.md`.

Die Prüfung läuft nur auf dem Server, kein Passwort verlässt HUBIplan.
Kürzere Passwörter lehnt schon die Mindestlänge ab.
