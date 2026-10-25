"""Ganancia Neta Real: una sola fórmula para el escritorio (SQLAlchemy) y la web (Django ORM).

Cada lado consulta sus filas y llama a build_profitability_summary con datos planos:
    Ganancia Neta = (Ventas - Devoluciones) - CMV - Gastos de caja - Mermas valorizadas
"""
from decimal import Decimal

from core.stock_math import to_decimal_money, to_decimal_qty

ZERO = Decimal('0.00')


def _money_sum(values):
    return sum((to_decimal_money(v or 0) for v in values), ZERO)


def _cost_sum(lines):
    # Costo por línea: cantidad (0.001) x costo unitario (0.01), redondeado a centavos
    return sum((to_decimal_money(to_decimal_qty(q or 0) * to_decimal_money(c or 0)) for q, c in lines), ZERO)


def build_profitability_summary(*, start, end, sales_totals, sold_lines, return_totals=(), returned_lines=(),
                                expenses=(), losses=(), adjustments=(), payments=()):
    """
    sales_totals: totales de venta · sold_lines: (cantidad, costo al vender) por detalle
    return_totals / returned_lines: idem para devoluciones (el CMV devuelto vuelve al stock)
    expenses: montos de gastos · losses: dicts {product, quantity, unit_cost, reason, date}
    adjustments: dicts {product, quantity, reference, date} (desposte dinámico)
    payments: (medio, monto) de SalePayment
    """
    sales_totals = list(sales_totals)
    gross_sales = _money_sum(sales_totals)
    returns = _money_sum(return_totals)
    total_sales = gross_sales - returns
    cmv = _cost_sum(sold_lines) - _cost_sum(returned_lines)
    gross_profit = total_sales - cmv
    expenses_total = _money_sum(expenses)

    loss_rows = []
    for loss in losses:
        row = dict(loss)
        row['quantity'] = to_decimal_qty(row['quantity'] or 0)
        row['unit_cost'] = to_decimal_money(row['unit_cost'] or 0)
        row['cost'] = to_decimal_money(row['quantity'] * row['unit_cost'])
        loss_rows.append(row)
    shrinkage_cost = sum((r['cost'] for r in loss_rows), ZERO)

    adjustment_rows = [dict(a, quantity=to_decimal_qty(a['quantity'] or 0)) for a in adjustments]

    by_method = {}
    for name, amount in payments:
        by_method[name] = by_method.get(name, ZERO) + to_decimal_money(amount or 0)

    return {
        'start': start,
        'end': end,
        'sales_count': len(sales_totals),
        'gross_sales': gross_sales,
        'returns': returns,
        'total_sales': total_sales,
        'cmv': cmv,
        'gross_profit': gross_profit,
        'gross_margin_pct': (gross_profit / total_sales * 100).quantize(Decimal('0.1')) if total_sales > 0 else Decimal('0.0'),
        'expenses': expenses_total,
        'shrinkage_cost': shrinkage_cost,
        'net_profit': gross_profit - expenses_total - shrinkage_cost,
        'losses': loss_rows,
        'auto_adjustments_count': len(adjustment_rows),
        'auto_adjustments': adjustment_rows,
        'payments_breakdown': by_method,
    }
