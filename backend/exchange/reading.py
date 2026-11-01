"""Excel- und CSV-Dateien einlesen."""

from __future__ import annotations

import csv
import datetime
import io
import zipfile
from pathlib import Path

from openpyxl import load_workbook

MAX_ROWS = 20000
MAX_COLUMNS = 200
# Beim Lesen höchstens so viele Zeilen (Daten + Kopf + ein paar Leerzeilen) ansehen,
# danach sofort abbrechen statt die ganze Datei in den Speicher zu holen.
MAX_SCAN_ROWS = MAX_ROWS + 1000


class ReadError(Exception):
    pass


def _cell(value):
    if isinstance(value, datetime.datetime):
        return value.date() if value.time() == datetime.time() else value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        return value.strip()
    return value


def read_table(path: str | Path, file_name: str) -> tuple[list[str], list[list]]:
    """Kopfzeile und Datenzeilen. Leere Zeilen entfallen."""
    suffix = Path(file_name).suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        rows = _read_xlsx(path)
    elif suffix in (".csv", ".txt"):
        rows = _read_csv(path)
    else:
        raise ReadError("Bitte eine Excel-Datei (.xlsx) oder CSV-Datei hochladen.")
    rows = [r for r in rows if any(v not in (None, "") for v in r)]
    if not rows:
        raise ReadError("Die Datei ist leer.")
    headers = [
        str(h).strip() if h not in (None, "") else f"Spalte {i + 1}" for i, h in enumerate(rows[0])
    ]
    data = rows[1:]
    if len(data) > MAX_ROWS:
        raise ReadError(f"Höchstens {MAX_ROWS} Zeilen je Datei.")
    width = len(headers)
    return headers, [(list(r) + [None] * width)[:width] for r in data]


# Entpackte Größe einer Excel-Datei (ZIP): vor dem Lesen begrenzen, damit eine kleine,
# stark gepackte Datei nicht Speicher und Rechenzeit verbraucht (Gesamtaudit 31.10.b, INF-S02)
MAX_UNPACKED = 100 * 1024 * 1024
MAX_RATIO = 200


def _check_zip(path) -> None:
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
    except (zipfile.BadZipFile, OSError) as exc:
        raise ReadError("Die Excel-Datei lässt sich nicht lesen.") from exc
    unpacked = sum(i.file_size for i in infos)
    packed = sum(i.compress_size for i in infos) or 1
    if unpacked > MAX_UNPACKED or unpacked / packed > MAX_RATIO:
        raise ReadError("Die Excel-Datei ist entpackt zu groß. Bitte als CSV speichern.")


def _read_xlsx(path) -> list[list]:
    _check_zip(path)
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise ReadError("Die Excel-Datei lässt sich nicht lesen.") from exc
    try:
        ws = wb.worksheets[0]
        rows = []
        kept = 0
        # max_col: übergroße angegebene Tabellenbreite nicht erst aufbauen (GA-H02)
        for row in ws.iter_rows(values_only=True, max_col=MAX_COLUMNS):
            values = [_cell(v) for v in row[:MAX_COLUMNS]]
            rows.append(values)
            if any(v not in (None, "") for v in values):
                kept += 1
            if kept > MAX_ROWS + 1 or len(rows) > MAX_SCAN_ROWS + MAX_ROWS:
                raise ReadError(f"Höchstens {MAX_ROWS} Zeilen je Datei.")
        return rows
    finally:
        wb.close()


class _Semicolon(csv.excel):
    delimiter = ";"


def _read_csv(path) -> list[list]:
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover
        raise ReadError("Unbekannte Zeichenkodierung.")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t")
    except csv.Error:
        dialect = _Semicolon
    rows = []
    for row in csv.reader(io.StringIO(text), dialect):
        rows.append([_cell(v) for v in row[:MAX_COLUMNS]])
        if len(rows) > MAX_SCAN_ROWS + MAX_ROWS:
            raise ReadError(f"Höchstens {MAX_ROWS} Zeilen je Datei.")
    return rows
