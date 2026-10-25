"""Ingreso de stock en la web con la misma regla de Costo Promedio Ponderado que la app de escritorio."""
from core.stock_math import calculate_weighted_average_cost, to_decimal_qty
from .models import InventoryMovement


def receive_stock(product, quantity, unit_cost, reference, user):
    """Suma stock aplicando CPP; usar dentro de transaction.atomic con el producto bloqueado (select_for_update).

    unit_cost=None (ej. ingreso por escáner sin costo) deja el costo como está.
    """
    qty = to_decimal_qty(quantity)
    if unit_cost is not None:
        product.cost_price = calculate_weighted_average_cost(product.stock, product.cost_price, qty, unit_cost)
    product.stock = to_decimal_qty(product.stock) + qty
    product.save()
    InventoryMovement.objects.create(
        product=product,
        quantity=qty,
        cost_price=product.cost_price if unit_cost is not None else None,
        movement_type='IN',
        reference=reference,
        user=user
    )
    return product
