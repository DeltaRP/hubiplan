import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("circulars", "0004_app_kurzmitteilung"),
        ("organizations", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MailingList",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, verbose_name="Name")),
                ("local_part", models.CharField(max_length=64, unique=True, verbose_name="Adresse")),
                (
                    "mode",
                    models.CharField(
                        choices=[
                            ("confirm", "Absender bestätigt per Link"),
                            ("draft", "als Entwurf in HUBIplan ablegen"),
                        ],
                        default="confirm",
                        max_length=10,
                        verbose_name="Versand",
                    ),
                ),
                ("is_active", models.BooleanField(default=True, verbose_name="aktiv")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "department",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="organizations.department",
                        verbose_name="Abteilung",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="organizations.organization",
                    ),
                ),
                (
                    "pattern",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="list_pattern",
                        to="circulars.circular",
                    ),
                ),
            ],
            options={
                "verbose_name": "Verteiler",
                "verbose_name_plural": "Verteiler",
                "ordering": ["name", "pk"],
            },
        ),
        migrations.CreateModel(
            name="InboundMail",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("message_id", models.CharField(blank=True, db_index=True, max_length=300)),
                ("sender", models.CharField(blank=True, max_length=300, verbose_name="Absender")),
                ("recipient", models.CharField(blank=True, max_length=300, verbose_name="an")),
                ("subject", models.CharField(blank=True, max_length=300, verbose_name="Betreff")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("rejected", "abgewiesen"),
                            ("waiting", "wartet auf Bestätigung"),
                            ("draft", "als Entwurf abgelegt"),
                            ("sent", "versendet"),
                            ("failed", "Fehler"),
                        ],
                        max_length=10,
                    ),
                ),
                ("reason", models.CharField(blank=True, max_length=300, verbose_name="Grund")),
                ("received_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "circular",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="circulars.circular",
                    ),
                ),
                (
                    "mailing_list",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="inbound",
                        to="circulars.mailinglist",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="organizations.organization",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Eingang eines Verteilers",
                "verbose_name_plural": "Eingänge der Verteiler",
                "ordering": ["-received_at", "-pk"],
            },
        ),
    ]
