"""Arqueo de un turno de caja: una sola fórmula para la web (finance/cash.py) y el escritorio (business_logic).

Los acumulados de CashSession son un caché que se recalcula SIEMPRE desde los registros:
    Efectivo esperado = Monto inicial + Ventas efectivo + Cobros de deuda en efectivo
                        - Reintegros de devoluciones en efectivo - Gastos/retiros
Cada lado consulta sus filas y pasa tuplas (nombre del medio, es_digital, monto). Lo fiado
(Cuenta Corriente) no entra en caja.
"""
from decimal import Decimal

from core.stock_math import CASH_METHOD, to_decimal_money

ZERO = Decimal('0.00')


def _split(rows):
    cash = digital = ZERO
    for name, is_digital, amount in rows:
        amount = to_decimal_money(amount or 0)
        if name == CASH_METHOD:
            cash += amount
        elif is_digital:
            digital += amount
    return cash, digital


def cash_session_totals(*, initial_amount, sale_payments=(), debt_payments=(), refunds=(), expenses=()):
    """sale_payments/debt_payments/refunds: (medio, es_digital, monto); expenses: montos."""
    cash_sales, digital_sales = _split(sale_payments)
    cash_debt, digital_debt = _split(debt_payments)
    cash_refunds, digital_refunds = _split(refunds)
    total_expenses = sum((to_decimal_money(e or 0) for e in expenses), ZERO)
    total_sales_cash = cash_sales + cash_debt - cash_refunds
    return {
        'cash_sales': cash_sales,
        'digital_sales': digital_sales,
        'cash_debt_payments': cash_debt,
        'digital_debt_payments': digital_debt,
        'cash_refunds': cash_refunds,
        'digital_refunds': digital_refunds,
        # Acumulados que se guardan en CashSession (mismos nombres de campo)
        'total_sales_cash': total_sales_cash,
        'total_sales_digital': digital_sales + digital_debt - digital_refunds,
        'total_expenses': total_expenses,
        'expected_final_amount': to_decimal_money(initial_amount or 0) + total_sales_cash - total_expenses,
    }
