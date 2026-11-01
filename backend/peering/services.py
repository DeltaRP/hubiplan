"""Ablauf im Verbund: Koppeln, Pakete senden und empfangen, Abgleich, Lösen."""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import secrets

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext, gettext_noop

from core.i18n import datetime_text

from . import crypto, identity, packets, transport
from .models import Coupling, CouplingCode, Message, Peer

log = logging.getLogger(__name__)

CODE_PREFIX = "HUBIPLAN1-"
CODE_VALID = datetime.timedelta(hours=48)
# Wartezeiten bis zum nächsten Versuch (danach stündlich)
BACKOFF = [60, 5 * 60, 30 * 60]
WARN_AFTER = datetime.timedelta(hours=24)
# Pakete im Postausgang, die so lange nicht zugestellt sind, werden verworfen (Härtung H4).
# Die Stände entstehen beim nächsten Abgleich neu aus den aktuellen Daten.
MAX_QUEUE_AGE = datetime.timedelta(days=14)


def enabled() -> bool:
    from organizations.models import PlatformSettings

    return PlatformSettings.load().peering_enabled


def require_enabled() -> None:
    if not enabled():
        raise ValidationError(gettext("Der Verbund ist auf dieser Instanz nicht eingeschaltet."))


# --- Wer darf was ---


def can_offer(unit) -> bool:
    """Darf diese Einheit ferne Einheiten unter sich aufnehmen (Kopplungscode)?

    Ein Dachverband nimmt ferne Vereine auf, ein Verein ferne Untereinheiten (Schritt 8)."""
    return (
        unit.type in (unit.Type.FEDERATION, unit.Type.CLUB)
        and not unit.is_remote
        and unit.is_active
    )


def can_join(unit) -> bool:
    """Darf diese Einheit sich unter eine ferne Einheit koppeln?

    Nur Einheiten mit eigenen Mitgliedern ohne lokale Einheit darüber (Fachfrage 1)."""
    from organizations.models import Organization

    if unit.type != Organization.Type.CLUB or unit.is_remote or not unit.is_active:
        return False
    if unit.parent and unit.parent.type != Organization.Type.PLATFORM:
        return False
    return not open_parent_coupling(unit)


def open_parent_coupling(unit) -> Coupling | None:
    return (
        Coupling.objects.filter(local_unit=unit, direction=Coupling.Direction.PARENT)
        .exclude(state__in=[Coupling.State.ENDED, Coupling.State.MOVED])
        .select_related("remote_unit", "peer")
        .first()
    )


def remote_parent(unit):
    """Platzhalter der fernen Einheit darüber, wenn die Kopplung aktiv ist."""
    if unit is None or unit.is_remote:
        return None
    coupling = open_parent_coupling(unit)
    if coupling and coupling.state == Coupling.State.ACTIVE:
        return coupling.remote_unit
    return None


# --- Kopplungscode ---


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def create_code(unit, user, valid: datetime.timedelta = CODE_VALID) -> tuple[str, CouplingCode]:
    require_enabled()
    if not can_offer(unit):
        raise ValidationError(gettext("Diese Einheit kann keine fernen Einheiten aufnehmen."))
    secret = secrets.token_urlsafe(24)
    code = CouplingCode.objects.create(
        unit=unit,
        secret_hash=_hash(secret),
        expires_at=timezone.now() + valid,
        created_by=user,
    )
    ident = identity.identity()
    data = {
        "u": identity.base_url(),
        "e": str(unit.uuid),
        "f": ident.fingerprint.replace(" ", ""),
        "s": secret,
    }
    if unit.type == unit.Type.CLUB:
        data["k"] = packets.CLUB  # obere Seite ist ein Verein (Schritt 8)
    text = CODE_PREFIX + identity.b64(json.dumps(data, separators=(",", ":")).encode())
    return text, code


def parse_code(text: str) -> dict:
    text = "".join((text or "").split())
    if not text.startswith(CODE_PREFIX):
        raise ValidationError(gettext("Das ist kein HUBIplan-Kopplungscode."))
    try:
        data = json.loads(identity.unb64(text[len(CODE_PREFIX) :]))
        result = {
            "base_url": transport.normalize_url(str(data["u"])),
            "unit": str(data["e"]),
            "fingerprint": str(data["f"]).upper(),
            "secret": str(data["s"]),
            "upper": packets.CLUB if data.get("k") == packets.CLUB else packets.FEDERATION,
        }
    except (KeyError, ValueError, TypeError, transport.PeerError) as exc:
        raise ValidationError(
            gettext("Der Kopplungscode ist unvollständig oder beschädigt.")
        ) from exc
    return result


def _code_for(unit_uuid: str, secret: str) -> CouplingCode:
    from organizations.models import Organization

    code = (
        CouplingCode.objects.select_related("unit")
        .filter(secret_hash=_hash(secret), unit__uuid=unit_uuid)
        .first()
    )
    if code is None or not code.usable or not can_offer(code.unit):
        raise ValidationError(gettext("Der Kopplungscode ist ungültig oder abgelaufen."))
    assert isinstance(code.unit, Organization)  # noqa: S101
    return code


def keys_of(peer_or_info) -> transport.PeerKeys:
    if isinstance(peer_or_info, Peer):
        p = peer_or_info
        return transport.PeerKeys(
            str(p.instance_id), p.base_url, p.public_key, p.enc_public_key, p.valid_previous_key
        )
    i = peer_or_info
    return transport.PeerKeys(i["instance_id"], i["base_url"], i["public_key"], i["enc_public_key"])


def _remote_info(parsed: dict) -> dict:
    try:
        info = transport.fetch_info(parsed["base_url"])
    except transport.PeerError as exc:
        raise ValidationError(
            gettext("Die andere Instanz antwortet nicht: {exc}").format(exc=exc)
        ) from exc
    if info["fingerprint"].replace(" ", "") != parsed["fingerprint"]:
        raise ValidationError(
            gettext(
                "Der Fingerabdruck der anderen Instanz passt nicht zum Kopplungscode. "
                "Bitte nicht koppeln und die andere Seite fragen."
            )
        )
    if str(info["instance_id"]) == identity.identity().instance_id:
        raise ValidationError(gettext("Der Code stammt von dieser Instanz selbst."))
    return info


