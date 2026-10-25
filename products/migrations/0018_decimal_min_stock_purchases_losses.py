# SPEC-DATA-02: min_stock y cantidades de compras, órdenes de compra y bajas a DECIMAL(10,3).

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0017_weighable_decimal_quantities'),
    ]

    operations = [
        migrations.AlterField(
            model_name='product',
            name='min_stock',
            field=models.DecimalField(decimal_places=3, default=5, max_digits=10, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Stock Mínimo'),
        ),
        migrations.AlterField(
            model_name='purchasedetail',
            name='quantity',
            field=models.DecimalField(decimal_places=3, max_digits=10, verbose_name='Cantidad'),
        ),
        migrations.AlterField(
            model_name='purchaseorderdetail',
            name='quantity',
            field=models.DecimalField(decimal_places=3, max_digits=10, verbose_name='Cantidad'),
        ),
        migrations.AlterField(
            model_name='stockloss',
            name='quantity',
            field=models.DecimalField(decimal_places=3, max_digits=10, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Cantidad'),
        ),
    ]
