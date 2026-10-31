"""„Geschichte“ aufgeteilt in „Chronik“ und „Ämter“ (Ralf 2026-10-31).

Der neue Schalter „Ämter“ übernimmt den bisherigen Stand von „Geschichte“, damit
sich auf bestehenden Webseiten nichts ändert. Die Textseite „geschichte“ heißt
jetzt „Chronik“, sofern sie noch den alten Standardtitel trägt.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from core.tenancy import rls_bypass

    Website = apps.get_model("website", "Website")
    WebsiteText = apps.get_model("website", "WebsiteText")
    with rls_bypass():
        for site in Website.objects.all():
            blocks = dict(site.blocks or {})
            if "offices" not in blocks:
                blocks["offices"] = bool(blocks.get("history", True))
                site.blocks = blocks
                site.save(update_fields=["blocks"])
        texts = WebsiteText.objects.filter(kind="page", slug="geschichte")
        texts.filter(title="Geschichte").update(title="Chronik")
        texts.filter(published_title="Geschichte").update(published_title="Chronik")


def backwards(apps, schema_editor):
    from core.tenancy import rls_bypass

    Website = apps.get_model("website", "Website")
    with rls_bypass():
        for site in Website.objects.all():
            blocks = dict(site.blocks or {})
            if blocks.pop("offices", None) is not None:
                site.blocks = blocks
                site.save(update_fields=["blocks"])


class Migration(migrations.Migration):
    dependencies = [("website", "0019_wuerdentraeger")]

    operations = [migrations.RunPython(forwards, backwards)]
