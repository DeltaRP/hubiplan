"""Gesamtaudit 25.10.2026, Paket 4: 2FA-Geheimnisse (I-S02) und Löschfrist (A-S03).

Die Backup-Prüfsumme (I-S01) prüft scripts/test.sh mit BACKUP_TEST=1."""

import datetime
import importlib
import io

import pytest
from allauth.mfa.models import Authenticator
from allauth.mfa.recovery_codes.internal.auth import RecoveryCodes
from allauth.mfa.totp.internal.auth import TOTP
from cryptography.fernet import Fernet
from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.utils import timezone

from accounts import mfa
from core.tenancy import rls_bypass
from customfields.models import FieldDefinition, FieldValue
from members.models import MembershipPeriod
from members.workflows import purge_expired
from portal.models import ChangeRequest, LoginLink, PortalAccess, hash_token

from .factories import make_member, make_user
from .test_auth import totp_code

pytestmark = pytest.mark.django_db
SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


def stored(user, kind):
    return Authenticator.objects.get(user=user, type=kind).data


def test_totp_geheimnis_liegt_verschluesselt(user):
    TOTP.activate(user, SECRET)
    data = stored(user, Authenticator.Type.TOTP)
    assert data["secret"].startswith("enc1:")
    assert SECRET not in str(data)
    instance = Authenticator.objects.get(user=user, type=Authenticator.Type.TOTP)
    assert TOTP(instance).validate_code(totp_code(SECRET))


def test_wiederherstellungscodes_verschluesselt_und_nutzbar(user):
    codes = RecoveryCodes.activate(user)
    seed = stored(user, Authenticator.Type.RECOVERY_CODES)["seed"]
    assert seed.startswith("enc1:")
    first = codes.generate_codes()[0]
    assert RecoveryCodes(codes.instance).validate_code(first)


def test_klartext_und_falscher_schluessel_werden_abgewiesen(user, settings):
    Authenticator.objects.create(user=user, type="totp", data={"secret": SECRET})
    instance = Authenticator.objects.get(user=user, type="totp")
    with pytest.raises(ImproperlyConfigured):
        TOTP(instance).validate_code(totp_code(SECRET))
    instance.data = {"secret": mfa.encrypt(SECRET)}
    instance.save()
    settings.MFA_ENCRYPTION_KEYS = [Fernet.generate_key().decode()]
    with pytest.raises(ImproperlyConfigured):
        TOTP(instance).validate_code(totp_code(SECRET))


def test_ohne_schluessel_im_betrieb_kein_start():
    with pytest.raises(ImproperlyConfigured):
        mfa._fernet(())
    with pytest.raises(ImproperlyConfigured):
        mfa._fernet(("kein-schluessel",))


def test_migration_verschluesselt_vorhandene_eintraege(user):
    Authenticator.objects.create(user=user, type="totp", data={"secret": SECRET})
    other = make_user("zweiter@example.org")
    Authenticator.objects.create(
        user=other,
        type="recovery_codes",
        data={"seed": "abcdef", "used_mask": 0, "migrated_codes": ["11111111", "22222222"]},
    )
    migration = importlib.import_module("accounts.migrations.0003_mfa_geheimnisse_verschluesseln")
    migration.encrypt_all(apps, None)
    migration.encrypt_all(apps, None)  # zweimal schadet nicht
    totp = stored(user, "totp")
    codes = stored(other, "recovery_codes")
    assert mfa.decrypt(totp["secret"]) == SECRET
    assert mfa.decrypt(codes["seed"]) == "abcdef"
    assert [mfa.decrypt(c) for c in codes["migrated_codes"]] == ["11111111", "22222222"]
    assert codes["used_mask"] == 0
    assert "abcdef" not in str(codes) and SECRET not in str(totp)


def test_schluesselwechsel(user, settings):
    old = Fernet.generate_key().decode()
    new = Fernet.generate_key().decode()
    settings.MFA_ENCRYPTION_KEYS = [old]
    TOTP.activate(user, SECRET)
    settings.MFA_ENCRYPTION_KEYS = [new, old]
    call_command("mfa_schluessel_wechseln", stdout=io.StringIO())
    settings.MFA_ENCRYPTION_KEYS = [new]
    assert mfa.decrypt(stored(user, "totp")["secret"]) == SECRET


def test_loeschfrist_entfernt_zusatzfelder_meldungen_und_zugang(orgs):
    club = orgs["a"]
    membership = make_member(club, "Erika", "Muster")
    person = membership.person
    login_user = make_user("erika-portal@example.org")
    with rls_bypass():
        own = FieldDefinition.objects.create(organization=club, label="Schuhgröße", key="schuh")
        fed = FieldDefinition.objects.create(
            organization=orgs["federation"], label="Ehrennadel", key="nadel"
        )
        FieldValue.objects.create(organization=club, definition=own, person=person, value="42")
        FieldValue.objects.create(
            organization=orgs["federation"], definition=fed, person=person, value="Gold"
        )
        ChangeRequest.objects.create(
            organization=club,
            membership=membership,
            data={"street": "Neue Straße 5"},
            previous={"street": "Lindenweg 4"},
            message="Bin umgezogen",
        )
        PortalAccess.objects.create(organization=club, membership=membership, user=login_user)
        link = LoginLink.objects.create(
            user=login_user,
            organization=club,
            token_hash=hash_token("probe"),
            expires_at=timezone.now() + datetime.timedelta(days=1),
        )
        MembershipPeriod.objects.filter(membership=membership).update(
            exit_date=datetime.date(2020, 12, 31)
        )
    assert purge_expired(datetime.date(2023, 1, 1)) == 1
    with rls_bypass():
        assert list(FieldValue.objects.filter(person=person).values_list("value", flat=True)) == [
            "Gold"
        ]  # Feld des Dachverbands gehört nicht dem Verein
        request = ChangeRequest.objects.get(membership=membership)
        assert (request.data, request.previous, request.message) == ({}, {}, "")
        assert request.status == ChangeRequest.Status.REJECTED
        assert not PortalAccess.objects.filter(membership=membership).exists()
        link.refresh_from_db()
        assert link.used_at is not None
