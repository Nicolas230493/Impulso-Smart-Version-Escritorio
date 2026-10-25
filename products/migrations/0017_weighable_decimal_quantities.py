# SPEC-DATA-01: cantidades pesables (DECIMAL 10,3) y flag is_weighable.
# En SQLite, Django reconstruye la tabla copiando los datos dentro de una transacción.

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0016_product_unit'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='is_weighable',
            field=models.BooleanField(default=False, help_text='Se vende por peso fraccional (ej. 0.500 kg)', verbose_name='Pesable'),
        ),
        migrations.AlterField(
            model_name='product',
            name='stock',
            field=models.DecimalField(decimal_places=3, default=0, max_digits=10, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Stock'),
        ),
        migrations.AlterField(
            model_name='inventorymovement',
            name='quantity',
            field=models.DecimalField(decimal_places=3, max_digits=10, verbose_name='Cantidad'),
        ),
    ]
