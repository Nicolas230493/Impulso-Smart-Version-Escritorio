"""Reglas de ventas y devoluciones de la web, alineadas con la app de escritorio (business_logic.process_sale)."""
from decimal import Decimal

from django.db.models import Sum

from core.models import ActivityLog
from core.stock_math import (AUTO_ADJUST_REASON, AUTO_ADJUST_TYPE, CURRENT_ACCOUNT_METHOD, FINAL_CONSUMER_DNI,
                             capped_return_credit, to_decimal_money, to_decimal_qty, validate_quantity)
from customers.models import Customer, CurrentAccount
from finance.models import PaymentMethod
from products.models import InventoryMovement, Product
from .models import Sale, SaleDetail, SalePayment, SaleReturnDetail

ZERO = Decimal('0.00')


def resolve_payments(payments, total):
    """[(PaymentMethod, monto)] sin montos en cero.

    payments: [{'payment_method_id', 'amount'}] y como máximo uno {'payment_method_id', 'rest': True}
    que toma el saldo restante (evita diferencias de centavos con el total calculado en el navegador).
    Sin 'rest', la suma debe igualar el total exacto.
    """
    merged, rest_method = {}, None
    for p in payments:
        method_id = int(p['payment_method_id'])
        if p.get('rest'):
            if rest_method is not None:
                raise ValueError("Solo un medio de pago puede tomar el saldo restante.")
            rest_method = method_id
            continue
        amount = to_decimal_money(p['amount'])
        if amount < 0:
            raise ValueError("Los montos de pago no pueden ser negativos.")
        merged[method_id] = merged.get(method_id, ZERO) + amount
    explicit = sum(merged.values(), ZERO)
    if rest_method is not None:
        rest = total - explicit
        if rest < 0:
            raise ValueError(f"Los montos ingresados (${explicit}) superan el total de la venta (${total}).")
        merged[rest_method] = merged.get(rest_method, ZERO) + rest
    elif explicit != total:
        raise ValueError(f"La suma de los pagos (${explicit}) no coincide con el total de la venta (${total}).")

    result = []
    for method_id, amount in merged.items():
        if amount == 0:
            continue
        pm = PaymentMethod.objects.filter(pk=method_id, active=True).first()
        if not pm:
            raise ValueError(f"Medio de pago ID {method_id} inexistente o inactivo.")
        result.append((pm, amount))
    if total > 0 and not result:
        raise ValueError("Debe indicar un medio de pago.")
    return result


