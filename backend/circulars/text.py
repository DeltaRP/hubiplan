"""Text eines Rundschreibens: Platzhalter und einfache Auszeichnung.

Auszeichnung (wie im Editor der Oberfläche):

- ``**fett**``, ``*kursiv*``, ``[Text](https://…)``
- Zeilen mit ``- `` bilden eine Liste, Zeilen mit ``1. `` eine nummerierte Liste
- Leerzeile = neuer Absatz, einfacher Zeilenumbruch bleibt erhalten

Daraus entstehen HTML (Mail), reiner Text (Mail ohne HTML) und Absätze für das
Brief-PDF. Fremdes HTML wird nie übernommen: alles wird erst maskiert.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape

PLACEHOLDERS: dict[str, str] = {
    "Vorname": "Vorname des Empfängers",
    "Nachname": "Nachname des Empfängers",
    "Anrede": "„Sehr geehrter Herr …“ / „Sehr geehrte Frau …“ (sonst „Guten Tag …“)",
    "Anrede Du": "„Lieber …“ / „Liebe …“ mit Vorname (sonst „Hallo …“)",
    "Abteilung": "Abteilung(en) des Mitglieds",
    "Verein": "Verein des Empfängers",
    "Mitgliedsjahre": "volle Jahre im Verein",
    "Jubiläumsjahre": "Jubiläum im gewählten Jahr (nur mit Auswahl „Jubilare“)",
}

PLACEHOLDER_RE = re.compile(r"\{([^{}\s][^{}]{0,40})\}")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
ITALIC_RE = re.compile(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])")
LINK_RE = re.compile(r"\[([^\]\n]+)\]\(((?:https?://|mailto:)[^)\s]+)\)")
BULLET_RE = re.compile(r"^\s*[-•]\s+(.*)$")
NUMBER_RE = re.compile(r"^\s*\d+[.)]\s+(.*)$")


def unknown_placeholders(*texts: str) -> list[str]:
    found = []
    for text in texts:
        for name in PLACEHOLDER_RE.findall(text or ""):
            if name not in PLACEHOLDERS and name not in found:
                found.append(name)
    return found


def fill(text: str, values: dict[str, str]) -> str:
    """Setzt die Platzhalter ein; unbekannte bleiben stehen."""

    def repl(m: re.Match) -> str:
        name = m.group(1)
        if name in PLACEHOLDERS:
            return str(values.get(name, "") or "")
        return m.group(0)

    return PLACEHOLDER_RE.sub(repl, text or "")


@dataclass
class Block:
    kind: str  # "p", "ul" oder "ol"
    lines: list[str]


def blocks(text: str) -> list[Block]:
    result: list[Block] = []
    current: Block | None = None
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            current = None
            continue
        bullet = BULLET_RE.match(line)
        number = NUMBER_RE.match(line)
        kind = "ul" if bullet else "ol" if number else "p"
        content = (bullet or number).group(1) if (bullet or number) else line
        if current is None or current.kind != kind:
            current = Block(kind, [])
            result.append(current)
        current.lines.append(content)
    return result


def inline_html(text: str) -> str:
    """Eine Zeile maskieren und auszeichnen (<b>, <i>, <a>); gilt für Mail und PDF."""
    links: list[str] = []

    def keep_link(m: re.Match) -> str:
        links.append(
            f'<a href="{escape(m.group(2), quote=True)}">{escape(m.group(1), quote=False)}</a>'
        )
        return f"\x00{len(links) - 1}\x00"

    text = LINK_RE.sub(keep_link, text)
    out = escape(text, quote=False)
    out = BOLD_RE.sub(r"<b>\1</b>", out)
    out = ITALIC_RE.sub(r"<i>\1</i>", out)
    return re.sub("\x00(\\d+)\x00", lambda m: links[int(m.group(1))], out)


def to_html(text: str) -> str:
    parts = []
    for block in blocks(text):
        if block.kind == "p":
            parts.append("<p>" + "<br>".join(inline_html(line) for line in block.lines) + "</p>")
        else:
            items = "".join(f"<li>{inline_html(line)}</li>" for line in block.lines)
            parts.append(f"<{block.kind}>{items}</{block.kind}>")
    return "\n".join(parts)


def inline_plain(text: str) -> str:
    text = LINK_RE.sub(lambda m: f"{m.group(1)} ({m.group(2)})", text)
    text = BOLD_RE.sub(r"\1", text)
    return ITALIC_RE.sub(r"\1", text)


def to_plain(text: str) -> str:
    parts = []
    for block in blocks(text):
        if block.kind == "p":
            parts.append("\n".join(inline_plain(line) for line in block.lines))
        elif block.kind == "ul":
            parts.append("\n".join(f"- {inline_plain(line)}" for line in block.lines))
        else:
            parts.append(
                "\n".join(f"{n}. {inline_plain(line)}" for n, line in enumerate(block.lines, 1))
            )
    return "\n\n".join(parts)
