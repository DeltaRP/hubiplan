"""Schlüsselwechsel der Instanz im Verbund (Härtung H6, konzepte/haertung-austausch.md V2/V3).

Geplanter Wechsel (Knopf in der Plattformverwaltung oder automatisch nach einem Jahr):
neue Schlüssel, die alten gelten 30 Tage weiter. Jede Gegenstelle bekommt die
Ankündigung ``instance.keys``, unterschrieben mit dem alten Schlüssel (Kopfzeile) und
dem neuen (Nachweis im Inhalt). Sie übernimmt die neuen Schlüssel sofort und nimmt den
alten noch 30 Tage an. Danach löscht diese Instanz den alten privaten Schlüssel.

Notfallwechsel (Schlüssel vermutlich gestohlen): Der alte Schlüssel unterschreibt nur
noch die Ankündigung. Die Gegenstelle übernimmt die neuen Schlüssel erst, wenn dort ein
Vorstand den Fingerabdruck bestätigt, den wir ihm auf anderem Weg mitteilen. Ein
geplanter Wechsel wird dort abgelehnt, solange ein Notfallwechsel wartet: Wer nur den
alten Schlüssel gestohlen hat, kann sich so nicht dazwischen drängen.
"""

from __future__ import annotations

import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.alarm import send_alert

from . import identity, services, transport
from .models import Coupling, Message, Peer

log = logging.getLogger(__name__)

PATH = "/api/peering/v1/keys/"
CLOSED = (Coupling.State.ENDED, Coupling.State.MOVED)


def open_peers():
    """Gegenstellen mit mindestens einer nicht gelösten Kopplung."""
    return (
        Peer.objects.filter(couplings__isnull=False)
        .exclude(couplings__state__in=CLOSED)
        .exclude(instance_id=identity.identity().instance_id)
        .distinct()
    )


def _open_couplings(peer: Peer):
    return (
        Coupling.objects.filter(peer=peer)
        .exclude(state__in=CLOSED)
        .select_related("local_unit", "remote_unit", "peer")
    )


# --- Diese Instanz wechselt ---


def announcement(ident: identity.Identity) -> dict:
    at = ident.rotated_at or ident.created
    statement = identity.key_statement(
        ident.instance_id, ident.public_key, ident.enc_public_key, at
    )
    return {
        "kind": "instance.keys",
        "public_key": ident.public_key,
        "enc_public_key": ident.enc_public_key,
        "at": at,
        "emergency": ident.previous_revoked,
        # Nachweis: wir haben den neuen privaten Schlüssel
        "proof": ident.sign(statement),
    }


def announce(peer: Peer) -> str:
    """Wechsel einer Gegenstelle mitteilen: "applied", "pending" (Notfall) oder Fehlertext."""
    ident = identity.identity()
    if peer.our_fingerprint == ident.fingerprint:
        return "applied"
    try:
        result = transport.call(services.keys_of(peer), PATH, announcement(ident), announce=True)
    except transport.PeerError as exc:
        log.warning("Schlüsselwechsel an %s nicht zugestellt: %s", peer.base_url, exc)
        return str(exc) or "nicht erreichbar"
    if result.get("applied"):
        Peer.objects.filter(pk=peer.pk).update(our_fingerprint=ident.fingerprint)
        return "applied"
    return "pending" if result.get("pending") else "unbekannte Antwort"


def announce_all() -> dict[str, str]:
    return {peer.base_url: announce(peer) for peer in open_peers()}


