"""Recalculo de un turno de caja en la web con la fórmula compartida (core.cash)."""
from django.utils import timezone

from core.cash import cash_session_totals
from customers.models import Payment
from sales.models import SalePayment, SaleReturn
from .models import CashExpense

STORED_FIELDS = ('total_sales_cash', 'total_sales_digital', 'total_expenses', 'expected_final_amount')


def recalculate_cash_session(session, save=True):
    """Ventas, cobros de deuda y reintegros del cajero dentro de la ventana del turno + gastos de la caja."""
    window = {'gte': session.start_date, 'lte': session.end_date or timezone.now()}
    sales = SalePayment.objects.filter(sale__user=session.user, sale__date__gte=window['gte'], sale__date__lte=window['lte'])
    debts = Payment.objects.filter(user=session.user, date__gte=window['gte'], date__lte=window['lte'])
    refunds = SaleReturn.objects.filter(user=session.user, date__gte=window['gte'], date__lte=window['lte'],
                                        refund_amount__gt=0, refund_method__isnull=False)
    totals = cash_session_totals(
        initial_amount=session.initial_amount,
        sale_payments=sales.values_list('payment_method__name', 'payment_method__is_digital', 'amount'),
        debt_payments=debts.values_list('payment_method__name', 'payment_method__is_digital', 'amount'),
        refunds=refunds.values_list('refund_method__name', 'refund_method__is_digital', 'refund_amount'),
        expenses=CashExpense.objects.filter(session=session).values_list('amount', flat=True),
    )
    for field in STORED_FIELDS:
        setattr(session, field, totals[field])
    if save:
        session.save(update_fields=list(STORED_FIELDS))
    return totals
