"""Abteilungen werden Einheiten in der Organisationstabelle.

Jede bisherige Abteilung wird eine ``Organization`` der Art ``unit`` mit
``parent`` und ``organization`` = ihr Verein. Alle Verweise auf Abteilungen
(Fremdschlüssel in allen Apps, Wechselanfragen, Protokoll) werden auf die neuen
IDs umgeschrieben. Die alte Tabelle entfällt, ``Department`` bleibt als
Proxy-Modell. Jede Einheit bekommt außerdem eine eigene Bezeichnung.

Der Rückgängig-Verlauf (Änderungspakete) wird geleert: Seine Rohwerte gehören
zur alten Struktur und ließen sich nicht mehr sicher zurückspielen.
"""

import django.db.models.deletion
from django.db import migrations, models

LABELS = {
    "platform": ("Plattform", "Plattformen", "f", ""),
    "federation": ("Dachverband", "Dachverbände", "m", "Dachverbands"),
    "club": ("Verein", "Vereine", "m", "Vereins"),
}

DEPARTMENT_FIELDS = (
    "name",
    "short_name",
    "founding_year",
    "sort_order",
    "date_precision",
    "is_active",
    "fiscal_start_month",
    "fiscal_start_day",
    "primary_color",
    "accent_color",
)


def copy_departments(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    Department = apps.get_model("organizations", "Department")
    AuditEntry = apps.get_model("audit", "AuditEntry")
    TransferRequest = apps.get_model("members", "TransferRequest")
    ChangeSet = apps.get_model("changes", "ChangeSet")
    ChangeRecord = apps.get_model("changes", "ChangeRecord")
    db = schema_editor.connection.alias

    for org_type, (label, plural, gender, genitive) in LABELS.items():
        Organization.objects.using(db).filter(type=org_type).update(
            label=label, label_plural=plural, label_gender=gender, label_genitive=genitive
        )

    mapping: dict[int, int] = {}
    for dept in Department.objects.using(db).select_related("organization").order_by("pk"):
        club = dept.organization
        unit = Organization(
            type="unit",
            parent_id=club.pk,
            organization_id=club.pk,
            label=club.department_label,
            label_plural=club.department_label_plural,
            label_gender=club.department_label_gender,
            label_genitive=club.department_label_genitive,
            country="",
            logo=dept.logo.name if dept.logo else "",
            **{f: getattr(dept, f) for f in DEPARTMENT_FIELDS},
        )
        unit.save(using=db)
        Organization.objects.using(db).filter(pk=unit.pk).update(
            created_at=dept.created_at, updated_at=dept.updated_at
        )
        mapping[dept.pk] = unit.pk

    with schema_editor.connection.cursor() as cursor:
        for old, new in mapping.items():
            cursor.execute(
                "UPDATE organizations_organization SET legacy_department_id = %s WHERE id = %s",
                [old, new],
            )

    for entry in AuditEntry.objects.using(db).filter(object_type="Abteilung"):
        new = mapping.get(int(entry.object_id)) if entry.object_id.isdigit() else None
        if new:
            entry.object_id = str(new)
            entry.save(update_fields=["object_id"])

    for req in TransferRequest.objects.using(db).exclude(admission={}):
        ids = req.admission.get("department_ids") if isinstance(req.admission, dict) else None
        if ids:
            req.admission = {
                **req.admission,
                "department_ids": [mapping[i] for i in ids if i in mapping],
            }
            req.save(update_fields=["admission"])

    remap_json_references(apps, db, mapping)

    ChangeRecord.objects.using(db).all().delete()
    ChangeSet.objects.using(db).all().delete()


def _new_id(value, mapping):
    """Alte Abteilungsnummer (Zahl oder Ziffernfolge) auf die neue Einheit; sonst None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return mapping.get(value)
    if isinstance(value, str) and value.isdigit():
        new = mapping.get(int(value))
        return str(new) if new else None
    return None


def remap_json_references(apps, db, mapping):
    """Abteilungsnummern in JSON-Feldern umschreiben (die Fremdschlüssel macht SQL unten).

    - Rundschreiben: Empfängerauswahl ``departments``
    - Exportvorlagen und Exporte: Filter ``abteilung``
    - Importvorlagen und Importe: Wertzuordnung ``departments`` (Dateiwert -> Abteilung)
    Nicht mehr vorhandene Abteilungen fallen aus Listen heraus.
    """
    Circular = apps.get_model("circulars", "Circular")
    for circular in Circular.objects.using(db).exclude(filters={}):
        ids = circular.filters.get("departments") if isinstance(circular.filters, dict) else None
        if isinstance(ids, list) and ids:
            new = [n for n in (_new_id(i, mapping) for i in ids) if n]
            circular.filters = {**circular.filters, "departments": new}
            circular.save(update_fields=["filters"])

    for name in ("ExportTemplate", "ExportJob"):
        model = apps.get_model("exchange", name)
        for obj in model.objects.using(db).exclude(filters={}):
            if not isinstance(obj.filters, dict) or obj.filters.get("abteilung") in (None, ""):
                continue
            filters = dict(obj.filters)
            new = _new_id(filters["abteilung"], mapping)
            if new:
                filters["abteilung"] = new
            else:
                filters.pop("abteilung")
            obj.filters = filters
            obj.save(update_fields=["filters"])

    for name in ("ImportTemplate", "ImportJob"):
        model = apps.get_model("exchange", name)
        for obj in model.objects.using(db).exclude(value_mapping={}):
            vm = obj.value_mapping if isinstance(obj.value_mapping, dict) else {}
            departments = vm.get("departments")
            if not isinstance(departments, dict) or not departments:
                continue
            remapped = {}
            for raw, target in departments.items():
                new = _new_id(target, mapping)
                if new:
                    remapped[raw] = new
            obj.value_mapping = {**vm, "departments": remapped}
            obj.save(update_fields=["value_mapping"])


# Alle Fremdschlüssel auf die alte Abteilungstabelle auf die Organisationstabelle
# umhängen. Erst negativ setzen, damit eindeutige Spalten beim Umschreiben nicht
# kurzzeitig doppelt belegt sind.
REMAP_FOREIGN_KEYS = """
SET CONSTRAINTS ALL IMMEDIATE;
DO $$
DECLARE r record;
BEGIN
    FOR r IN
        SELECT c.conname, c.conrelid::regclass::text AS tbl, a.attname AS col
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
        WHERE c.contype = 'f' AND c.confrelid = 'organizations_department'::regclass
    LOOP
        EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', r.tbl, r.conname);
        EXECUTE format('UPDATE %s SET %I = -%I WHERE %I IS NOT NULL', r.tbl, r.col, r.col, r.col);
        EXECUTE format(
            'UPDATE %s t SET %I = o.id FROM organizations_organization o '
            'WHERE t.%I < 0 AND o.legacy_department_id = -t.%I',
            r.tbl, r.col, r.col, r.col
        );
        EXECUTE format(
            'ALTER TABLE %s ADD CONSTRAINT %I FOREIGN KEY (%I) '
            'REFERENCES organizations_organization (id) DEFERRABLE INITIALLY DEFERRED',
            r.tbl, left(r.tbl || '_' || r.col || '_einheit_fk', 63), r.col
        );
    END LOOP;
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0013_dachverband_name_grammatik"),
        ("audit", "0004_auditentry_change_set"),
        ("billing", "0005_veranstaltungen"),
        ("changes", "0002_rls"),
        ("circulars", "0002_empfaengerkreis_abteilungen"),
        ("core", "0019_rls_ehrentitel"),
        ("datatransfer", "0001_initial"),
        ("exchange", "0002_private_storage_callable"),
        ("documents", "0004_rls_nach_oben"),
        ("events", "0003_veranstaltungen"),
        ("finance", "0005_veranstaltungen"),
        ("members", "0008_ehrentitel"),
        ("statutes", "0002_rls"),
    ]

    operations = [
        migrations.AlterField(
            model_name="organization",
            name="type",
            field=models.CharField(
                choices=[
                    ("platform", "Plattform"),
                    ("federation", "Dachverband"),
                    ("club", "Verein"),
                    ("unit", "Untereinheit"),
                ],
                max_length=20,
                verbose_name="Art",
            ),
        ),
        migrations.AddField(
            model_name="organization",
            name="organization",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="departments",
                to="organizations.organization",
                verbose_name="Datenbereich",
            ),
        ),
        migrations.AddField(
            model_name="organization",
            name="sort_order",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="Reihenfolge"),
        ),
        migrations.AddField(
            model_name="organization",
            name="label",
            field=models.CharField(blank=True, max_length=50, verbose_name="Bezeichnung (Einzahl)"),
        ),
        migrations.AddField(
            model_name="organization",
            name="label_plural",
            field=models.CharField(
                blank=True, max_length=50, verbose_name="Bezeichnung (Mehrzahl)"
            ),
        ),
        migrations.AddField(
            model_name="organization",
            name="label_gender",
            field=models.CharField(
                choices=[("f", "die (weiblich)"), ("m", "der (männlich)"), ("n", "das (sächlich)")],
                default="m",
                max_length=1,
                verbose_name="Bezeichnung (Genus)",
            ),
        ),
        migrations.AddField(
            model_name="organization",
            name="label_genitive",
            field=models.CharField(
                blank=True, max_length=50, verbose_name="Bezeichnung (Genitiv, falls abweichend)"
            ),
        ),
        migrations.AlterField(
            model_name="organization",
            name="date_precision",
            field=models.CharField(
                blank=True,
                choices=[("day", "tagesgenau"), ("month", "monatsgenau"), ("year", "jahresgenau")],
                default="day",
                help_text="Bei Untereinheiten leer: wie die übergeordnete Einheit.",
                max_length=10,
                verbose_name="Genauigkeit für Mitgliedschaften und Jubiläen",
            ),
        ),
        migrations.RunSQL(
            "ALTER TABLE organizations_organization ADD COLUMN legacy_department_id bigint",
            migrations.RunSQL.noop,
        ),
        migrations.RunPython(copy_departments),
        migrations.RunSQL(REMAP_FOREIGN_KEYS),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL("DROP TABLE organizations_department"),
                migrations.RunSQL(
                    "ALTER TABLE organizations_organization DROP COLUMN legacy_department_id"
                ),
            ],
            state_operations=[
                migrations.DeleteModel(name="Department"),
                migrations.CreateModel(
                    name="Department",
                    fields=[],
                    options={
                        "verbose_name": "Abteilung",
                        "verbose_name_plural": "Abteilungen",
                        "ordering": ["sort_order", "name"],
                        "proxy": True,
                        "indexes": [],
                        "constraints": [],
                    },
                    bases=("organizations.organization",),
                ),
            ],
        ),
        # Eindeutiger Name je übergeordneter Einheit. Als Index ohne Modell-Constraint,
        # weil DRF sonst „parent“ in allen Organisations-Formularen zur Pflicht macht.
        migrations.RunSQL(
            "CREATE UNIQUE INDEX untereinheit_name_je_einheit "
            "ON organizations_organization (parent_id, name) WHERE type = 'unit'",
            "DROP INDEX IF EXISTS untereinheit_name_je_einheit",
        ),
    ]