def rotate(user, *, emergency: bool = False) -> identity.Identity:
    """Schlüssel dieser Instanz wechseln und allen Gegenstellen mitteilen."""
    old = identity.identity().fingerprint
    ident = identity.rotate(emergency=emergency)
    who = getattr(user, "email", "") or "automatisch (jährlich)"
    send_alert(
        "Verbund: Notfallwechsel der Instanzschlüssel"
        if emergency
        else "Verbund: Instanzschlüssel gewechselt",
        [
            f"Ausgelöst von: {who}",
            f"Alter Fingerabdruck: {old}",
            f"Neuer Fingerabdruck: {ident.fingerprint}",
            *(
                [
                    "Die Partner müssen den neuen Fingerabdruck bestätigen. Bitte ihnen auf",
                    "anderem Weg (Telefon) mitteilen. Bis dahin ruht der Austausch mit ihnen.",
                ]
                if emergency
                else ["Der alte Schlüssel gilt noch 30 Tage."]
            ),
            "Wenn das niemand von euch war: sofort Notfallwechsel, siehe docs/betrieb.md.",
        ],
    )
    transaction.on_commit(_announce_later)
    return ident


def _announce_later() -> None:
    from .tasks import announce_keys

    announce_keys.delay()


def daily() -> None:
    """Täglich: alte Schlüssel löschen, nach einem Jahr wechseln, Ankündigung wiederholen."""
    identity.drop_expired()
    if not services.enabled():
        return
    ident = identity.identity()
    changed = ident.last_change
    if changed is not None and timezone.now() - changed > identity.MAX_AGE:
        rotate(None)
        return
    if ident.sign_announcement(b"x"):
        # Übergangszeit läuft: wer den Wechsel noch nicht kennt, bekommt ihn erneut
        announce_all()


# --- Eine Gegenstelle wechselt ---


def _key(value) -> str:
    text = str(value or "")
    try:
        if len(identity.unb64(text)) != 32:
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise services.Refused(422, "Ungültiger Schlüssel.") from exc
    return text


def receive(peer: Peer, payload: dict) -> tuple[dict, transport.PeerKeys]:
    """Ankündigung prüfen. Die Anfrage ist schon mit einem bekannten Schlüssel geprüft."""
    public_key = _key(payload.get("public_key"))
    enc_public_key = _key(payload.get("enc_public_key"))
    at = str(payload.get("at", ""))[:40]
    when = parse_datetime(at)
    if when is None or when > timezone.now() + identity.TRANSITION:
        raise services.Refused(422, "Ungültiger Zeitpunkt.")
    statement = identity.key_statement(str(peer.instance_id), public_key, enc_public_key, at)
    if not identity.verify(public_key, statement, str(payload.get("proof", ""))):
        raise services.Refused(422, "Der neue Schlüssel ist nicht nachgewiesen.")
    new_keys = transport.PeerKeys(str(peer.instance_id), peer.base_url, public_key, enc_public_key)
    fingerprint = identity.fingerprint(public_key, enc_public_key)
    with transaction.atomic():
        peer = Peer.objects.select_for_update().get(pk=peer.pk)
        if peer.public_key == public_key and peer.enc_public_key == enc_public_key:
            return {"ok": True, "applied": True}, new_keys
        if payload.get("emergency") is True:
            if (peer.pending_keys or {}).get("public_key") == public_key:
                return {"ok": True, "pending": True}, new_keys
            peer.pending_keys = {
                "public_key": public_key,
                "enc_public_key": enc_public_key,
                "fingerprint": fingerprint,
                "at": at,
                "received_at": timezone.now().isoformat(),
            }
            peer.save(update_fields=["pending_keys"])
            _notify(peer, emergency=True, fingerprint=fingerprint)
            return {"ok": True, "pending": True}, new_keys
        if peer.pending_keys:
            raise services.Refused(
                409, "Hier wartet ein Notfallwechsel auf Bestätigung; geplanter Wechsel abgelehnt."
            )
        peer.previous_public_key = peer.public_key
        peer.previous_until = timezone.now() + identity.TRANSITION
        peer.public_key = public_key
        peer.enc_public_key = enc_public_key
        peer.fingerprint = fingerprint
        peer.keys_changed_at = timezone.now()
        peer.save()
        _notify(peer, emergency=False, fingerprint=fingerprint)
    return {"ok": True, "applied": True}, new_keys