def register_sale(user, customer, cart, payments, discount=0, surcharge=0, points_redeemed=0, points_discount=0):
    """Venta web con las reglas del escritorio: cantidades pesables, desposte dinámico y cobro mixto.

    Llamar dentro de transaction.atomic(). cart: [{'id', 'qty', 'discounted_price', 'original_price_at_sale'}].
    Devuelve {"sale", "payments": [(PaymentMethod, monto)], "auto_adjustments": [...]}; ValueError si algo no valida.
    """
    discount, surcharge, points_discount = (to_decimal_money(v or 0) for v in (discount, surcharge, points_discount))
    points_redeemed = int(points_redeemed or 0)
    if not cart:
        raise ValueError("El carrito está vacío.")

    lines = []
    for item in cart:
        product = Product.objects.select_for_update().get(pk=item['id'])
        try:
            qty = validate_quantity(item['qty'], product.is_weighable)
        except ValueError as e:
            raise ValueError(f"{product.name}: {e}")
        price = to_decimal_money(item.get('discounted_price', item.get('price')))
        original = to_decimal_money(item.get('original_price_at_sale', price))
        lines.append((product, qty, price, original, to_decimal_money(price * qty)))

    total = sum((line[4] for line in lines), ZERO) - discount - points_discount + surcharge
    if total < 0:
        raise ValueError("El total de la venta no puede ser negativo.")
    resolved = resolve_payments(payments, total)
    cc_amount = sum((amt for pm, amt in resolved if pm.name == CURRENT_ACCOUNT_METHOD), ZERO)

    if customer:
        customer = Customer.objects.select_for_update().get(pk=customer.pk)
    if points_redeemed > 0 and (not customer or customer.points < points_redeemed):
        raise ValueError("Puntos insuficientes para el canje.")
    if cc_amount > 0:
        # Validaciones de fiado solo sobre la porción en Cuenta Corriente
        if not customer:
            raise ValueError("Debe seleccionar un cliente para vender a Cuenta Corriente.")
        if customer.dni_cuit == FINAL_CONSUMER_DNI:
            raise ValueError("No se puede fiar al Consumidor Final.")
        if customer.limite_credito > 0 and customer.balance + cc_amount > customer.limite_credito:
            raise ValueError(f"Límite de crédito excedido. Saldo actual: ${customer.balance}, Límite: ${customer.limite_credito}")

    sale = Sale.objects.create(
        user=user,
        customer=customer,
        total_amount=total,
        discount_amount=discount,
        points_redeemed=points_redeemed,
        points_discount=points_discount,
        surcharge_amount=surcharge,
        # Medio principal (mayor monto) para reportes que aún leen Sale.payment_method
        payment_method=max(resolved, key=lambda p: p[1])[0] if resolved else None,
    )
    for pm, amount in resolved:
        SalePayment.objects.create(sale=sale, payment_method=pm, amount=amount)

    auto_adjustments, total_tax, total_promo = [], ZERO, ZERO
    for product, qty, price, original, subtotal in lines:
        stock_before = to_decimal_qty(product.stock)
        current = stock_before
        if current < qty:
            # Desposte dinámico: ingresar el faltante para que la venta deje el stock en 0.000
            missing = qty - current
            InventoryMovement.objects.create(product=product, quantity=missing, movement_type=AUTO_ADJUST_TYPE,
                                             reference=f"Venta #{sale.id} - {AUTO_ADJUST_REASON}"[:100], user=user)
            current += missing
            auto_adjustments.append({"product_id": product.id, "product_name": product.name, "stock_before": stock_before,
                                     "adjusted_qty": missing, "quantity_sold": qty})
        product.stock = current - qty
        product.save()

        # El precio incluye IVA: se desglosa
        tax = to_decimal_money(subtotal - subtotal / (1 + product.tax_rate / 100))
        total_tax += tax
        total_promo += to_decimal_money((original - price) * qty)
        SaleDetail.objects.create(sale=sale, product=product, quantity=qty, price=price, cost_price_at_sale=product.cost_price,
                                  tax_rate=product.tax_rate, tax_amount=tax, subtotal=subtotal)
        InventoryMovement.objects.create(product=product, quantity=qty, movement_type='OUT', reference=f"Venta #{sale.id}", user=user)

    sale.tax_amount = total_tax
    sale.promo_discount = total_promo
    sale.save(update_fields=['tax_amount', 'promo_discount'])

    if customer:
        customer.points += int(total / Decimal('1000')) - points_redeemed
        if cc_amount > 0:
            customer.balance += cc_amount
            CurrentAccount.objects.create(customer=customer, amount=cc_amount, entry_type='DEBT',
                                          reference=f"Venta #{sale.id}", balance_after=customer.balance)
        customer.save()
    if points_redeemed > 0:
        ActivityLog.objects.create(user=user, action=f"Canje de {points_redeemed} puntos - Venta #{sale.id}", module="Fidelización",
                                   details=f"Cliente: {customer.full_name}, Descuento: ${points_discount}")
    if auto_adjustments:
        names = ", ".join(f"{a['product_name']} (+{a['adjusted_qty']})" for a in auto_adjustments)
        ActivityLog.objects.create(user=user, action=f"Desposte dinámico en Venta #{sale.id}: {names}"[:255], module="Inventario")
    return {"sale": sale, "payments": resolved, "auto_adjustments": auto_adjustments}


def returnable_quantity(sale, product_id):
    """Vendido de un producto en la venta menos lo ya devuelto en devoluciones anteriores."""
    sold = sale.details.filter(product_id=product_id).aggregate(t=Sum('quantity'))['t'] or Decimal('0')
    returned = SaleReturnDetail.objects.filter(sale_return__sale=sale, product_id=product_id).aggregate(t=Sum('quantity'))['t'] or Decimal('0')
    return to_decimal_qty(sold) - to_decimal_qty(returned)


def credit_return_to_current_account(sale_return):
    """Acredita una devolución en Cuenta Corriente solo hasta lo fiado en la venta (según SalePayment),
    descontando lo ya acreditado por devoluciones anteriores de esa venta. Devuelve el monto acreditado."""
    sale = sale_return.sale
    if not sale.customer_id:
        return Decimal('0.00')

    payments = SalePayment.objects.filter(sale=sale)
    if payments.exists():
        on_credit = payments.filter(payment_method__name=CURRENT_ACCOUNT_METHOD).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    elif sale.payment_method and sale.payment_method.name == CURRENT_ACCOUNT_METHOD:
        on_credit = sale.total_amount
    else:
        on_credit = Decimal('0.00')

    previous_refs = [f"Devolución #{pk}" for pk in sale.returns.exclude(pk=sale_return.pk).values_list('pk', flat=True)]
    already_credited = CurrentAccount.objects.filter(
        customer_id=sale.customer_id, entry_type='CREDIT', reference__in=previous_refs
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    credit = capped_return_credit(sale_return.total_amount, on_credit, already_credited)
    if credit <= 0:
        return Decimal('0.00')

    customer = Customer.objects.select_for_update().get(pk=sale.customer_id)
    customer.balance -= credit
    customer.save()
    CurrentAccount.objects.create(
        customer=customer,
        amount=credit,
        entry_type='CREDIT',
        reference=f"Devolución #{sale_return.id}",
        balance_after=customer.balance
    )
    return credit
