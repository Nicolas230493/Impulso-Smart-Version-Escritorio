# SPEC-DATA-01: cantidades pesables (DECIMAL 10,3) en el detalle de venta.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0010_sale_promo_discount_alter_sale_discount_amount'),
    ]

    operations = [
        migrations.AlterField(
            model_name='saledetail',
            name='quantity',
            field=models.DecimalField(decimal_places=3, max_digits=10, verbose_name='Cantidad'),
        ),
    ]