def inspect_code(unit, text: str) -> dict:
    """Vorschau vor dem Koppeln: wer ist die andere Seite, was fließt?"""
    require_enabled()
    if not can_join(unit):
        raise ValidationError(
            gettext("Diese Einheit kann sich nicht unter eine ferne Einheit koppeln.")
        )
    parsed = parse_code(text)
    info = _remote_info(parsed)
    try:
        answer = transport.call(
            keys_of(info),
            "/api/peering/v1/pair/inspect/",
            {"base_url": identity.base_url(), "unit": parsed["unit"], "secret": parsed["secret"]},
        )
    except transport.PeerError as exc:
        raise ValidationError(
            gettext("Abfrage bei der anderen Instanz fehlgeschlagen: {exc}").format(exc=exc)
        ) from exc
    _check_kind(parsed, answer)
    probe = Coupling(direction=Coupling.Direction.PARENT, options={"upper": parsed["upper"]})
    return {
        "remote": {
            "name": str(answer.get("name", ""))[:200],
            "base_url": info["base_url"],
            "country": str(info.get("country", ""))[:10],
            "fingerprint": info["fingerprint"],
            "kind": parsed["upper"],
        },
        "send": packet_choices(probe, packets.defaults(probe)),
        "receive": [
            {"key": p.key, "label": p.label, "personal": p.personal}
            for p in packets.receivable(probe)
        ],
    }


def _check_kind(parsed: dict, answer: dict) -> None:
    """Code und Antwort müssen dieselbe Art der oberen Seite nennen (ältere Instanzen: keine)."""
    kind = answer.get("kind")
    if kind is not None and kind != parsed["upper"]:
        raise ValidationError(gettext("Der Kopplungscode passt nicht zur Art der anderen Einheit."))


def kind_of(unit) -> str:
    return packets.CLUB if unit.type == unit.Type.CLUB else packets.FEDERATION


def packet_choices(coupling: Coupling, current: dict) -> list[dict]:
    return [
        {
            "key": p.key,
            "label": p.label,
            "personal": p.personal,
            "levels": [{"value": v, "label": label} for v, label in p.levels],
            "value": current.get(p.key),
        }
        for p in packets.sendable(coupling)
    ]


def _placeholder(name: str, *, parent, type_):
    from organizations.models import Organization

    return Organization.objects.create(
        name=name[:200] or "Ferne Einheit",
        type=type_,
        parent=parent,
        is_remote=True,
        enabled_modules=[],
        events_share_up=True,
        events_share_down=True,
    )


def _child_placeholder(upper, name: str):
    """Platzhalter der fernen Einheit darunter.

    Unter einem Dachverband ein Verein, unter einem Verein eine Untereinheit in dessen
    Datenbereich (Schritt 8): Ihre Termine erscheinen dann wie die jeder Untereinheit."""
    from organizations.models import Department, Organization

    if upper.type != Organization.Type.CLUB:
        return _placeholder(name, parent=upper, type_=Organization.Type.CLUB)
    return Department.objects.create(
        name=name[:200] or "Ferne Einheit",
        organization=upper,
        parent=upper,
        is_remote=True,
        enabled_modules=[],
        events_share_up=True,
        events_share_down=True,
    )


def _store_peer(info: dict) -> Peer:
    """Andere Instanz speichern; ihr Schlüssel ist danach festgehalten (Pinning)."""
    peer = Peer.objects.filter(instance_id=info["instance_id"]).first()
    if peer is not None:
        if peer.public_key != info["public_key"] or peer.enc_public_key != info["enc_public_key"]:
            from core.alarm import send_alert

            send_alert(
                "Verbund: Gegenstelle meldet einen anderen Schlüssel",
                [
                    f"Instanz: {info['base_url']} ({peer.instance_id})",
                    f"Gespeicherter Fingerabdruck: {peer.fingerprint}",
                    f"Gemeldeter Fingerabdruck: {info['fingerprint']}",
                    "Ein Schlüsselwechsel kommt sonst als eigene Ankündigung. Bitte nachfragen.",
                ],
            )
            raise ValidationError(
                gettext("Die andere Instanz meldet einen anderen Schlüssel als bisher bekannt.")
            )
        peer.base_url = info["base_url"]
        peer.versions = info.get("versions") or [1]
        peer.country = str(info.get("country", ""))[:10]
        peer.last_seen_at = timezone.now()
        peer.save()
        return peer
    return Peer.objects.create(
        instance_id=info["instance_id"],
        base_url=info["base_url"],
        public_key=info["public_key"],
        enc_public_key=info["enc_public_key"],
        fingerprint=info["fingerprint"],
        versions=info.get("versions") or [1],
        country=str(info.get("country", ""))[:10],
        last_seen_at=timezone.now(),
    )


def request_coupling(unit, text: str, chosen: dict, user) -> Coupling:
    """Untere Einheit koppelt sich mit dem Code unter die ferne Einheit."""
    from organizations.models import Organization

    require_enabled()
    if not can_join(unit):
        raise ValidationError(
            gettext("Diese Einheit kann sich nicht unter eine ferne Einheit koppeln.")
        )
    parsed = parse_code(text)
    info = _remote_info(parsed)
    probe = Coupling(
        direction=Coupling.Direction.PARENT, local_unit=unit, options={"upper": parsed["upper"]}
    )
    levels = packets.clean_levels(probe, chosen)
    probe.packets = levels
    try:
        answer = transport.call(
            keys_of(info),
            "/api/peering/v1/pair/request/",
            {
                "base_url": identity.base_url(),
                "unit": parsed["unit"],
                "secret": parsed["secret"],
                "child": {"uuid": str(unit.uuid), "name": unit.name},
                "packets": levels,
                "versions": [1],
            },
        )
    except transport.RemoteRefused as exc:
        raise ValidationError(
            gettext("Die andere Instanz lehnt ab: {exc}").format(exc=exc)
        ) from exc
    except transport.PeerError as exc:
        raise ValidationError(gettext("Kopplung fehlgeschlagen: {exc}").format(exc=exc)) from exc
    _check_kind(parsed, answer)
    with transaction.atomic():
        peer = _store_peer(info)
        remote = _placeholder(
            str(answer.get("name", "")),
            parent=Organization.platform(),
            type_=Organization.Type.FEDERATION,
        )
        coupling = Coupling.objects.create(
            local_unit=unit,
            remote_unit=remote,
            remote_uuid=parsed["unit"],
            peer=peer,
            direction=Coupling.Direction.PARENT,
            state=Coupling.State.REQUESTED,
            packets=levels,
            remote_packets=answer.get("packets") or {},
            created_by=user,
        )
        coupling.remote_packets = _clean_remote(coupling, coupling.remote_packets)
        coupling.options = {"accept": dict(coupling.remote_packets)}
        if parsed["upper"] == packets.CLUB:
            coupling.options["upper"] = packets.CLUB
        coupling.save(update_fields=["remote_packets", "options"])
        _audit(coupling, user, "Kopplung angefragt")
    return coupling


