"""Fachfrage 4 (31.10.b): Virenprüfung beim Hochladen mit clamd (hier ein nachgebauter
clamd über einen Unix-Socket; erfundene Daten)."""
# ruff: noqa: F811  (Fixtures als Parameter)

import socket
import struct
import threading

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile

from core import virenscan

from .test_documents import base, board_fed, folder, pdf, private_root, setup  # noqa: F401

pytestmark = pytest.mark.django_db
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class FakeClamd:
    """Antwortet wie clamd auf zINSTREAM: FOUND bei der EICAR-Testzeichenkette."""

    def __init__(self, path):
        self.path = str(path)
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path)
        self.server.listen(5)
        self.scanned = []
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                data = b""
                while not data.endswith(b"\0"):
                    data += conn.recv(1)
                assert data == b"zINSTREAM\0"
                body = b""
                while True:
                    head = b""
                    while len(head) < 4:
                        part = conn.recv(4 - len(head))
                        if not part:
                            break
                        head += part
                    if len(head) < 4:
                        break
                    (size,) = struct.unpack("!L", head)
                    if size == 0:
                        self.scanned.append(body)
                        reply = (
                            b"stream: Eicar-Test-Signature FOUND\0"
                            if EICAR in body
                            else b"stream: OK\0"
                        )
                        conn.sendall(reply)
                        break
                    chunk = b""
                    while len(chunk) < size:
                        chunk += conn.recv(size - len(chunk))
                    body += chunk

    def close(self):
        self.server.close()


@pytest.fixture
def clamd(settings, tmp_path):
    settings.SECURITY_ALERTS = True
    settings.SECURITY_ALERT_EMAIL = "alarm@example.org"
    fake = FakeClamd(tmp_path / "clamd.ctl")
    settings.CLAMD_SOCKET = fake.path
    yield fake
    fake.close()


def _upload(api, board_fed, setup, file):
    c = api(board_fed)
    b = base(setup["federation"])
    f = folder(c, b)
    return c.post(f"{b}folders/{f['id']}/documents/", {"title": "Protokoll", "file": file})


def test_sauber_geht_durch(clamd, api, board_fed, setup):
    resp = _upload(api, board_fed, setup, pdf())
    assert resp.status_code == 201, resp.json()
    assert clamd.scanned == [b"%PDF-1.4 erfundenes Protokoll"]


def test_fund_wird_abgelehnt_und_gemeldet(clamd, api, board_fed, setup):
    from documents.models import Document

    mail.outbox.clear()
    resp = _upload(api, board_fed, setup, SimpleUploadedFile("rechnung.pdf", b"%PDF-1.4 " + EICAR))
    assert resp.status_code == 422
    assert "Schadsoftware" in resp.json()["detail"]
    assert not Document.objects.exists()
    assert any("Schadsoftware" in m.subject for m in mail.outbox)


def test_clamd_aus_lehnt_ab(settings, tmp_path, api, board_fed, setup):
    settings.CLAMD_SOCKET = str(tmp_path / "fehlt.ctl")
    resp = _upload(api, board_fed, setup, pdf())
    assert resp.status_code == 503


def test_zu_gross_bleibt_ungeprueft(clamd, settings, api, board_fed, setup):
    settings.CLAMD_MAX_BYTES = 10
    resp = _upload(api, board_fed, setup, pdf())
    assert resp.status_code == 201, resp.json()
    assert clamd.scanned == []


def test_ohne_socket_keine_pruefung(settings, api, board_fed, setup):
    settings.CLAMD_SOCKET = ""
    resp = _upload(api, board_fed, setup, SimpleUploadedFile("x.pdf", b"%PDF-1.4 " + EICAR))
    assert resp.status_code == 201


def test_scan_bytes(clamd):
    virenscan.scan_bytes(b"harmlos", "a.txt")
    with pytest.raises(virenscan.VirusFound):
        virenscan.scan_bytes(EICAR, "b.txt")


def test_inbound_ok_mail_anhang(clamd):
    """GA-I01: Anhänge aus Mails werden geprüft, ein Fund wird übersprungen."""
    from email.message import EmailMessage

    from circulars.inbound import extract

    assert virenscan.inbound_ok(b"harmlos", "a.pdf", "Test")
    assert not virenscan.inbound_ok(EICAR, "b.pdf", "Test")

    msg = EmailMessage()
    msg["Subject"] = "Rundschreiben"
    msg["From"] = "vorstand@example.org"
    msg.set_content("Hallo zusammen")
    msg.add_attachment(b"%PDF-1.4 sauber", maintype="application", subtype="pdf", filename="a.pdf")
    msg.add_attachment(
        b"%PDF-1.4 " + EICAR, maintype="application", subtype="pdf", filename="b.pdf"
    )
    result = extract(msg)
    assert [name for name, _ in result.pdfs] == ["a.pdf"]
    assert any("b.pdf" in s and "Schadsoftware" in s for s in result.skipped)
