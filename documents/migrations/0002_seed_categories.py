from django.db import migrations


def seed_categories(apps, schema_editor):
    Category = apps.get_model("documents", "Category")
    defaults = [
        ("Meals & Entertainment", "Food, coffee, client meals"),
        ("Software / Subscriptions", "SaaS, cloud, licenses"),
        ("Hardware / Maintenance", "Tools, repairs, facilities"),
        ("Travel & Transport", "Flights, rideshare, mileage"),
        ("Fuel & Auto", "Gas, parking, vehicle"),
        ("Office / Supplies", "General office spend"),
    ]
    for name, desc in defaults:
        Category.objects.get_or_create(
            name=name,
            defaults={"description": desc, "is_system_generated": False},
        )


def unseed(apps, schema_editor):
    Category = apps.get_model("documents", "Category")
    Category.objects.filter(is_system_generated=False).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_categories, unseed),
    ]