# --- Gegenseite: Anfragen beantworten ---


def handle_inspect(payload: dict) -> dict:
    code = _code_for(str(payload.get("unit", "")), str(payload.get("secret", "")))
    return {"name": code.unit.name, "kind": kind_of(code.unit)}


def handle_request(info: dict, payload: dict) -> dict:
    require_enabled()
    child = payload.get("child") or {}
    with transaction.atomic():
        code = _code_for(str(payload.get("unit", "")), str(payload.get("secret", "")))
        code = CouplingCode.objects.select_for_update().get(pk=code.pk)
        if not code.usable:
            raise ValidationError(gettext("Der Kopplungscode ist schon benutzt."))
        try:
            child_uuid = str(__import__("uuid").UUID(str(child.get("uuid"))))
        except ValueError as exc:
            raise ValidationError(gettext("Ungültige Kennung der Einheit.")) from exc
        peer = _store_peer(info)
        if (
            Coupling.objects.filter(peer=peer, remote_uuid=child_uuid)
            .exclude(state__in=[Coupling.State.ENDED, Coupling.State.MOVED])
            .exists()
        ):
            raise ValidationError(gettext("Diese Einheit ist hier schon gekoppelt."))
        from . import spinoff

        spin = spinoff.placeholder_for(code)
        remote = spin.unit if spin else _child_placeholder(code.unit, str(child.get("name", "")))
        coupling = Coupling(
            local_unit=code.unit,
            remote_unit=remote,
            remote_uuid=child_uuid,
            peer=peer,
            direction=Coupling.Direction.CHILD,
            state=Coupling.State.PENDING,
        )
        coupling.remote_packets = _clean_remote(coupling, payload.get("packets") or {})
        coupling.packets = packets.defaults(coupling)
        coupling.save()
        code.used_at = timezone.now()
        code.save(update_fields=["used_at"])
        if spin:
            spinoff.requested(spin, coupling)
        _audit(coupling, None, f"Kopplungsanfrage von {info['base_url']} eingegangen")
    transaction.on_commit(lambda: _notify_pending(coupling.pk))
    return {"name": code.unit.name, "kind": kind_of(code.unit), "packets": coupling.packets}


def _clean_remote(coupling: Coupling, given: dict) -> dict:
    allowed = {p.key: {v for v, _ in p.levels} for p in packets.receivable(coupling)}
    return {k: v for k, v in (given or {}).items() if k in allowed and v in allowed[k]}


# --- Bestätigen, Freigaben, Pausieren, Lösen ---


def accept(coupling: Coupling, user, chosen: dict | None = None) -> Coupling:
    require_enabled()
    if coupling.state != Coupling.State.PENDING:
        raise ValidationError(gettext("Diese Kopplung wartet nicht auf eine Bestätigung."))
    with transaction.atomic():
        coupling = Coupling.objects.select_for_update().get(pk=coupling.pk)
        if chosen is not None:
            coupling.packets = packets.clean_levels(coupling, chosen)
        coupling.state = Coupling.State.ACTIVE
        coupling.activated_at = timezone.now()
        # Was der Vorstand hier beim Bestätigen gesehen hat, ist die Höchststufe (Härtung H4)
        coupling.options = {**(coupling.options or {}), "accept": dict(coupling.remote_packets)}
        coupling.save()
        from . import spinoff

        # Vor der Nachricht an die Gegenseite: ihr erster Stand trifft schon die Umstellung
        spinoff.accepted(coupling, user)
        enqueue(coupling, "coupling.accept", {"packets": coupling.packets})
        _audit(coupling, user, "Kopplung bestätigt")
    sync(coupling)
    return coupling


def decline(coupling: Coupling, user) -> None:
    if coupling.state != Coupling.State.PENDING:
        raise ValidationError(gettext("Diese Kopplung wartet nicht auf eine Bestätigung."))
    end(coupling, user, reason="abgelehnt")


def set_packets(coupling: Coupling, chosen: dict, user) -> Coupling:
    with transaction.atomic():
        coupling = Coupling.objects.select_for_update().get(pk=coupling.pk)
        before = dict(coupling.packets)
        coupling.packets = packets.clean_levels(coupling, chosen)
        coupling.save(update_fields=["packets"])
        if coupling.state in (Coupling.State.ACTIVE, Coupling.State.PAUSED):
            enqueue(coupling, "coupling.config", {"packets": coupling.packets})
        if before != coupling.packets:
            _audit(coupling, user, "Freigaben geändert", before=before, after=coupling.packets)
    if coupling.state == Coupling.State.ACTIVE:
        sync(coupling)
    return coupling


def set_paused(coupling: Coupling, paused: bool, user) -> Coupling:
    target = Coupling.State.PAUSED if paused else Coupling.State.ACTIVE
    if coupling.state not in (Coupling.State.ACTIVE, Coupling.State.PAUSED):
        raise ValidationError(gettext("Die Kopplung ist nicht aktiv."))
    with transaction.atomic():
        coupling = Coupling.objects.select_for_update().get(pk=coupling.pk)
        coupling.state = target
        coupling.save(update_fields=["state"])
        _audit(coupling, user, "Kopplung pausiert" if paused else "Kopplung fortgesetzt")
    if not paused:
        transaction.on_commit(lambda: deliver_later(coupling.pk))
        sync(coupling)
    return coupling


