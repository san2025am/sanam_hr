from django.db import migrations


def set_default_capacity(apps, schema_editor):
    Location = apps.get_model("api_guard", "Location")
    Shift = apps.get_model("api_guard", "Shift")
    try:
        Location.objects.all().update(guard_capacity=5)
    except Exception:
        pass
    try:
        Shift.objects.all().update(guard_capacity=5)
    except Exception:
        pass


class Migration(migrations.Migration):
    dependencies = [
        ("api_guard", "0017_location_guard_capacity_shift_guard_capacity"),
    ]

    operations = [
        migrations.RunPython(set_default_capacity, migrations.RunPython.noop),
    ]

