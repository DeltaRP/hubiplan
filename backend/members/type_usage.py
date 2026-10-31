"""Wo wird eine Mitgliedsart verwendet? Entscheidet über Löschen oder Archivieren.

Geprüft werden alle Verweise in der Datenbank (per Introspektion, damit neue
Module automatisch mitzählen) und gespeicherte Vorlagen, die eine Art über ihre
ID in JSON ablegen (Import-Wertzuordnungen, Export-Filter).
"""

from __future__ import annotations

from dataclasses import dataclass

from core.tenancy import rls_bypass

from .models import MemberType

# Lesbare Texte für bekannte Verweise: (Einzahl, Mehrzahl)
LABELS = {
    "members.membertypeassignment": ("Mitgliedszeitraum", "Mitgliedszeiträumen"),
    "members.transferrequest": ("Wechselanfrage", "Wechselanfragen"),
    "billing.feerate": ("Beitragssatz", "Beitragssätzen"),
    "billing.agerate": ("Altersstufe", "Altersstufen"),
}


@dataclass
class Usage:
    label: str
    count: int

    @property
    def text(self) -> str:
        return f"in {self.count} {self.label} verwendet"


def _db_usages(member_type: MemberType) -> list[Usage]:
    result = []
    # include_hidden: auch Verweise mit related_name="+" (z. B. Mitgliedszeiträume)
    relations = [
        f
        for f in MemberType._meta.get_fields(include_hidden=True)
        if f.auto_created and not f.concrete and (f.one_to_many or f.one_to_one)
    ]
    for rel in relations:
        model = rel.related_model
        count = model._base_manager.filter(**{rel.field.name: member_type}).count()
        if not count:
            continue
        key = model._meta.label_lower
        one, many = LABELS.get(
            key, (str(model._meta.verbose_name), str(model._meta.verbose_name_plural))
        )
        result.append(Usage(one if count == 1 else many, count))
    return result


def _mapped_ids(value_mapping) -> set[str]:
    """IDs aus Import-Wertzuordnungen der Ziele „member_type“ und „member_type_N“."""
    ids: set[str] = set()
    for target, values in (value_mapping or {}).items():
        if (target == "member_type" or target.startswith("member_type_")) and isinstance(
            values, dict
        ):
            ids |= {str(v) for v in values.values()}
    return ids


def _json_usages(member_type: MemberType) -> list[Usage]:
    from exchange.models import ExportTemplate, ImportJob, ImportTemplate

    pk = str(member_type.pk)
    org = member_type.organization_id
    result = []
    templates = sum(
        pk in _mapped_ids(t.value_mapping)
        for t in ImportTemplate.objects.filter(organization_id=org)
    )
    if templates:
        result.append(Usage("Import-Vorlage" if templates == 1 else "Import-Vorlagen", templates))
    jobs = sum(
        pk in _mapped_ids(j.value_mapping) for j in ImportJob.objects.filter(organization_id=org)
    )
    if jobs:
        result.append(Usage("Import" if jobs == 1 else "Importen", jobs))
    exports = sum(
        str((t.filters or {}).get("art", "")) == pk
        for t in ExportTemplate.objects.filter(organization_id=org)
    )
    if exports:
        result.append(Usage("Export-Vorlage" if exports == 1 else "Export-Vorlagen", exports))
    return result


def usages(member_type: MemberType) -> list[Usage]:
    # Ohne RLS zählen: auch Verweise, die die eigene Organisation nicht sieht
    # (z. B. Wechselanfragen), sollen ein Löschen verhindern.
    with rls_bypass():
        return _db_usages(member_type) + _json_usages(member_type)