def end(coupling: Coupling, user, reason: str = "gelöst", notify: bool = True) -> None:
    """Kopplung lösen. Die andere Seite wird benachrichtigt (wenn erreichbar)."""
    if coupling.state in (Coupling.State.ENDED, Coupling.State.MOVED):
        return
    if notify:
        _try_notify_end(coupling)
    with transaction.atomic():
        coupling = Coupling.objects.select_for_update().get(pk=coupling.pk)
        coupling.state = Coupling.State.ENDED
        coupling.ended_at = timezone.now()
        coupling.save(update_fields=["state", "ended_at"])
        Message.objects.filter(coupling=coupling, state=Message.State.QUEUED).update(
            state=Message.State.FAILED, payload=None, last_error="Kopplung gelöst"
        )
        from . import spinoff

        spinoff.ended(coupling)
        cleanup(coupling)
        _audit(coupling, user, f"Kopplung {reason}")


def _try_notify_end(coupling: Coupling) -> None:
    """Direkt melden (nicht über den Postausgang, der beim Lösen geleert wird)."""
    try:
        transport.call(
            keys_of(coupling.peer),
            "/api/peering/v1/inbox/",
            _envelope(coupling, "coupling.end", {}, seq=coupling.out_seq + 1),
        )
    except transport.PeerError as exc:
        log.info("Kopplung %s: Lösen nicht zustellbar (%s)", coupling.pk, exc)


def cleanup(coupling: Coupling) -> None:
    """Kopien der Gegenseite nach dem Lösen entfernen (Konzept 6.4).

    Der Platzhalter bleibt deaktiviert bestehen, solange Rechnungen oder Buchungen
    auf ihn verweisen; seine Kopien (Termine, Vorstand, Dokumente …) gehen.
    """
    if not coupling.remote_unit.is_remote:
        # Ausgliederung vor der Bestätigung beendet: die Untereinheit bleibt, wie sie war
        return
    for packet in packets.receivable(coupling):
        if packet.apply:
            try:
                packet.apply(coupling, {"level": None, "ended": True})
            except Exception:  # noqa: BLE001
                log.exception("Aufräumen %s fehlgeschlagen", packet.key)
    org = coupling.remote_unit
    org.is_active = False
    org.save(update_fields=["is_active"])


# --- Postausgang ---


def _envelope(coupling: Coupling, kind: str, data: dict, *, seq: int, msg_id=None) -> dict:
    return {
        "msg_id": str(msg_id or __import__("uuid").uuid4()),
        "seq": seq,
        "kind": kind,
        "schema": 1,
        "from_unit": str(coupling.local_unit.uuid),
        "to_unit": str(coupling.remote_uuid),
        "data": data,
    }


def enqueue(coupling: Coupling, kind: str, data: dict, persons: int = 0) -> Message:
    """Paket in den Postausgang legen (innerhalb einer Transaktion aufrufen)."""
    locked = Coupling.objects.select_for_update().get(pk=coupling.pk)
    locked.out_seq += 1
    locked.save(update_fields=["out_seq"])
    coupling.out_seq = locked.out_seq
    msg = Message.objects.create(
        coupling=locked,
        direction=Message.Direction.OUT,
        seq=locked.out_seq,
        kind=kind,
        payload=None,
        persons=persons,
        next_try_at=timezone.now(),
    )
    # Gleich für die Empfängerin versiegeln: In der Datenbank steht nur Chiffretext, den
    # diese Instanz selbst nicht mehr lesen kann (Härtung H4)
    peer = coupling.peer
    envelope = _envelope(coupling, kind, data, seq=msg.seq, msg_id=msg.msg_id)
    msg.payload = {
        "sealed": crypto.seal(
            envelope,
            sender=identity.identity().instance_id,
            recipient=str(peer.instance_id),
            recipient_enc_key=peer.enc_public_key,
        )
    }
    msg.save(update_fields=["payload"])
    transaction.on_commit(lambda: deliver_later(coupling.pk))
    return msg


def deliver_later(coupling_id: int) -> None:
    from .tasks import deliver_coupling

    deliver_coupling.delay(coupling_id)


def deliver(coupling_id: int) -> None:
    """Wartende Pakete einer Kopplung der Reihe nach zustellen."""
    coupling = Coupling.objects.select_related("peer", "local_unit").filter(pk=coupling_id).first()
    if coupling is None or coupling.state in (
        Coupling.State.ENDED,
        Coupling.State.MOVED,
        Coupling.State.MOVING,
    ):
        return
    now = timezone.now()
    queued = Message.objects.filter(
        coupling=coupling, direction=Message.Direction.OUT, state=Message.State.QUEUED
    ).order_by("seq")
    dropped = 0
    for msg in queued:
        sealed = (msg.payload or {}).get("sealed")
        if msg.created_at < now - MAX_QUEUE_AGE or (
            sealed and sealed.get("to") != str(coupling.peer.instance_id)
        ):
            # Zu alt oder für eine frühere Adresse der Gegenstelle versiegelt (Umzug)
            _mark(msg, Message.State.FAILED, "verworfen: nicht zugestellt, Stand wird neu gebaut")
            dropped += 1
            if dropped == 1:
                _on_dropped(coupling)
            continue
        if msg.next_try_at and msg.next_try_at > now:
            break  # Reihenfolge halten: spätere warten mit
        if coupling.state == Coupling.State.PAUSED and not msg.kind.startswith("coupling."):
            break
        if coupling.state in (Coupling.State.REQUESTED, Coupling.State.PENDING) and msg.kind != (
            "coupling.accept"
        ):
            break
        if sealed:
            envelope = None
        else:  # Pakete aus der Zeit vor H4 (Klartext im Postausgang)
            envelope = _envelope(
                coupling, msg.kind, msg.payload or {}, seq=msg.seq, msg_id=msg.msg_id
            )
        try:
            transport.call(
                keys_of(coupling.peer), "/api/peering/v1/inbox/", envelope, sealed=sealed
            )
        except transport.RemoteRefused as exc:
            if exc.status in (423, 503):  # pausiert / gerade nicht möglich: später
                _retry(coupling, msg, str(exc))
                break
            if exc.status == 410:  # Gegenseite hat gelöst
                _mark(msg, Message.State.REJECTED, str(exc))
                end(coupling, None, reason="von der anderen Seite gelöst", notify=False)
                return
            _mark(msg, Message.State.REJECTED, str(exc))
            continue
        except transport.PeerError as exc:
            _retry(coupling, msg, str(exc))
            break
        _mark(msg, Message.State.DONE, "")
        Coupling.objects.filter(pk=coupling.pk).update(
            last_contact_at=timezone.now(), last_error="", error_since=None, warned_at=None
        )


