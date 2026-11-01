# Hinweise für die Arbeit an hubiplan

Feste Regeln von Ralf:

- **Nie Tests auf dem Testserver ausführen**, auch keine Test-Container.
  Tests laufen lokal in WSL (Distribution `Debian`, Klon `~/hubiplan`, Docker) mit `scripts/test.sh`,
  danach wird ausgerollt. `deploy/deploy.sh` rollt nur lokal getestete Stände aus.
- **Höchstens zwei Testläufe gleichzeitig, jeder höchstens 8 Kerne**, projektübergreifend
  für alle Projekte auf Ralfs PC. `scripts/test.sh` holt sich dafür einen Platz mit
  `scripts/testplatz.sh` (auch für andere Projekte: `testplatz <befehl>`, siehe
  [docs/testserver.md](docs/testserver.md), „Testplätze“). Tests nur über `scripts/test.sh` starten.
- Keine Passwörter oder Geheimnisse ins Repo oder in Chats; Zugangsdaten nur in Dateien
  auf Ralfs Rechner.
- Auf dem Testserver nur erfundene Daten.
- **Jeder neue Text gleich auch auf Englisch** (Oberfläche `t()` + `src/i18n/en.json`, Backend
  `gettext` + `locale/en`); `scripts/test.sh` schlägt sonst fehl. Siehe [docs/uebersetzung.md](docs/uebersetzung.md).
- CI (GitHub Actions) läuft nur von Hand (workflow_dispatch); keine automatischen Auslöser.

Details: [docs/testserver.md](docs/testserver.md), [docs/betrieb.md](docs/betrieb.md).
