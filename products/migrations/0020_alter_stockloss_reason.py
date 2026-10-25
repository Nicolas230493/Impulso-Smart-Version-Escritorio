# SPEC-UI-04: motivo "Descarte / Merma" (MER) para bajas desde el escritorio. Solo cambian las opciones.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0019_stockloss_unit_cost'),
    ]

    operations = [
        migrations.AlterField(
            model_name='stockloss',
            name='reason',
            field=models.CharField(choices=[('EXP', 'Vencimiento'), ('MER', 'Descarte / Merma'), ('DAM', 'Rotura'), ('INT', 'Consumo Interno'), ('OTH', 'Otros')], max_length=3, verbose_name='Motivo'),
        ),
    ]
