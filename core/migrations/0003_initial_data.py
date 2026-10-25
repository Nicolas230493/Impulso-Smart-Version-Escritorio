# SPEC-BOOT-01: medios de pago base y Consumidor Final en toda instalación (idempotente).

from django.db import migrations


def seed(apps, schema_editor):
    from core.bootstrap import ensure_initial_data
    ensure_initial_data(apps)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_alter_activitylog_options_activitylog_ip_address'),
        ('finance', '0005_paymentmethod'),
        ('customers', '0010_customer_limite_credito'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
