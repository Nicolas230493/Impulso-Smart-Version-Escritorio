"""Ganancia Neta Real en la web: mismas reglas que business_logic.get_profitability_and_audit_summary."""
from django.utils import timezone

from core.profitability import build_profitability_summary
from core.stock_math import AUTO_ADJUST_REASON, AUTO_ADJUST_TYPE
from products.models import InventoryMovement, StockLoss
from sales.models import Sale, SaleDetail, SalePayment, SaleReturn, SaleReturnDetail
from .models import CashExpense


def get_profitability_summary(start=None, end=None, cash_session=None):
    """Resumen de un turno (cash_session) o de un rango [start, end]."""
    user = None
    if cash_session:
        start, end, user = cash_session.start_date, cash_session.end_date or timezone.now(), cash_session.user
        expenses = CashExpense.objects.filter(session=cash_session)
    else:
        expenses = CashExpense.objects.filter(date__range=[start, end])

    sales = Sale.objects.filter(date__range=[start, end])
    returns = SaleReturn.objects.filter(date__range=[start, end])
    adjustments = InventoryMovement.objects.filter(movement_type=AUTO_ADJUST_TYPE, date__range=[start, end],
                                                   reference__contains=AUTO_ADJUST_REASON[:40])
    if user:
        sales, returns, adjustments = sales.filter(user=user), returns.filter(user=user), adjustments.filter(user=user)

    returned_lines = []
    for rd in SaleReturnDetail.objects.filter(sale_return__in=returns).select_related('sale_return', 'product'):
        sold = SaleDetail.objects.filter(sale_id=rd.sale_return.sale_id, product_id=rd.product_id).first()
        returned_lines.append((rd.quantity, sold.cost_price_at_sale if sold else rd.product.cost_price))

    losses = [{
        "date": loss.date, "product": loss.product.name, "quantity": loss.quantity, "reason": loss.reason,
        "unit_cost": loss.unit_cost if loss.unit_cost is not None else loss.product.cost_price,
    } for loss in StockLoss.objects.filter(date__range=[start, end]).select_related('product').order_by('date')]

    return build_profitability_summary(
        start=start, end=end,
        sales_totals=sales.values_list('total_amount', flat=True),
        sold_lines=SaleDetail.objects.filter(sale__in=sales).values_list('quantity', 'cost_price_at_sale'),
        return_totals=returns.values_list('total_amount', flat=True),
        returned_lines=returned_lines,
        expenses=expenses.values_list('amount', flat=True),
        losses=losses,
        adjustments=[{"date": m.date, "product": m.product.name, "quantity": m.quantity, "reference": m.reference}
                     for m in adjustments.select_related('product').order_by('date')],
        payments=SalePayment.objects.filter(sale__in=sales).values_list('payment_method__name', 'amount'),
    )