def _notify(peer: Peer, *, emergency: bool, fingerprint: str) -> None:
    couplings = list(_open_couplings(peer))
    for c in couplings:
        services._audit(
            c,
            None,
            "Notfallwechsel der Schlüssel angekündigt" if emergency else "Schlüssel gewechselt",
            Fingerabdruck=fingerprint,
        )
    units = {c.local_unit_id: c for c in couplings}.values()
    if emergency:
        subject = f"Verbund: {peer.base_url} meldet einen Notfallwechsel der Schlüssel"
        text = (
            f"Die Instanz {peer.base_url} meldet, dass ihre Schlüssel vermutlich gestohlen wurden, "
            f"und hat neue erzeugt. Neuer Fingerabdruck: {fingerprint}\n\n"
            "Bis zur Bestätigung ruht der Austausch. Den Wechsel prüft und bestätigt die "
            "Plattformverwaltung dieser HUBIplan-Instanz; ihr bekommt danach eine Mitteilung. "
            "Wisst ihr von keinem Notfall bei der anderen Seite, sagt bitte der "
            "Plattformverwaltung Bescheid."
        )
        lines = [f"Instanz: {peer.base_url}", f"Neuer Fingerabdruck: {fingerprint}"]
        transaction.on_commit(
            lambda: send_alert("Verbund: Notfallwechsel einer Gegenstelle", lines)
        )
    else:
        subject = f"Verbund: {peer.base_url} hat die Schlüssel gewechselt"
        text = (
            f"Die Instanz {peer.base_url} hat ihre Schlüssel planmäßig gewechselt. Neuer "
            f"Fingerabdruck: {fingerprint}\n\nEs ist nichts zu tun. Wenn die andere Seite von "
            "keinem Wechsel weiß, bitte die Kopplung pausieren und nachfragen."
        )
    for c in units:
        unit = c.local_unit
        transaction.on_commit(lambda unit=unit: services._mail(unit, subject, text))


def pending_of(coupling: Coupling) -> dict | None:
    pending = coupling.peer.pending_keys or {}
    if not pending:
        return None
    return {
        "fingerprint": pending.get("fingerprint", ""),
        "at": pending.get("received_at") or pending.get("at"),
    }


def _norm(fingerprint: str) -> str:
    return "".join(str(fingerprint or "").split()).upper()


def pending_peers() -> list[dict]:
    """Für die Plattformverwaltung: Gegenstellen mit wartendem Notfallwechsel."""
    result = []
    for peer in Peer.objects.exclude(pending_keys={}).order_by("base_url"):
        units = sorted({c.local_unit.name for c in _open_couplings(peer)})
        result.append(
            {
                "id": peer.pk,
                "base_url": peer.base_url,
                "fingerprint": peer.pending_keys.get("fingerprint", ""),
                "at": peer.pending_keys.get("received_at") or peer.pending_keys.get("at"),
                "units": units,
            }
        )
    return result


def _tell_units(peer: Peer, subject: str, text: str) -> None:
    """Mitteilung an alle Einheiten mit Kopplung zu dieser Gegenstelle (FQ-11)."""
    units = {c.local_unit_id: c.local_unit for c in _open_couplings(peer)}.values()
    for unit in units:
        transaction.on_commit(lambda unit=unit: services._mail(unit, subject, text))


