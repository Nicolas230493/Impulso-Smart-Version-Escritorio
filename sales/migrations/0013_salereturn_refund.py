# SPEC-FIN-07: medio y monto reintegrado en devoluciones (arqueo de caja unificado web/escritorio).

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0005_paymentmethod'),
        ('sales', '0012_salepayment_decimal_returns'),
    ]

    operations = [
        migrations.AddField(
            model_name='salereturn',
            name='refund_amount',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='Monto Reintegrado'),
        ),
        migrations.AddField(
            model_name='salereturn',
            name='refund_method',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='finance.paymentmethod', verbose_name='Medio de Reintegro'),
        ),
    ]