def _on_dropped(coupling: Coupling) -> None:
    """Pakete verworfen: Stände neu bauen lassen, Vorstand täglich höchstens einmal informieren."""
    from django.core.cache import cache

    Coupling.objects.filter(pk=coupling.pk).update(
        sent_hashes={},
        last_error="Pakete nach 14 Tagen ohne Zustellung verworfen; der aktuelle Stand wird "
        "beim nächsten Kontakt neu gesendet.",
    )
    coupling.sent_hashes = {}
    if cache.add(f"peering:dropped:{coupling.pk}", 1, 24 * 3600):
        unit, remote, base = coupling.local_unit, coupling.remote_unit.name, coupling.peer.base_url
        transaction.on_commit(
            lambda: _mail(
                unit,
                gettext_noop("Verbund: Pakete an {remote} verworfen"),
                gettext_noop(
                    "{remote} ({base}) war 14 Tage lang nicht erreichbar. Die wartenden Pakete "
                    "wurden gelöscht, damit keine Daten unbegrenzt auf dem Server liegen. Sobald "
                    "die andere Seite wieder erreichbar ist, geht der aktuelle Stand neu hinaus. "
                    "Einzelne Mitteilungen (z. B. Korrekturvorschläge, Rundschreiben zur "
                    "Weitergabe) bitte bei Bedarf erneut senden."
                ),
                remote=remote,
                base=base,
            )
        )


def _mark(msg: Message, state: str, error: str) -> None:
    msg.state = state
    msg.last_error = error[:500]
    msg.done_at = timezone.now()
    msg.payload = None  # Inhalt nicht aufbewahren
    msg.save(update_fields=["state", "last_error", "done_at", "payload"])


def _retry(coupling: Coupling, msg: Message, error: str) -> None:
    wait = BACKOFF[msg.attempts] if msg.attempts < len(BACKOFF) else 3600
    msg.attempts += 1
    msg.last_error = error[:500]
    msg.next_try_at = timezone.now() + datetime.timedelta(seconds=wait)
    msg.save(update_fields=["attempts", "last_error", "next_try_at"])
    fields = {"last_error": error[:500]}
    if coupling.error_since is None:
        fields["error_since"] = timezone.now()
    Coupling.objects.filter(pk=coupling.pk).update(**fields)


def deliver_due() -> None:
    """Regelmäßig: fällige Pakete aller Kopplungen zustellen, bei Stau warnen."""
    ids = (
        Message.objects.filter(
            direction=Message.Direction.OUT,
            state=Message.State.QUEUED,
            next_try_at__lte=timezone.now(),
        )
        .values_list("coupling_id", flat=True)
        .distinct()
    )
    for coupling_id in list(ids):
        deliver(coupling_id)
    warn_stuck()


# --- Stände bauen und abgleichen ---


def sync(coupling: Coupling) -> int:
    """Geänderte Stände in den Postausgang legen. Gibt die Anzahl zurück."""
    if coupling.state != Coupling.State.ACTIVE:
        return 0
    count = 0
    with transaction.atomic():
        coupling = (
            Coupling.objects.select_for_update().select_related("local_unit").get(pk=coupling.pk)
        )
        hashes = dict(coupling.sent_hashes or {})
        for packet in packets.sendable(coupling):
            if packet.build is None:
                continue  # Vorgänge statt Stand (z. B. Rechnungen)
            data = packets.build(coupling, packet)
            digest = packets.digest(data)
            if hashes.get(packet.key) == digest:
                continue
            persons = packet.persons(data) if packet.persons else 0
            enqueue(coupling, f"packet.{packet.key}", data, persons=persons)
            hashes[packet.key] = digest
            count += 1
        coupling.sent_hashes = hashes
        coupling.last_sync_at = timezone.now()
        coupling.save(update_fields=["sent_hashes", "last_sync_at"])
    return count


def sync_all() -> None:
    for coupling in Coupling.objects.filter(state=Coupling.State.ACTIVE):
        try:
            sync(coupling)
        except Exception:  # noqa: BLE001
            log.exception("Abgleich der Kopplung %s fehlgeschlagen", coupling.pk)


def reconcile(coupling: Coupling) -> list[str]:
    """Täglicher Abgleich: Prüfsummen der Gegenseite holen, Abweichendes neu senden."""
    if coupling.state != Coupling.State.ACTIVE:
        return []
    try:
        answer = transport.call(
            keys_of(coupling.peer),
            "/api/peering/v1/status/",
            {"from_unit": str(coupling.local_unit.uuid), "to_unit": str(coupling.remote_uuid)},
        )
    except transport.PeerError as exc:
        log.info("Abgleich %s: %s", coupling.pk, exc)
        return []
    theirs = answer.get("received") or {}
    pending = set(
        Message.objects.filter(coupling=coupling, state=Message.State.QUEUED).values_list(
            "kind", flat=True
        )
    )
    stale = [
        key
        for key, digest in (coupling.sent_hashes or {}).items()
        if theirs.get(key) != digest and f"packet.{key}" not in pending
    ]
    if stale:
        with transaction.atomic():
            locked = Coupling.objects.select_for_update().get(pk=coupling.pk)
            locked.sent_hashes = {
                k: v for k, v in (locked.sent_hashes or {}).items() if k not in stale
            }
            locked.save(update_fields=["sent_hashes"])
        sync(Coupling.objects.get(pk=coupling.pk))
    return stale


def reconcile_all() -> None:
    for coupling in Coupling.objects.filter(state=Coupling.State.ACTIVE).select_related(
        "peer", "local_unit"
    ):
        reconcile(coupling)


# --- Eingang ---