def confirm(peer: Peer, fingerprint: str, user) -> Peer:
    """Notfallwechsel der Gegenstelle bestätigen (gilt für alle Kopplungen mit ihr).

    Nur die Plattformverwaltung (Gesamtaudit 31.10.b, Frage 11): Die Gegenstelle ist
    eine gemeinsame Instanz, ein einzelner Verein soll nicht für alle entscheiden.
    """
    with transaction.atomic():
        peer = Peer.objects.select_for_update().get(pk=peer.pk)
        pending = peer.pending_keys or {}
        if not pending:
            raise ValidationError("Für diese Instanz wartet kein Schlüsselwechsel.")
        if not fingerprint or _norm(fingerprint) != _norm(pending["fingerprint"]):
            raise ValidationError(
                "Der Fingerabdruck passt nicht. Bitte nicht bestätigen und bei der anderen Seite "
                "nachfragen."
            )
        # Frisch prüfen: meldet die Gegenstelle selbst diese Schlüssel?
        try:
            info = transport.fetch_info(peer.base_url)
        except transport.PeerError as exc:
            raise ValidationError(f"Die andere Instanz antwortet nicht: {exc}") from exc
        if (
            str(info["instance_id"]) != str(peer.instance_id)
            or info["public_key"] != pending["public_key"]
            or info["enc_public_key"] != pending["enc_public_key"]
        ):
            raise ValidationError("Die andere Instanz meldet andere Schlüssel als angekündigt.")
        peer.public_key = pending["public_key"]
        peer.enc_public_key = pending["enc_public_key"]
        peer.fingerprint = pending["fingerprint"]
        # Der alte Schlüssel gilt nach einem Notfall sofort nicht mehr
        peer.previous_public_key = ""
        peer.previous_until = None
        peer.pending_keys = {}
        peer.keys_changed_at = timezone.now()
        peer.save()
        for c in _open_couplings(peer):
            services._audit(c, user, "Notfallwechsel der Schlüssel bestätigt")
            # Was bis hierhin liegen geblieben ist, sofort neu versuchen
            Message.objects.filter(
                coupling=c, direction=Message.Direction.OUT, state=Message.State.QUEUED
            ).update(next_try_at=timezone.now())
            pk = c.pk
            transaction.on_commit(lambda pk=pk: services.deliver_later(pk))
        _tell_units(
            peer,
            f"Verbund: neue Schlüssel von {peer.base_url} bestätigt",
            f"Die Plattformverwaltung hat den Notfallwechsel der Schlüssel von {peer.base_url} "
            f"bestätigt (Fingerabdruck {peer.fingerprint}). Der Austausch läuft wieder.",
        )
    return peer


def decline(peer: Peer, user) -> None:
    """Notfallwechsel ablehnen: Die bisherigen Schlüssel bleiben (nur Plattformverwaltung)."""
    with transaction.atomic():
        peer = Peer.objects.select_for_update().get(pk=peer.pk)
        if not peer.pending_keys:
            raise ValidationError("Für diese Instanz wartet kein Schlüsselwechsel.")
        peer.pending_keys = {}
        peer.save(update_fields=["pending_keys"])
        for c in _open_couplings(peer):
            services._audit(c, user, "Notfallwechsel der Schlüssel abgelehnt")
        _tell_units(
            peer,
            f"Verbund: Schlüsselwechsel von {peer.base_url} abgelehnt",
            f"Die Plattformverwaltung hat den angekündigten Notfallwechsel der Schlüssel von "
            f"{peer.base_url} abgelehnt. Es gelten die bisherigen Schlüssel; bitte mit der "
            "anderen Seite klären, was passiert ist.",
        )


def status() -> dict:
    """Für die Plattformverwaltung: eigene Schlüssel und wer den Wechsel kennt."""
    ident = identity.identity()
    return {
        "fingerprint": ident.fingerprint,
        "created": ident.created,
        "rotated_at": ident.rotated_at or None,
        "previous_until": ident.previous_until or None,
        "emergency": ident.previous_revoked and bool(ident.previous_until),
        "next_rotation": (
            (ident.last_change + identity.MAX_AGE).isoformat() if ident.last_change else None
        ),
        "peers": [
            {
                "base_url": p.base_url,
                "knows_current": p.our_fingerprint == ident.fingerprint,
            }
            for p in open_peers().order_by("base_url")
        ],
    }
