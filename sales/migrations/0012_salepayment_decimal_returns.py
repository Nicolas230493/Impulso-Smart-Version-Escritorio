# SPEC-DATA-02 / SPEC-POS-08: devoluciones decimales + pagos por venta (cobro mixto).
# Las ventas históricas se completan con un SalePayment por su método y total.

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


def backfill_sale_payments(apps, schema_editor):
    Sale = apps.get_model('sales', 'Sale')
    SalePayment = apps.get_model('sales', 'SalePayment')
    SalePayment.objects.bulk_create(
        SalePayment(sale_id=s.id, payment_method_id=s.payment_method_id, amount=s.total_amount)
        for s in Sale.objects.filter(payment_method__isnull=False).only('id', 'payment_method_id', 'total_amount')
    )


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0005_paymentmethod'),
        ('sales', '0011_alter_saledetail_quantity_decimal'),
    ]

    operations = [
        migrations.AlterField(
            model_name='salereturndetail',
            name='quantity',
            field=models.DecimalField(decimal_places=3, max_digits=10, verbose_name='Cantidad Devuelta'),
        ),
        migrations.CreateModel(
            name='SalePayment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Monto')),
                ('payment_method', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='finance.paymentmethod', verbose_name='Método de Pago')),
                ('sale', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payments', to='sales.sale')),
            ],
            options={
                'verbose_name': 'Pago de Venta',
                'verbose_name_plural': 'Pagos de Venta',
            },
        ),
        migrations.RunPython(backfill_sale_payments, migrations.RunPython.noop),
    ]
