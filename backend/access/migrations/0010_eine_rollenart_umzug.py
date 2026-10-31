"""Eine Rollenart: Rollen der Untereinheiten ziehen in die Rollentabelle.

Bisher standen Rollen von Untereinheiten (z. B. Zugführer) in
``organizations.DepartmentRole`` und ihre Inhaber in ``members.DepartmentRoleHolder``.
Jetzt stehen alle Rollen in ``access.Role`` (mit ``department``) und alle Inhaber in
``access.RoleAssignment`` (mit ``membership``). Die Daten werden hier umkopiert; dabei
ändern sich die Nummern. Verweise darauf (Empfängerauswahl von Rundschreiben,
Rückgängig-Einträge) werden mit umgestellt.
"""

from django.db import migrations


def _remap_values(values, ids, keys):
    if not values:
        return values
    values = dict(values)
    for key in keys:
        if values.get(key) in ids:
            values[key] = ids[values[key]]
    return values


def copy_roles(apps, schema_editor):
    from core.tenancy import rls_bypass

    OldRole = apps.get_model("organizations", "DepartmentRole")
    OldHolder = apps.get_model("members", "DepartmentRoleHolder")
    Role = apps.get_model("access", "Role")
    RoleAssignment = apps.get_model("access", "RoleAssignment")
    Circular = apps.get_model("circulars", "Circular")
    ChangeRecord = apps.get_model("changes", "ChangeRecord")
    ChangeSet = apps.get_model("changes", "ChangeSet")

    with rls_bypass():
        role_ids: dict[int, int] = {}
        for old in OldRole.objects.order_by("pk"):
            new = Role.objects.create(
                organization_id=old.organization_id,
                department_id=old.department_id,
                name=old.name,
                permissions=old.permissions,
                position=old.position,
                on_letterhead=old.on_letterhead,
                contact_email=old.contact_email,
                on_website=old.on_website,
                is_board=False,
            )
            role_ids[old.pk] = new.pk
        holder_ids: dict[int, int] = {}
        for old in OldHolder.objects.order_by("pk"):
            new = RoleAssignment.objects.create(
                organization_id=old.organization_id,
                role_id=role_ids[old.role_id],
                membership_id=old.membership_id,
                valid_from=old.valid_from,
                valid_until=old.valid_until,
            )
            holder_ids[old.pk] = new.pk

        # Rundschreiben: gewählte Rollen
        for circular in Circular.objects.exclude(filters={}):
            roles = (circular.filters or {}).get("roles")
            if not roles:
                continue
            mapped = [role_ids.get(int(r), r) if str(r).isdigit() else r for r in roles]
            circular.filters = {**circular.filters, "roles": mapped}
            circular.save(update_fields=["filters"])

        # Rückgängig: Einträge auf die neuen Tabellen und Nummern umstellen
        moves = {
            "organizations.departmentrole": ("access.role", role_ids, {"id": role_ids}),
            "members.departmentroleholder": (
                "access.roleassignment",
                holder_ids,
                {"id": holder_ids, "role_id": role_ids},
            ),
        }
        for label, (target, ids, keys) in moves.items():
            for rec in ChangeRecord.objects.filter(model=label):
                rec.model = target
                if rec.object_id.isdigit() and int(rec.object_id) in ids:
                    rec.object_id = str(ids[int(rec.object_id)])
                else:
                    # Schon gelöscht: alte Nummer passt nicht mehr in die neue Tabelle
                    ChangeSet.objects.filter(pk=rec.change_set_id, blocked_reason="").update(
                        blocked_reason="Betrifft Rollen von vor der Umstellung der Rollen."
                    )
                for side in ("before", "after"):
                    values = getattr(rec, side)
                    for key, mapping in keys.items():
                        values = _remap_values(values, mapping, [key])
                    setattr(rec, side, values)
                rec.save(update_fields=["model", "object_id", "before", "after"])


class Migration(migrations.Migration):
    dependencies = [
        ("access", "0009_eine_rollenart"),
        ("circulars", "0002_empfaengerkreis_abteilungen"),
        ("changes", "0004_anfrageschluessel_pruefsumme"),
    ]

    operations = [migrations.RunPython(copy_roles, migrations.RunPython.noop)]
