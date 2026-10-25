# SPEC-FIN-06: valorizar mermas con el costo vigente al momento de la baja.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0018_decimal_min_stock_purchases_losses'),
    ]

    operations = [
        migrations.AddField(
            model_name='stockloss',
            name='unit_cost',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, verbose_name='Costo unitario al dar de baja'),
        ),
    ]