class Refused(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def find_coupling(peer: Peer, payload: dict) -> Coupling:
    coupling = (
        Coupling.objects.select_related("local_unit", "remote_unit", "peer")
        .filter(
            peer=peer,
            remote_uuid=str(payload.get("from_unit", "")),
            local_unit__uuid=str(payload.get("to_unit", "")),
        )
        .order_by("-created_at")
        .first()
    )
    if coupling is None:
        raise Refused(404, "Kopplung unbekannt.")
    return coupling


def receive(peer: Peer, payload: dict) -> dict:
    """Ein Paket der Gegenseite verarbeiten.

    Gesucht wird ohne RLS; verarbeitet wird mit RLS im Bereich der lokalen Einheit,
    damit ein Fehler in einem Paket nie Daten anderer Einheiten erreicht."""
    from core.tenancy import unit_context

    try:
        coupling = find_coupling(peer, payload)
    except ValidationError as exc:
        raise Refused(400, "Ungültige Angaben.") from exc
    with unit_context(coupling.local_unit_id):
        return _receive(coupling, payload)


def _receive(coupling: Coupling, payload: dict) -> dict:
    kind = str(payload.get("kind", ""))
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        raise Refused(400, "Ungültiger Inhalt.")
    try:
        seq = int(payload.get("seq"))
        msg_id = __import__("uuid").UUID(str(payload.get("msg_id")))
    except (TypeError, ValueError) as exc:
        raise Refused(400, "Ungültige Paketnummer.") from exc
    if coupling.state == Coupling.State.MOVED:
        target = (coupling.options or {}).get("moved_to", "")
        raise Refused(410, f"Die Einheit ist umgezogen{f' nach {target}' if target else ''}.")
    if coupling.state == Coupling.State.ENDED:
        raise Refused(410, "Die Kopplung ist gelöst.")
    if kind == "unit.moved":
        from . import moving

        try:
            with transaction.atomic():
                locked = (
                    Coupling.objects.select_for_update().select_related("peer").get(pk=coupling.pk)
                )
                moving.receive_moved(locked, data)
        except (ValidationError, transport.PeerError) as exc:
            raise Refused(422, f"Umzug nicht übernommen: {exc}") from exc
        return {"ok": True}
    if kind == "coupling.end":
        end(coupling, None, reason="von der anderen Seite gelöst", notify=False)
        return {"ok": True}
    if coupling.state == Coupling.State.PAUSED and not kind.startswith("coupling."):
        raise Refused(423, "Die Kopplung ist hier pausiert.")
    if coupling.state == Coupling.State.MOVING:
        raise Refused(423, "Hier wartet ein angekündigter Umzug auf Bestätigung.")
    if Message.objects.filter(direction=Message.Direction.IN, msg_id=msg_id).exists():
        return {"ok": True, "duplicate": True}
    with transaction.atomic():
        coupling = Coupling.objects.select_for_update().get(pk=coupling.pk)
        stale = seq <= coupling.in_seq
        persons = 0
        if not stale:
            persons = _process(coupling, kind, data)
            coupling.in_seq = seq
        coupling.last_contact_at = timezone.now()
        # Nur die Felder des Eingangs: ein Versand während der Verarbeitung zählt
        # out_seq hoch und darf nicht überschrieben werden
        coupling.save(update_fields=RECEIVE_FIELDS)
        Message.objects.create(
            coupling=coupling,
            direction=Message.Direction.IN,
            msg_id=msg_id,
            seq=seq,
            kind=kind[:40],
            payload=None,
            persons=persons,
            state=Message.State.DONE,
            done_at=timezone.now(),
            last_error="älter als der bekannte Stand" if stale else "",
        )
    return {"ok": True}


RECEIVE_FIELDS = [
    "state",
    "activated_at",
    "remote_packets",
    "received_hashes",
    "in_seq",
    "last_contact_at",
]


def _process(coupling: Coupling, kind: str, data: dict) -> int:
    if kind == "coupling.accept":
        if coupling.state != Coupling.State.REQUESTED:
            return 0
        coupling.state = Coupling.State.ACTIVE
        coupling.activated_at = timezone.now()
        coupling.remote_packets = _clean_remote(coupling, data.get("packets") or {})
        coupling.save(update_fields=["state", "activated_at", "remote_packets"])
        # Erste Freigabe der oberen Seite gilt (die untere hat mit ihrem Code angefragt);
        # mehr später nur nach Zustimmung
        _offer(coupling, coupling.remote_packets, first=True)
        _audit(coupling, None, "Kopplung von der anderen Seite bestätigt")
        transaction.on_commit(lambda: sync(Coupling.objects.get(pk=coupling.pk)))
        return 0
    if kind == "coupling.config":
        accepted(coupling)  # ältere Kopplung: bisherigen Stand als Zustimmung festhalten
        coupling.remote_packets = _clean_remote(coupling, data.get("packets") or {})
        _offer(coupling, coupling.remote_packets)
        return 0
    if kind.startswith("packet."):
        key = kind[len("packet.") :]
        packet = packets.REGISTRY.get(key)
        if packet is None or packet not in packets.receivable(coupling):
            raise Refused(422, f"Paket „{key}“ wird hier nicht angenommen.")
        if coupling.state != Coupling.State.ACTIVE:
            raise Refused(423, "Die Kopplung ist noch nicht aktiv.")
        # Nur bis zur Stufe, der diese Seite zugestimmt hat (leerer Stand immer, Härtung H4)
        level = data.get("level")
        if level and rank(packet, level) > rank(packet, accepted(coupling).get(key)):
            raise Refused(
                422,
                f"Paket „{packet.label}“ in dieser Stufe hier nicht freigegeben; "
                "der Vorstand muss erst zustimmen.",
            )
        if level and coupling.remote_level(key) != level:
            coupling.remote_packets = {**(coupling.remote_packets or {}), key: level}
        try:
            packet.apply(coupling, data)
        except ValidationError as exc:
            raise Refused(422, "; ".join(exc.messages)) from exc
        hashes = dict(coupling.received_hashes or {})
        hashes[key] = packets.digest(data)
        coupling.received_hashes = hashes
        return packet.persons(data) if packet.persons else 0
    if kind == "register.numbers":
        from . import register

        register.receive_numbers(coupling, data)
        return 0
    if kind == "register.suggest":
        from . import register

        return register.receive_suggestion(coupling, data)
    if kind in ("circular.forward", "circular.report"):
        from . import packet_circulars

        if coupling.state != Coupling.State.ACTIVE:
            raise Refused(423, "Die Kopplung ist noch nicht aktiv.")
        if kind == "circular.forward":
            # Nur, wenn diese Seite Rundschreiben angenommen hat (INF-S01)
            _require_accepted(coupling, packet_circulars.KEY)
            packet_circulars.receive_forward(coupling, data)
            return 0
        packet_circulars.receive_report(coupling, data)
        return 0
    if kind.startswith("transfer."):
        from . import transfers

        if coupling.state != Coupling.State.ACTIVE:
            raise Refused(423, "Die Kopplung ist noch nicht aktiv.")
        try:
            if coupling.direction == Coupling.Direction.CHILD:
                # Oben betrifft ein Wechsel mehrere Einheiten des Verbandsbereichs (bisheriger
                # Verein, Platzhalter, Wechselanfrage): bewusst ohne RLS, wie bisher
                from core.tenancy import rls_bypass

                with rls_bypass():
                    transfers.receive(coupling, kind, data)
            else:
                transfers.receive(coupling, kind, data)
        except ValidationError as exc:
            raise Refused(422, "; ".join(exc.messages)) from exc
        return 1
    if kind.startswith("invoice."):
        from . import packet_invoices

        if coupling.state != Coupling.State.ACTIVE:
            raise Refused(423, "Die Kopplung ist noch nicht aktiv.")
        if kind == "invoice.issue":
            # Neue Rechnungen nur, wenn diese Seite Rechnungen angenommen hat (INF-S01);
            # Storno und Stand bereits bekannter Rechnungen kommen weiter an
            _require_accepted(coupling, packet_invoices.KEY)
        try:
            packet_invoices.receive(coupling, kind, data)
        except ValidationError as exc:
            raise Refused(422, "; ".join(exc.messages)) from exc
        return 0
    raise Refused(422, f"Unbekannte Paketart „{kind}“.")


# --- Höchststufe beim Empfänger (Härtung H4, V5) ---


def _require_accepted(coupling: Coupling, key: str) -> None:
    """Vorgänge außerhalb der Pakete (Rundschreiben, Rechnungen): nur mit Zustimmung."""
    packet = packets.REGISTRY.get(key)
    if (
        packet is None
        or packet not in packets.receivable(coupling)
        or rank(packet, accepted(coupling).get(key)) < 0
    ):
        label = packet.label if packet else key
        raise Refused(422, f"„{label}“ wird hier nicht angenommen.")


def rank(packet, level) -> int:
    """Rang einer Stufe: -1 aus, 0 kleinste, … (unbekannt: höchster Rang)."""
    if not level:
        return -1
    values = [v for v, _ in packet.levels]
    return values.index(level) if level in values else len(values)


def accepted(coupling: Coupling) -> dict:
    """Stufen, denen diese Seite zugestimmt hat. Ältere Kopplungen: der bisherige Stand."""
    options = coupling.options or {}
    if "accept" not in options:
        options = {**options, "accept": dict(coupling.remote_packets or {})}
        coupling.options = options
        Coupling.objects.filter(pk=coupling.pk).update(options=options)
    return options["accept"]


def _offer(coupling: Coupling, offered: dict, *, first: bool = False) -> None:
    """Gegenseite meldet ihre Freigaben: was über der Zustimmung liegt, wartet auf den Vorstand."""
    options = dict(coupling.options or {})
    if first:
        options["accept"] = dict(offered)
        options.pop("wants_more", None)
    else:
        allowed = options.get("accept") or {}
        wants = {
            key: level
            for key, level in offered.items()
            if (p := packets.REGISTRY.get(key)) and rank(p, level) > rank(p, allowed.get(key))
        }
        before = options.get("wants_more") or {}
        if wants:
            options["wants_more"] = wants
        else:
            options.pop("wants_more", None)
        if wants and wants != before:
            pk = coupling.pk
            transaction.on_commit(lambda: _notify_more(pk))
    coupling.options = options
    Coupling.objects.filter(pk=coupling.pk).update(options=options)


def wants_more(coupling: Coupling) -> list[dict]:
    result = []
    for key, level in ((coupling.options or {}).get("wants_more") or {}).items():
        packet = packets.REGISTRY.get(key)
        if packet is None:
            continue
        labels = dict(packet.levels)
        current = accepted(coupling).get(key)
        result.append(
            {
                "key": key,
                "label": packet.label,
                "level": level,
                "level_label": labels.get(level, level),
                "accepted": current,
                "accepted_label": labels.get(current, "aus") if current else "aus",
                "personal": packet.personal,
            }
        )
    return result


def set_accept(coupling: Coupling, levels: dict, user) -> Coupling:
    """Höchststufen je Paket, die diese Seite von der Gegenseite annimmt."""
    with transaction.atomic():
        coupling = Coupling.objects.select_for_update().get(pk=coupling.pk)
        allowed = _clean_remote(coupling, levels)
        options = dict(coupling.options or {})
        options["accept"] = allowed
        wants = {
            key: level
            for key, level in (options.get("wants_more") or {}).items()
            if (p := packets.REGISTRY.get(key)) and rank(p, level) > rank(p, allowed.get(key))
        }
        if wants:
            options["wants_more"] = wants
        else:
            options.pop("wants_more", None)
        coupling.options = options
        coupling.save(update_fields=["options"])
        _audit(coupling, user, "Höchststufen für empfangene Pakete geändert")
    return coupling


def decide_more(coupling: Coupling, key: str, accept: bool, user) -> Coupling:
    """Vorstand stimmt einer höheren Stufe der Gegenseite zu oder lehnt ab."""
    with transaction.atomic():
        coupling = Coupling.objects.select_for_update().get(pk=coupling.pk)
        options = dict(coupling.options or {})
        wants = dict(options.get("wants_more") or {})
        if key not in wants:
            raise ValidationError(gettext("Dazu liegt keine Anfrage vor."))
        level = wants.pop(key)
        if accept:
            options["accept"] = {**(options.get("accept") or {}), key: level}
        if wants:
            options["wants_more"] = wants
        else:
            options.pop("wants_more", None)
        coupling.options = options
        coupling.save(update_fields=["options"])
        label = packets.REGISTRY[key].label if key in packets.REGISTRY else key
        _audit(
            coupling,
            user,
            f"Höhere Stufe angenommen: {label}" if accept else f"Höhere Stufe abgelehnt: {label}",
        )
    return coupling


def _notify_more(coupling_id: int) -> None:
    coupling = Coupling.objects.select_related("local_unit", "remote_unit", "peer").get(
        pk=coupling_id
    )

    def lines() -> str:
        return "\n".join(
            "- "
            + gettext("{label}: {level} (bisher {accepted})").format(
                label=w["label"], level=w["level_label"], accepted=w["accepted_label"]
            )
            for w in wants_more(coupling)
        )

    _mail(
        coupling.local_unit,
        gettext_noop("Verbund: {remote} möchte mehr Daten senden"),
        gettext_noop(
            "{remote} ({base}) möchte mehr senden, als ihr beim Koppeln angenommen habt:"
            "\n\n{lines}\n\nBis ihr in HUBIplan unter Verbund zustimmt, nimmt diese Instanz "
            "nur die bisherige Stufe an."
        ),
        remote=coupling.remote_unit.name,
        base=coupling.peer.base_url,
        lines=lines,
    )


def status_for(peer: Peer, payload: dict) -> dict:
    coupling = find_coupling(peer, payload)
    return {"state": coupling.state, "received": coupling.received_hashes or {}}


# --- Hinweise und Protokoll ---


def _audit(coupling: Coupling, user, text: str, **changes) -> None:
    from audit.log import record

    data = {"Kopplung": [None, text], "andere Instanz": [None, coupling.peer.base_url]}
    for key, value in changes.items():
        data[key] = [None, value]
    record(coupling.local_unit, user, "update", coupling.local_unit, data)


def _audit_unit(unit, user, text: str) -> None:
    from audit.log import record

    record(unit, user, "update", unit, {"Verbund": [None, text]})


def _managers(unit) -> list:
    from access.models import RoleAssignment

    from .permissions import PEERING_MANAGE

    users = {}
    for a in (
        RoleAssignment.objects.active().filter(organization=unit).select_related("role", "user")
    ):
        if a.user_id and PEERING_MANAGE in (a.role.permissions or []):
            users[a.user_id] = a.user
    return list(users.values())


def _mail(unit, subject: str, text: str, /, **params) -> None:
    """Hinweis an alle mit Verbund-Verwaltung, je in ihrer Nutzersprache.

    ``subject`` und ``text`` sind die deutschen Schlüssel (``gettext_noop``); Werte in
    ``params`` dürfen Funktionen sein, die erst in der Sprache der Empfänger rechnen.
    """
    from django.core.mail import send_mail
    from django.utils import translation

    from core.i18n import user_language
    from core.tenancy import rls_bypass

    # Hinweis-Mails laufen oft nach dem Ende der Anfrage (on_commit): Empfänger ohne RLS suchen
    with rls_bypass():
        managers = _managers(unit)
    by_language: dict[str, list[str]] = {}
    for user in managers:
        by_language.setdefault(user_language(user), []).append(user.email)
    for language, emails in by_language.items():
        with translation.override(language):
            values = {k: v() if callable(v) else v for k, v in params.items()}
            send_mail(
                gettext(subject).format(**values),
                gettext(text).format(**values),
                None,
                sorted(emails),
            )


def _notify_pending(coupling_id: int) -> None:
    coupling = Coupling.objects.select_related("local_unit", "remote_unit", "peer").get(
        pk=coupling_id
    )
    _mail(
        coupling.local_unit,
        gettext_noop("Kopplungsanfrage: {remote}"),
        gettext_noop(
            "{remote} ({base}) möchte sich unter {local} koppeln.\n\nBitte in HUBIplan unter "
            "Einstellungen › Verbund prüfen und bestätigen oder ablehnen."
        ),
        remote=coupling.remote_unit.name,
        base=coupling.peer.base_url,
        local=coupling.local_unit.name,
    )


def _notify_move(coupling_id: int) -> None:
    coupling = Coupling.objects.select_related("local_unit", "remote_unit", "peer").get(
        pk=coupling_id
    )
    move = (coupling.options or {}).get("move") or {}
    _mail(
        coupling.local_unit,
        gettext_noop("Umzug angekündigt: {remote}"),
        gettext_noop(
            "{remote} meldet einen Umzug von {old} nach {new}.\n\nBis zur Bestätigung ruht "
            "die Kopplung, es gehen keine Daten hinaus. Bitte in HUBIplan unter Verbund den "
            "Fingerabdruck der neuen Instanz mit dem vergleichen, den euch die andere Seite "
            "auf anderem Weg (Telefon, Mail) mitteilt, und erst dann bestätigen. Wenn ihr "
            "nichts von einem Umzug wisst: ablehnen."
        ),
        remote=coupling.remote_unit.name,
        old=move.get("from", ""),
        new=move.get("base_url", ""),
    )


def _notify_circular(coupling: Coupling, circular) -> None:
    unit = coupling.local_unit
    transaction.on_commit(
        lambda: _mail(
            unit,
            gettext_noop("Rundschreiben von {remote} zur Weitergabe"),
            gettext_noop(
                "{remote} bittet, das Rundschreiben „{subject}“ an die Mitglieder von {local} "
                "weiterzugeben. Es liegt als Entwurf unter Rundschreiben bereit: bitte prüfen, "
                "Empfänger wählen und versenden."
            ),
            remote=coupling.remote_unit.name,
            subject=circular.subject,
            local=unit.name,
        )
    )


def warn_stuck() -> None:
    limit = timezone.now() - WARN_AFTER
    for coupling in Coupling.objects.filter(
        error_since__lte=limit, warned_at__isnull=True
    ).select_related("local_unit", "remote_unit", "peer"):
        _mail(
            coupling.local_unit,
            gettext_noop("Verbund: {remote} seit einem Tag nicht erreichbar"),
            gettext_noop(
                "Pakete an {remote} ({base}) warten seit {since}. Letzter Fehler: {error}\n\n"
                "Die Arbeit hier geht normal weiter; die Pakete werden automatisch "
                "nachgeschickt."
            ),
            remote=coupling.remote_unit.name,
            base=coupling.peer.base_url,
            since=lambda c=coupling: datetime_text(timezone.localtime(c.error_since)),
            error=coupling.last_error,
        )
        Coupling.objects.filter(pk=coupling.pk).update(warned_at=timezone.now())
