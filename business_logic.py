from db_manager import (db, utc_now, Product, Sale, SaleDetail, SalePayment, Customer, CashSession, CashExpense, PaymentMethod,
                        ActivityLog, CurrentAccount, InventoryMovement, Supplier, Purchase, PurchaseDetail,
                        SaleReturn, SaleReturnDetail, StockLoss, Category, PriceLog, Payment)
import datetime
import re
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import func, and_, or_, select
from core.stock_math import (QTY_STEP, MONEY_STEP, ZERO_QTY, to_decimal_qty, to_decimal_money, validate_quantity,
                             validate_sale_quantity, calculate_weighted_average_cost, format_qty,
                             CASH_METHOD, CURRENT_ACCOUNT_METHOD, FINAL_CONSUMER_DNI, AUTO_ADJUST_TYPE, AUTO_ADJUST_REASON,
                             capped_return_credit)
from core.profitability import build_profitability_summary
from core.cash import cash_session_totals
from core import backup_manager
from core.timeutils import to_local, local_to_utc, local_now

# --- Consultas para la GUI (devuelven datos planos, sesión siempre cerrada) ---

def _product_to_dict(p):
    return {
        "id": p.id,
        "sku": p.sku,
        "barcode": p.barcode,
        "name": p.name,
        "unit": p.unit,
        "price": to_decimal_money(p.price or 0),
        "cost_price": to_decimal_money(p.cost_price or 0),
        "stock": to_decimal_qty(p.stock or 0),
        "is_weighable": bool(p.is_weighable),
        "expiry_date": p.expiry_date,
    }

def get_inventory_list():
    session = db.get_session()
    try:
        return [_product_to_dict(p) for p in session.query(Product).order_by(Product.name).all()]
    finally:
        session.close()

def search_products_for_sale(query=""):
    # Sin filtro de stock > 0: el desposte dinámico permite vender sin stock previo
    session = db.get_session()
    try:
        prods = session.query(Product)
        if query:
            like = f"%{query.strip()}%"
            prods = prods.filter(or_(Product.name.ilike(like), Product.sku.ilike(like), Product.barcode.ilike(like)))
        return [_product_to_dict(p) for p in prods.order_by(Product.name).all()]
    finally:
        session.close()

def find_product_by_code(code):
    """Coincidencia exacta por código de barras o SKU (lector de códigos)."""
    code = (code or "").strip()
    if not code:
        return None
    session = db.get_session()
    try:
        p = session.query(Product).filter(or_(Product.barcode == code, Product.sku == code)).first()
        return _product_to_dict(p) if p else None
    finally:
        session.close()

def get_sale_ticket_data(sale_id):
    """Datos planos de una venta para armar el comprobante."""
    session = db.get_session()
    try:
        sale = session.query(Sale).filter(Sale.id == sale_id).first()
        if not sale:
            raise ValueError(f"Venta #{sale_id} inexistente.")
        customer = session.query(Customer).filter(Customer.id == sale.customer_id).first() if sale.customer_id else None
        items = []
        for d, name, weighable in session.query(SaleDetail, Product.name, Product.is_weighable)\
                .outerjoin(Product, Product.id == SaleDetail.product_id)\
                .filter(SaleDetail.sale_id == sale_id).order_by(SaleDetail.id).all():
            items.append({
                "name": name or "(producto eliminado)",
                "is_weighable": bool(weighable),
                "quantity": to_decimal_qty(d.quantity),
                "price": to_decimal_money(d.price),
                "subtotal": to_decimal_money(d.subtotal),
            })
        payments = [{"name": name, "amount": to_decimal_money(amount)} for amount, name in
                    session.query(SalePayment.amount, PaymentMethod.name)
                    .join(PaymentMethod, PaymentMethod.id == SalePayment.payment_method_id)
                    .filter(SalePayment.sale_id == sale_id).order_by(SalePayment.id).all()]
        if not payments and sale.payment_method_id:
            # Ventas sin SalePayment: se informa el método único por el total
            pm = session.query(PaymentMethod).filter(PaymentMethod.id == sale.payment_method_id).first()
            payments = [{"name": pm.name if pm else "-", "amount": to_decimal_money(sale.total_amount)}]
        return {
            "sale_id": sale.id,
            "date": to_local(sale.date),
            "customer": customer.full_name if customer else "Consumidor Final",
            "items": items,
            "discount": to_decimal_money(sale.discount_amount or 0),
            "points_discount": to_decimal_money(sale.points_discount or 0),
            "surcharge": to_decimal_money(sale.surcharge_amount or 0),
            "total": to_decimal_money(sale.total_amount),
            "payments": payments,
        }
    finally:
        session.close()

def get_payment_methods():
    session = db.get_session()
    try:
        return [{"id": pm.id, "name": pm.name, "is_digital": bool(pm.is_digital)}
                for pm in session.query(PaymentMethod).filter(PaymentMethod.active == True).order_by(PaymentMethod.id).all()]
    finally:
        session.close()

def get_customers_list():
    session = db.get_session()
    try:
        return [{
            "id": c.id,
            "full_name": c.full_name,
            "dni_cuit": c.dni_cuit,
            "phone": c.phone,
            "balance": to_decimal_money(c.balance or 0),
            "points": c.points or 0,
            "limite_credito": to_decimal_money(c.limite_credito or 0),
            "is_final_consumer": c.dni_cuit == FINAL_CONSUMER_DNI,
        } for c in session.query(Customer).order_by(Customer.full_name).all()]
    finally:
        session.close()

def get_suppliers_list():
    session = db.get_session()
    try:
        return [{"id": s.id, "name": s.name, "phone": s.phone, "email": s.email, "address": s.address}
                for s in session.query(Supplier).order_by(Supplier.name).all()]
    finally:
        session.close()

def get_open_cash_session(user_id=1):
    session = db.get_session()
    try:
        cs = session.query(CashSession).filter(CashSession.is_open == True, CashSession.user_id == user_id).first()
        if not cs:
            return None
        return {
            "id": cs.id,
            "start_date": to_local(cs.start_date),
            "initial_amount": to_decimal_money(cs.initial_amount or 0),
            "total_sales_cash": to_decimal_money(cs.total_sales_cash or 0),
            "total_sales_digital": to_decimal_money(cs.total_sales_digital or 0),
            "total_expenses": to_decimal_money(cs.total_expenses or 0),
        }
    finally:
        session.close()

def get_last_closed_cash_session(user_id=1):
    session = db.get_session()
    try:
        cs = session.query(CashSession).filter(CashSession.is_open == False, CashSession.user_id == user_id)\
            .order_by(CashSession.end_date.desc()).first()
        if not cs:
            return None
        return {"id": cs.id, "start_date": to_local(cs.start_date), "end_date": to_local(cs.end_date)}
    finally:
        session.close()

def get_profitability_and_audit_summary(start_date=None, end_date=None, cash_session_id=None):
    """Ganancia Neta Real y auditoría de desposte de un turno (cash_session_id) o de un rango de fechas.

    Con turno: ventas y devoluciones del cajero dentro de su ventana, gastos de esa caja.
    Con rango: todo lo ocurrido entre start_date y end_date (hora local, inclusive). Las mermas siempre van por fecha.
    Las fechas del resultado están en hora local.
    """
    session = db.get_session()
    try:
        user_id = None
        if cash_session_id:
            cs = session.query(CashSession).filter(CashSession.id == cash_session_id).first()
            if not cs:
                raise ValueError(f"Sesión de caja #{cash_session_id} inexistente.")
            start_date, end_date, user_id = cs.start_date, cs.end_date or utc_now(), cs.user_id
            expenses = [e.amount for e in session.query(CashExpense).filter(CashExpense.session_id == cs.id)]
        else:
            if not start_date or not end_date:
                raise ValueError("Indique el rango de fechas.")
            start_date, end_date = local_to_utc(start_date), local_to_utc(end_date)
            expenses = [e.amount for e in session.query(CashExpense).filter(CashExpense.date.between(start_date, end_date))]

        sale_filter = [Sale.date.between(start_date, end_date)]
        return_filter = [SaleReturn.date.between(start_date, end_date)]
        adj_filter = [InventoryMovement.movement_type == AUTO_ADJUST_TYPE,
                      InventoryMovement.reference.like(f"%{AUTO_ADJUST_REASON[:40]}%"),
                      InventoryMovement.date.between(start_date, end_date)]
        if user_id:
            sale_filter.append(Sale.user_id == user_id)
            return_filter.append(SaleReturn.user_id == user_id)
            adj_filter.append(InventoryMovement.user_id == user_id)
        sale_ids = select(Sale.id).where(*sale_filter)

        sales_totals = [t for (t,) in session.query(Sale.total_amount).filter(*sale_filter)]
        sold_lines = session.query(SaleDetail.quantity, SaleDetail.cost_price_at_sale).filter(SaleDetail.sale_id.in_(sale_ids)).all()
        payments = session.query(PaymentMethod.name, SalePayment.amount)\
            .join(PaymentMethod, PaymentMethod.id == SalePayment.payment_method_id)\
            .filter(SalePayment.sale_id.in_(sale_ids)).all()

        return_totals = [t for (t,) in session.query(SaleReturn.total_amount).filter(*return_filter)]
        returned_lines = []
        for rd, sale_id, current_cost in session.query(SaleReturnDetail, SaleReturn.sale_id, Product.cost_price)\
                .join(SaleReturn, SaleReturn.id == SaleReturnDetail.sale_return_id)\
                .join(Product, Product.id == SaleReturnDetail.product_id).filter(*return_filter):
            sold_cost = session.query(SaleDetail.cost_price_at_sale).filter(
                SaleDetail.sale_id == sale_id, SaleDetail.product_id == rd.product_id).scalar()
            returned_lines.append((rd.quantity, sold_cost if sold_cost is not None else current_cost))

        losses = [{
            "date": to_local(loss.date), "product": name, "quantity": loss.quantity, "reason": loss.reason,
            "unit_cost": loss.unit_cost if loss.unit_cost is not None else current_cost,
        } for loss, name, current_cost in session.query(StockLoss, Product.name, Product.cost_price)
            .join(Product, Product.id == StockLoss.product_id).filter(StockLoss.date.between(start_date, end_date))
            .order_by(StockLoss.date)]

        adjustments = [{"date": to_local(m.date), "product": name, "quantity": m.quantity, "reference": m.reference}
                       for m, name in session.query(InventoryMovement, Product.name)
                       .join(Product, Product.id == InventoryMovement.product_id).filter(*adj_filter)
                       .order_by(InventoryMovement.date)]

        summary = build_profitability_summary(
            start=to_local(start_date), end=to_local(end_date), sales_totals=sales_totals, sold_lines=sold_lines,
            return_totals=return_totals, returned_lines=returned_lines, expenses=expenses,
            losses=losses, adjustments=adjustments, payments=payments)
        summary["cash_session_id"] = cash_session_id
        return summary
    finally:
        session.close()

def get_payment_method_id(name):
    session = db.get_session()
    try:
        pm = session.query(PaymentMethod).filter(PaymentMethod.name == name).first()
        return pm.id if pm else None
    finally:
        session.close()


def log_activity(user_id, action, module):
    session = db.get_session()
    log = ActivityLog(user_id=user_id, action=action, module=module)
    session.add(log)
    session.commit()
    session.close()

def _normalize_payments(session, payments, payment_method_id, total):
    """[(PaymentMethod, monto)] sin montos en cero; la suma debe igualar el total exacto."""
    if total < 0:
        raise ValueError("El total de la venta no puede ser negativo.")
    if payments is None:
        if payment_method_id is None:
            raise ValueError("Debe indicar un medio de pago.")
        payments = [{'payment_method_id': payment_method_id, 'amount': total}]
    merged = {}
    for p in payments:
        amount = to_decimal_money(p['amount'])
        if amount < 0:
            raise ValueError("Los montos de pago no pueden ser negativos.")
        merged[p['payment_method_id']] = merged.get(p['payment_method_id'], Decimal('0.00')) + amount
    paid = sum(merged.values(), Decimal('0.00'))
    if paid != total:
        raise ValueError(f"La suma de los pagos (${paid}) no coincide con el total de la venta (${total}).")
    result = []
    for method_id, amount in merged.items():
        if amount == 0:
            continue
        pm = session.query(PaymentMethod).filter(PaymentMethod.id == method_id).first()
        if not pm or not pm.active:
            raise ValueError(f"Medio de pago ID {method_id} inexistente o inactivo.")
        result.append((pm, amount))
    return result

CASH_SESSION_FIELDS = ('total_sales_cash', 'total_sales_digital', 'total_expenses', 'expected_final_amount')

def _recalculate_cash_session(session, cs):
    """Misma fórmula que la web (core.cash / finance.cash): acumulados del turno desde los registros,
    no sumas incrementales, para que escritorio y web nunca diverjan."""
    end = cs.end_date or utc_now()
    pm_cols = (PaymentMethod.name, PaymentMethod.is_digital)
    sale_rows = session.query(*pm_cols, SalePayment.amount).join(SalePayment, SalePayment.payment_method_id == PaymentMethod.id)\
        .join(Sale, Sale.id == SalePayment.sale_id).filter(Sale.user_id == cs.user_id, Sale.date.between(cs.start_date, end)).all()
    debt_rows = session.query(*pm_cols, Payment.amount).join(Payment, Payment.payment_method_id == PaymentMethod.id)\
        .filter(Payment.user_id == cs.user_id, Payment.date.between(cs.start_date, end)).all()
    refund_rows = session.query(*pm_cols, SaleReturn.refund_amount).join(SaleReturn, SaleReturn.refund_method_id == PaymentMethod.id)\
        .filter(SaleReturn.user_id == cs.user_id, SaleReturn.date.between(cs.start_date, end), SaleReturn.refund_amount > 0).all()
    expenses = [amount for (amount,) in session.query(CashExpense.amount).filter(CashExpense.session_id == cs.id)]
    totals = cash_session_totals(initial_amount=cs.initial_amount, sale_payments=sale_rows, debt_payments=debt_rows,
                                 refunds=refund_rows, expenses=expenses)
    for field in CASH_SESSION_FIELDS:
        setattr(cs, field, totals[field])
    return totals

def _sync_open_cash_session(session, user_id):
    cs = session.query(CashSession).filter(CashSession.is_open == True, CashSession.user_id == user_id).first()
    return _recalculate_cash_session(session, cs) if cs else None

def process_sale(cart_items, customer_id, payment_method_id=None, user_id=1, discount=0, surcharge=0, points_redeemed=0, points_discount=0, payments=None):
    """Registra la venta de forma atómica.

    payments: [{'payment_method_id', 'amount'}] para cobro mixto; si es None se usa
    payment_method_id por el total. Devuelve (True, {"sale_id", "total", "payments",
    "auto_adjustments"}) o (False, mensaje).
    """
    if not cart_items:
        return False, "El carrito está vacío."
    session = db.get_session()
    try:
        # Normalizar líneas: cantidad 0.001, precio 0.01, subtotal cuantizado a 0.01
        lines = []
        for item in cart_items:
            product = session.query(Product).filter(Product.id == item['id']).first()
            if not product:
                raise ValueError(f"Producto ID {item['id']} inexistente.")
            try:
                qty = validate_sale_quantity(item['quantity'], product.is_weighable)
            except ValueError as e:
                raise ValueError(f"{product.name}: {e}")
            price = to_decimal_money(item['price'])
            lines.append((product, qty, price, (price * qty).quantize(MONEY_STEP, rounding=ROUND_HALF_UP)))

        subtotal_cart = sum((line[3] for line in lines), Decimal('0.00'))
        discount = to_decimal_money(discount)
        surcharge = to_decimal_money(surcharge)
        points_discount = to_decimal_money(points_discount)
        total_final = subtotal_cart - discount - points_discount + surcharge
        
        customer = None
        if customer_id:
            customer = session.query(Customer).filter(Customer.id == customer_id).first()
            if not customer:
                raise ValueError(f"Cliente ID {customer_id} inexistente (¿fue eliminado?).")

        payments = _normalize_payments(session, payments, payment_method_id, total_final)
        cc_amount = sum((amt for pm, amt in payments if pm.name == CURRENT_ACCOUNT_METHOD), Decimal('0.00'))
        # Sale.payment_method conserva el medio principal (mayor monto) para los reportes existentes
        primary_method_id = max(payments, key=lambda p: p[1])[0].id if payments else payment_method_id

        if cc_amount > 0:
            # Validaciones de fiado solo sobre la porción en Cuenta Corriente
            if not customer: return False, "Debe seleccionar un cliente para vender a Cuenta Corriente."
            if customer.dni_cuit == FINAL_CONSUMER_DNI: return False, "No se puede fiar al Consumidor Final."
            if customer.limite_credito > 0 and (customer.balance + cc_amount) > customer.limite_credito:
                return False, f"Límite de crédito excedido. Saldo actual: ${customer.balance}, Límite: ${customer.limite_credito}"

        if points_redeemed > 0:
            if not customer or customer.points < points_redeemed: return False, "Puntos insuficientes."

        new_sale = Sale(
            total_amount=total_final,
            discount_amount=discount,
            points_redeemed=points_redeemed,
            points_discount=points_discount,
            surcharge_amount=surcharge,
            customer_id=customer_id if customer_id else None,
            payment_method_id=primary_method_id,
            user_id=user_id,
            date=utc_now()
        )
        session.add(new_sale)
        session.flush()

        for pm, amount in payments:
            session.add(SalePayment(sale_id=new_sale.id, payment_method_id=pm.id, amount=amount))

        auto_adjustments = []
        for product, qty, price, subtotal in lines:
            stock_before = to_decimal_qty(product.stock or 0)
            current = stock_before
            if current < qty:
                # Desposte dinámico: ingresar el faltante para que la venta deje el stock en 0.000
                missing_qty = qty - current
                session.add(InventoryMovement(
                    product_id=product.id,
                    quantity=missing_qty,
                    movement_type=AUTO_ADJUST_TYPE,
                    reference=f"Venta #{new_sale.id} - {AUTO_ADJUST_REASON}"[:100],
                    user_id=user_id
                ))
                current += missing_qty
                auto_adjustments.append({
                    "product_id": product.id,
                    "product_name": product.name,
                    "stock_before": stock_before,
                    "adjusted_qty": missing_qty,
                    "quantity_sold": qty,
                })

            product.stock = current - qty
            
            detail = SaleDetail(
                sale_id=new_sale.id,
                product_id=product.id,
                quantity=qty,
                price=price,
                cost_price_at_sale=product.cost_price,
                tax_rate=product.tax_rate,
                subtotal=subtotal
            )
            session.add(detail)
            
            inv_mov = InventoryMovement(
                product_id=product.id,
                quantity=qty,
                movement_type='OUT',
                reference=f"Venta #{new_sale.id}",
                user_id=user_id
            )
            session.add(inv_mov)

        if customer:
            points_earned = int(total_final / Decimal('1000'))
            customer.points += points_earned
            if points_redeemed > 0:
                customer.points -= points_redeemed
            
            if cc_amount > 0:
                customer.balance += cc_amount
                acc = CurrentAccount(
                    customer_id=customer.id,
                    amount=cc_amount,
                    entry_type='DEBT',
                    reference=f"Venta #{new_sale.id}",
                    balance_after=customer.balance
                )
                session.add(acc)

        # A la caja solo impacta la porción en efectivo y la digital; el fiado no entra en caja
        _sync_open_cash_session(session, user_id)

        breakdown = " + ".join(f"{pm.name} ${amt}" for pm, amt in payments)
        log = ActivityLog(user_id=user_id, action=f"Venta confirmada #{new_sale.id} - Total: ${total_final}"[:255], module="Ventas", details=f"Pagos: {breakdown}")
        session.add(log)
        if auto_adjustments:
            names = ", ".join(f"{a['product_name']} (+{a['adjusted_qty']})" for a in auto_adjustments)
            session.add(ActivityLog(user_id=user_id, action=f"Desposte dinámico en Venta #{new_sale.id}: {names}"[:255], module="Inventario"))
        session.commit()
        return True, {
            "sale_id": new_sale.id,
            "total": total_final,
            "payments": [{"payment_method_id": pm.id, "name": pm.name, "amount": amt} for pm, amt in payments],
            "auto_adjustments": auto_adjustments,
        }
    except Exception as e:
        session.rollback()
        return False, str(e)
    finally:
        session.close()

def register_purchase_or_stock_entry(items, supplier_id=None, invoice_number=None, user_id=1):
    """Ingreso de mercadería con Costo Promedio Ponderado, en una sola transacción.

    items: [{'product_id', 'quantity', 'unit_cost'}]. Con supplier_id también registra la
    Compra (Purchase + PurchaseDetail). Devuelve (True, {"purchase_id", "total", "items"})
    o (False, mensaje).
    """
    if not items:
        return False, "No hay ítems para ingresar."
    session = db.get_session()
    try:
        purchase = None
        if supplier_id:
            if not session.query(Supplier).filter(Supplier.id == supplier_id).first():
                raise ValueError(f"Proveedor ID {supplier_id} inexistente.")
            purchase = Purchase(supplier_id=supplier_id, invoice_number=invoice_number or None,
                                total_amount=Decimal('0.00'), user_id=user_id, date=utc_now())
            session.add(purchase)
            session.flush()
        reference = f"Compra #{purchase.id}" if purchase else "Ingreso de mercadería"

        total = Decimal('0.00')
        results = []
        for item in items:
            product = session.query(Product).filter(Product.id == item['product_id']).first()
            if not product:
                raise ValueError(f"Producto ID {item['product_id']} inexistente.")
            try:
                qty = validate_quantity(item['quantity'], product.is_weighable)
                incoming_cost = to_decimal_money(item['unit_cost'])
                if incoming_cost < 0:
                    raise ValueError("El costo no puede ser negativo.")
            except ValueError as e:
                raise ValueError(f"{product.name}: {e}")

            stock_before = to_decimal_qty(product.stock or 0)
            cost_before = to_decimal_money(product.cost_price or 0)
            new_cost = calculate_weighted_average_cost(stock_before, cost_before, qty, incoming_cost)
            product.cost_price = new_cost
            product.stock = stock_before + qty

            session.add(InventoryMovement(
                product_id=product.id,
                quantity=qty,
                movement_type='IN',
                reference=reference,
                cost_price=new_cost,
                user_id=user_id
            ))
            subtotal = (qty * incoming_cost).quantize(MONEY_STEP, rounding=ROUND_HALF_UP)
            if purchase:
                session.add(PurchaseDetail(purchase_id=purchase.id, product_id=product.id, quantity=qty,
                                           cost_price=incoming_cost, subtotal=subtotal))
            total += subtotal
            results.append({
                "product_id": product.id,
                "product_name": product.name,
                "quantity": qty,
                "stock_before": stock_before,
                "stock_after": stock_before + qty,
                "cost_before": cost_before,
                "incoming_cost": incoming_cost,
                "new_cost": new_cost,
            })

        if purchase:
            purchase.total_amount = total
        session.add(ActivityLog(user_id=user_id, action=f"{reference} - {len(results)} ítems - Total: ${total}", module="Inventario"))
        session.commit()
        return True, {"purchase_id": purchase.id if purchase else None, "total": total, "items": results}
    except Exception as e:
        session.rollback()
        return False, str(e)
    finally:
        session.close()

def open_cash_session(initial_balance, user_id=1):
    try:
        initial = to_decimal_money(initial_balance)
    except ValueError:
        return False, "Monto inicial inválido."
    if initial < 0:
        return False, "El monto inicial no puede ser negativo."
    session = db.get_session()
    try:
        existing = session.query(CashSession).filter(CashSession.is_open == True, CashSession.user_id == user_id).first()
        if existing:
            return False, "Ya tienes una sesión de caja activa."
        session.add(CashSession(initial_amount=initial, user_id=user_id, total_sales_cash=0, total_sales_digital=0,
                                total_expenses=0, expected_final_amount=0, is_open=True, start_date=utc_now()))
        session.commit()
        return True, "Caja abierta con éxito."
    finally:
        session.close()

def add_cash_expense(amount, description, user_id=1):
    try:
        amount = to_decimal_money(amount)
    except ValueError:
        return False, "Monto de gasto inválido."
    description = (description or "").strip()
    if amount <= 0:
        return False, "El monto del gasto debe ser mayor a cero."
    if not description:
        return False, "Ingrese una descripción del gasto."
    session = db.get_session()
    try:
        open_s = session.query(CashSession).filter(CashSession.is_open == True, CashSession.user_id == user_id).first()
        if not open_s:
            return False, "Debes abrir caja para registrar gastos."
        session.add(CashExpense(session_id=open_s.id, amount=amount, description=description[:255], date=utc_now()))
        _recalculate_cash_session(session, open_s)
        session.commit()
        return True, "Gasto registrado."
    finally:
        session.close()

def close_cash_session(real_final_amount, notes="", user_id=1):
    try:
        real = to_decimal_money(real_final_amount)
    except ValueError:
        return False, "Monto contado inválido."
    if real < 0:
        return False, "El monto contado no puede ser negativo."
    session = db.get_session()
    try:
        open_s = session.query(CashSession).filter(CashSession.is_open == True, CashSession.user_id == user_id).first()
        if not open_s:
            return False, "No hay caja abierta para cerrar."
        open_s.end_date = utc_now()
        totals = _recalculate_cash_session(session, open_s)  # esperado al momento exacto del cierre
        open_s.real_final_amount = real
        open_s.notes = notes
        open_s.is_open = False
        diff = real - totals['expected_final_amount']
        session.commit()
    finally:
        session.close()
    msg = f"Caja cerrada. Diferencia: ${diff}"
    try:
        daily = backup_manager.ensure_daily_backup(db.db_path)
        if daily:
            msg += f"\nCopia de seguridad diaria creada: {daily.name}"
    except Exception as e:  # el respaldo nunca debe impedir cerrar la caja
        msg += f"\nAviso: no se pudo crear la copia de seguridad diaria ({e})."
    return True, msg

UNIT_CHOICES = ['unidad', 'kg', 'lt', 'm', 'caja', 'paquete']  # products.models.Product.UNIT_CHOICES

def parse_local_date(text):
    """'31/12/2026' o '2026-12-31' -> date; vacío -> None."""
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Fecha inválida: '{text}' (use dd/mm/aaaa).")

def get_categories_list():
    session = db.get_session()
    try:
        return [{"id": c.id, "name": c.name} for c in session.query(Category).order_by(Category.name).all()]
    finally:
        session.close()

def get_product(product_id):
    session = db.get_session()
    try:
        p = session.query(Product).filter(Product.id == product_id).first()
        if not p:
            return None
        data = _product_to_dict(p)
        data.update({
            "description": p.description or "",
            "min_stock": to_decimal_qty(p.min_stock or 0),
            "tax_rate": to_decimal_money(p.tax_rate if p.tax_rate is not None else 21),
            "category_id": p.category_id,
            "supplier_id": p.supplier_id,
        })
        return data
    finally:
        session.close()

def save_product(data, product_id=None, user_id=1):
    """Alta o edición de producto desde el escritorio. Devuelve (True, product_id) o (False, mensaje).

    data: textos de la UI (name, sku, barcode, unit, is_weighable, price, cost_price, tax_rate,
    min_stock, expiry_date, supplier_id, category_id y, solo en alta, initial_stock).
    El stock de un producto existente no se edita aquí: entra por Ingreso de Mercadería (CPP).
    """
    session = db.get_session()
    try:
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("El nombre es obligatorio.")
        is_weighable = bool(data.get("is_weighable"))
        unit = data.get("unit") or ("kg" if is_weighable else "unidad")
        if unit not in UNIT_CHOICES:
            raise ValueError(f"Unidad inválida: {unit}.")
        if is_weighable and unit == "unidad":
            unit = "kg"
        price = to_decimal_money(data.get("price") or 0)
        cost = to_decimal_money(data.get("cost_price") or 0)
        tax_rate = to_decimal_money(data.get("tax_rate") or 0)
        min_stock = to_decimal_qty(data.get("min_stock") or 0)
        if price < 0 or cost < 0 or min_stock < 0:
            raise ValueError("Precio, costo y stock mínimo no pueden ser negativos.")
        if not (0 <= tax_rate <= 100):
            raise ValueError("La tasa de IVA debe estar entre 0 y 100.")
        if not is_weighable and min_stock != min_stock.to_integral_value():
            raise ValueError("El stock mínimo de un producto por unidad debe ser entero.")
        expiry = parse_local_date(data.get("expiry_date"))

        sku = (data.get("sku") or "").strip()
        if not sku:
            next_id = (session.query(func.max(Product.id)).scalar() or 0) + 1
            sku = f"SKU-{next_id:05d}"
            while session.query(Product.id).filter(Product.sku == sku).first():
                next_id += 1
                sku = f"SKU-{next_id:05d}"
        barcode = (data.get("barcode") or "").strip() or None
        dup = session.query(Product.id).filter(Product.sku == sku, Product.id != (product_id or 0)).first()
        if dup:
            raise ValueError(f"Ya existe un producto con SKU '{sku}'.")
        if barcode and session.query(Product.id).filter(Product.barcode == barcode, Product.id != (product_id or 0)).first():
            raise ValueError(f"Ya existe un producto con código de barras '{barcode}'.")

        if product_id:
            product = session.query(Product).filter(Product.id == product_id).first()
            if not product:
                raise ValueError(f"Producto ID {product_id} inexistente.")
            if not is_weighable and product.stock is not None and product.stock != product.stock.to_integral_value():
                raise ValueError("Tiene stock fraccional: no puede dejar de ser pesable.")
            if to_decimal_money(product.price or 0) != price:
                # Paridad con la señal de Django (products.signals.log_price_change)
                session.add(PriceLog(product_id=product.id, old_price=product.price, new_price=price, user_id=user_id, date=utc_now()))
                session.add(ActivityLog(user_id=user_id, module="Productos",
                                        action=f"Cambio de precio: {name} (${product.price} -> ${price})"[:255]))
        else:
            product = Product(stock=Decimal('0.000'))
            session.add(product)

        product.name, product.sku, product.barcode, product.unit = name, sku, barcode, unit
        product.is_weighable, product.price, product.cost_price, product.tax_rate = is_weighable, price, cost, tax_rate
        product.min_stock, product.expiry_date = min_stock, expiry
        product.supplier_id = data.get("supplier_id") or None
        product.category_id = data.get("category_id") or None
        product.description = (data.get("description") or "").strip() or None
        session.flush()

        initial_stock = (data.get("initial_stock") or "").strip() if not product_id else ""
        if initial_stock:
            qty = validate_quantity(initial_stock, is_weighable)
            product.stock = qty
            session.add(InventoryMovement(product_id=product.id, quantity=qty, movement_type='IN', cost_price=cost,
                                          reference="Stock inicial", user_id=user_id, date=utc_now()))
        session.add(ActivityLog(user_id=user_id, module="Productos",
                                action=f"Producto {'editado' if product_id else 'creado'}: {name} (SKU: {sku})"[:255]))
        session.commit()
        return True, product.id
    except Exception as e:
        session.rollback()
        return False, str(e)
    finally:
        session.close()

def get_bi_stats():
    session = db.get_session()
    try:
        stats = {}
        
        # Ventas totales
        stats['total_revenue'] = to_decimal_money(session.query(func.sum(Sale.total_amount)).scalar() or 0)
        
        # Top productos (con is_weighable para mostrar kg o unidades)
        top = session.query(Product.name, Product.is_weighable, func.sum(SaleDetail.quantity).label('total'))\
            .join(SaleDetail, SaleDetail.product_id == Product.id).group_by(Product.id)\
            .order_by(func.sum(SaleDetail.quantity).desc()).limit(5).all()
        stats['top_products'] = [{"name": name, "is_weighable": bool(weighable), "quantity": to_decimal_qty(total or 0)}
                                 for name, weighable, total in top]
            
        # Productos críticos (bajo stock)
        stats['critical_stock'] = session.query(Product).filter(Product.stock <= Product.min_stock).count()
        
        # Ranking de proveedores (por cantidad de productos)
        stats['supplier_ranking'] = [(name, count) for name, count in session.query(Supplier.name, func.count(Product.id))
            .join(Product).group_by(Supplier.name).order_by(func.count(Product.id).desc()).limit(5).all()]
        return stats
    finally:
        session.close()


# --- Fase 5: operación completa desde el escritorio ---------------------------------------------

# products.models.LOSS_REASONS (desktop_tests verifica que coincidan)
LOSS_REASONS = {'EXP': 'Vencimiento', 'MER': 'Descarte / Merma', 'DAM': 'Rotura', 'INT': 'Consumo Interno', 'OTH': 'Otros'}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def _open_session_for(session, user_id):
    return session.query(CashSession).filter(CashSession.is_open == True, CashSession.user_id == user_id).first()

def _resolve_loss_reason(reason):
    """Código o etiqueta conocida -> (código, nota extra); texto libre -> ('OTH', texto)."""
    text = (reason or "").strip()
    if text.upper() in LOSS_REASONS:
        return text.upper(), ""
    for code, label in LOSS_REASONS.items():
        if text.casefold() == label.casefold():
            return code, ""
    if not text:
        raise ValueError("Indique el motivo de la baja.")
    return 'OTH', text

def register_shrinkage(product_id, quantity, reason, user_id=1, notes=""):
    """Baja / merma: descuenta stock valorizando al costo vigente. Devuelve (ok, mensaje, datos)."""
    session = db.get_session()
    try:
        product = session.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise ValueError(f"Producto ID {product_id} inexistente.")
        qty = validate_sale_quantity(quantity, product.is_weighable)
        stock = to_decimal_qty(product.stock or 0)
        if qty > stock:
            # Misma regla que la web: no se puede dar de baja más de lo que hay
            raise ValueError(f"Stock insuficiente para dar de baja {format_qty(qty, product.is_weighable)}: "
                             f"hay {format_qty(stock, product.is_weighable)}.")
        code, free_text = _resolve_loss_reason(reason)
        unit_cost = to_decimal_money(product.cost_price or 0)
        note = " · ".join(t for t in (free_text, (notes or "").strip()) if t) or None
        now = utc_now()
        loss = StockLoss(product_id=product.id, quantity=qty, reason=code, unit_cost=unit_cost, notes=note, user_id=user_id, date=now)
        session.add(loss)
        product.stock = stock - qty
        session.add(InventoryMovement(product_id=product.id, quantity=qty, movement_type='OUT', reference=f"BAJA: {code}",
                                      user_id=user_id, date=now))
        # Mismo texto que products.signals.log_stock_loss (la señal no corre desde SQLAlchemy)
        session.add(ActivityLog(user_id=user_id, module="Inventario", date=now,
                                action=f"Baja de stock: {product.name} ({format_qty(qty, product.is_weighable)}) - Motivo: {LOSS_REASONS[code]}"[:255],
                                details=note))
        session.flush()
        data = {"loss_id": loss.id, "product_id": product.id, "product_name": product.name, "quantity": qty,
                "unit_cost": unit_cost, "cost": to_decimal_money(qty * unit_cost), "stock_after": stock - qty,
                "reason": code, "reason_label": LOSS_REASONS[code]}
        session.commit()
        return True, f"Baja registrada: {product.name} -{format_qty(qty, product.is_weighable)} (${data['cost']}).", data
    except Exception as e:
        session.rollback()
        return False, str(e), {}
    finally:
        session.close()

def _customer_to_dict(c):
    return {"id": c.id, "full_name": c.full_name, "dni_cuit": c.dni_cuit, "phone": c.phone, "email": c.email,
            "address": c.address, "balance": to_decimal_money(c.balance or 0), "points": c.points or 0,
            "limite_credito": to_decimal_money(c.limite_credito or 0), "is_final_consumer": c.dni_cuit == FINAL_CONSUMER_DNI}

def get_customer(customer_id):
    session = db.get_session()
    try:
        c = session.query(Customer).filter(Customer.id == customer_id).first()
        return _customer_to_dict(c) if c else None
    finally:
        session.close()

def save_customer(customer_data):
    """Alta (sin 'id') o edición de cliente. El Consumidor Final conserva su DNI y límite 0 (bloqueo de fiado).

    customer_data: name, dni_cuit, phone, email, address, credit_limit. Devuelve (ok, mensaje, cliente).
    """
    session = db.get_session()
    try:
        customer_id = customer_data.get("id")
        name = (customer_data.get("name") or "").strip()
        if not name:
            raise ValueError("El nombre es obligatorio.")
        dni = (customer_data.get("dni_cuit") or "").strip() or None
        email = (customer_data.get("email") or "").strip() or None
        if email and not EMAIL_RE.match(email):
            raise ValueError(f"Email inválido: {email}")
        limit = to_decimal_money(customer_data.get("credit_limit") or 0)
        if limit < 0:
            raise ValueError("El límite de crédito no puede ser negativo.")

        customer = None
        if customer_id:
            customer = session.query(Customer).filter(Customer.id == customer_id).first()
            if not customer:
                raise ValueError(f"Cliente ID {customer_id} inexistente.")
            if customer.dni_cuit == FINAL_CONSUMER_DNI and (dni != FINAL_CONSUMER_DNI or limit != 0):
                raise ValueError("El Consumidor Final no puede cambiar su DNI ni tener límite de crédito (no se le puede fiar).")
        if dni == FINAL_CONSUMER_DNI and not (customer and customer.dni_cuit == FINAL_CONSUMER_DNI):
            raise ValueError(f"El DNI {FINAL_CONSUMER_DNI} está reservado para el Consumidor Final.")
        if dni and session.query(Customer.id).filter(Customer.dni_cuit == dni, Customer.id != (customer_id or 0)).first():
            raise ValueError(f"Ya existe un cliente con DNI/CUIT {dni}.")
        if not customer:
            # Recién ahora: agregarlo antes de las consultas haría un autoflush con el registro incompleto
            customer = Customer(balance=Decimal('0.00'), points=0, created_at=utc_now())
            session.add(customer)

        customer.full_name, customer.dni_cuit, customer.email, customer.limite_credito = name[:255], dni, email, limit
        customer.phone = (customer_data.get("phone") or "").strip()[:20] or None
        customer.address = (customer_data.get("address") or "").strip()[:255] or None
        session.flush()
        data = _customer_to_dict(customer)
        session.commit()
        return True, f"Cliente {'actualizado' if customer_id else 'creado'}: {name}.", data
    except Exception as e:
        session.rollback()
        return False, str(e), {}
    finally:
        session.close()

def register_debt_payment(customer_id, amount, payment_method_id, notes="", user_id=1):
    """Cobro de deuda de Cuenta Corriente: un único asiento CREDIT (igual que customers.views.customer_payment)
    e ingreso en la caja abierta del cajero (efectivo o digital). Devuelve (ok, mensaje, datos del recibo)."""
    session = db.get_session()
    try:
        customer = session.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            raise ValueError(f"Cliente ID {customer_id} inexistente.")
        balance = to_decimal_money(customer.balance or 0)
        if balance <= 0:
            raise ValueError(f"{customer.full_name} no tiene deuda pendiente.")
        amount = to_decimal_money(amount)
        if amount <= 0:
            raise ValueError("El monto debe ser mayor a cero.")
        if amount > balance:
            raise ValueError(f"El monto (${amount}) supera la deuda actual (${balance}).")
        pm = session.query(PaymentMethod).filter(PaymentMethod.id == payment_method_id, PaymentMethod.active == True).first()
        if not pm or pm.name == CURRENT_ACCOUNT_METHOD:
            raise ValueError("Elija un medio de pago válido (no Cuenta Corriente).")
        open_session = _open_session_for(session, user_id)
        if pm.name == CASH_METHOD and not open_session:
            raise ValueError("Abra la caja para recibir pagos en efectivo.")

        now = utc_now()
        payment = Payment(customer_id=customer.id, amount=amount, payment_method_id=pm.id, date=now,
                          notes=(notes or "").strip()[:255] or None, user_id=user_id)
        session.add(payment)
        session.flush()
        customer.balance = balance - amount
        session.add(CurrentAccount(customer_id=customer.id, amount=amount, entry_type='CREDIT', date=now,
                                   reference=f"Pago #{payment.id} ({pm.name})", balance_after=customer.balance))
        if open_session:
            _recalculate_cash_session(session, open_session)
        session.add(ActivityLog(user_id=user_id, module="Clientes", date=now,
                                action=f"Cobro de deuda #{payment.id}: {customer.full_name} ${amount} ({pm.name})"[:255]))
        data = {"payment_id": payment.id, "date": to_local(now), "customer": customer.full_name, "amount": amount,
                "method": pm.name, "balance_before": balance, "balance_after": balance - amount, "notes": payment.notes}
        session.commit()
        return True, f"Pago de ${amount} registrado. Saldo restante: ${data['balance_after']}.", data
    except Exception as e:
        session.rollback()
        return False, str(e), {}
    finally:
        session.close()

def get_customer_account_statement(customer_id):
    """Libro de Cuenta Corriente: ventas fiadas (DEBT), pagos y devoluciones (CREDIT), en hora local."""
    session = db.get_session()
    try:
        customer = session.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            raise ValueError(f"Cliente ID {customer_id} inexistente.")
        entries = [{
            "date": to_local(e.date), "type": e.entry_type, "reference": e.reference or "",
            "debit": to_decimal_money(e.amount) if e.entry_type == 'DEBT' else Decimal('0.00'),
            "credit": to_decimal_money(e.amount) if e.entry_type == 'CREDIT' else Decimal('0.00'),
            "balance_after": to_decimal_money(e.balance_after or 0),
        } for e in session.query(CurrentAccount).filter(CurrentAccount.customer_id == customer_id)
            .order_by(CurrentAccount.date, CurrentAccount.id)]
        return {"customer": _customer_to_dict(customer), "balance": to_decimal_money(customer.balance or 0),
                "total_debit": sum((e["debit"] for e in entries), Decimal('0.00')),
                "total_credit": sum((e["credit"] for e in entries), Decimal('0.00')), "entries": entries}
    finally:
        session.close()

def save_supplier(supplier_data):
    """Alta (sin 'id') o edición de proveedor. Devuelve (ok, mensaje, proveedor)."""
    session = db.get_session()
    try:
        supplier_id = supplier_data.get("id")
        name = (supplier_data.get("name") or "").strip()
        if not name:
            raise ValueError("El nombre es obligatorio.")
        email = (supplier_data.get("email") or "").strip() or None
        if email and not EMAIL_RE.match(email):
            raise ValueError(f"Email inválido: {email}")
        duplicate = session.query(Supplier.id).filter(func.lower(Supplier.name) == name.lower(),
                                                      Supplier.id != (supplier_id or 0)).first()
        if duplicate:
            raise ValueError(f"Ya existe un proveedor llamado '{name}'.")
        if supplier_id:
            supplier = session.query(Supplier).filter(Supplier.id == supplier_id).first()
            if not supplier:
                raise ValueError(f"Proveedor ID {supplier_id} inexistente.")
        else:
            supplier = Supplier(created_at=utc_now())
            session.add(supplier)
        supplier.name, supplier.email = name[:100], email
        supplier.phone = (supplier_data.get("phone") or "").strip()[:20] or None
        supplier.address = (supplier_data.get("address") or "").strip() or None
        session.flush()
        data = {"id": supplier.id, "name": supplier.name, "phone": supplier.phone, "email": supplier.email, "address": supplier.address}
        session.commit()
        return True, f"Proveedor {'actualizado' if supplier_id else 'creado'}: {name}.", data
    except Exception as e:
        session.rollback()
        return False, str(e), {}
    finally:
        session.close()

def get_recent_sales(day=None, limit=100):
    """Ventas de un día del negocio (por defecto hoy, hora local), de la más nueva a la más vieja."""
    from core.timeutils import local_day_bounds
    start, end = local_day_bounds(day or local_now().date())
    session = db.get_session()
    try:
        rows = []
        for sale, customer_name in session.query(Sale, Customer.full_name).outerjoin(Customer, Customer.id == Sale.customer_id)\
                .filter(Sale.date.between(start, end)).order_by(Sale.date.desc(), Sale.id.desc()).limit(limit):
            pays = session.query(PaymentMethod.name, SalePayment.amount).join(PaymentMethod, PaymentMethod.id == SalePayment.payment_method_id)\
                .filter(SalePayment.sale_id == sale.id).all()
            returned = session.query(func.sum(SaleReturn.total_amount)).filter(SaleReturn.sale_id == sale.id).scalar()
            rows.append({"id": sale.id, "date": to_local(sale.date), "customer": customer_name or "Consumidor Final",
                         "total": to_decimal_money(sale.total_amount), "returned": to_decimal_money(returned or 0),
                         "payments": " + ".join(f"{n} ${to_decimal_money(a)}" for n, a in pays)})
        return rows
    finally:
        session.close()

def _returned_by_product(session, sale_id):
    return {pid: to_decimal_qty(q) for pid, q in session.query(SaleReturnDetail.product_id, func.sum(SaleReturnDetail.quantity))
            .join(SaleReturn, SaleReturn.id == SaleReturnDetail.sale_return_id)
            .filter(SaleReturn.sale_id == sale_id).group_by(SaleReturnDetail.product_id)}

def _credit_portion(session, sale):
    """Lo fiado en la venta según SalePayment (o el total si es una venta vieja a Cuenta Corriente)."""
    pays = session.query(PaymentMethod.name, SalePayment.amount).join(PaymentMethod, PaymentMethod.id == SalePayment.payment_method_id)\
        .filter(SalePayment.sale_id == sale.id).all()
    if pays:
        return sum((to_decimal_money(a) for n, a in pays if n == CURRENT_ACCOUNT_METHOD), Decimal('0.00'))
    pm = session.query(PaymentMethod).filter(PaymentMethod.id == sale.payment_method_id).first()
    return to_decimal_money(sale.total_amount) if pm and pm.name == CURRENT_ACCOUNT_METHOD else Decimal('0.00')

def get_sale_return_info(sale_id):
    """Líneas de una venta con lo vendido, lo ya devuelto y lo que queda por devolver."""
    session = db.get_session()
    try:
        sale = session.query(Sale).filter(Sale.id == sale_id).first()
        if not sale:
            return None
        returned = _returned_by_product(session, sale_id)
        sold_by_product = {}
        lines = []
        for d, name, weighable in session.query(SaleDetail, Product.name, Product.is_weighable)\
                .outerjoin(Product, Product.id == SaleDetail.product_id).filter(SaleDetail.sale_id == sale_id).order_by(SaleDetail.id):
            qty = to_decimal_qty(d.quantity)
            # Lo ya devuelto de un producto se descuenta de sus líneas en orden
            already = min(qty, returned.get(d.product_id, Decimal('0')) - sold_by_product.get(d.product_id, Decimal('0')))
            already = max(already, Decimal('0.000'))
            sold_by_product[d.product_id] = sold_by_product.get(d.product_id, Decimal('0')) + already
            lines.append({"detail_id": d.id, "product_id": d.product_id, "name": name or "(producto eliminado)",
                          "is_weighable": bool(weighable), "price": to_decimal_money(d.price), "sold": qty,
                          "returned": already, "remaining": qty - already if d.product_id else Decimal('0.000')})
        customer = session.query(Customer).filter(Customer.id == sale.customer_id).first() if sale.customer_id else None
        return {"sale_id": sale.id, "date": to_local(sale.date), "total": to_decimal_money(sale.total_amount),
                "customer": customer.full_name if customer else "Consumidor Final", "credit_portion": _credit_portion(session, sale),
                "lines": lines}
    finally:
        session.close()

def register_sale_return(sale_id, items, reason="", refund_method_id=None, user_id=1):
    """Devolución parcial o total (mismas reglas que sales.views.sale_return).

    items: [{'detail_id', 'quantity'}]. Reintegra stock, acredita en Cuenta Corriente hasta lo fiado
    (core.stock_math.capped_return_credit) y el resto se devuelve por refund_method_id (Efectivo por
    defecto), descontándolo de la caja abierta. Devuelve (ok, mensaje, datos).
    """
    session = db.get_session()
    try:
        sale = session.query(Sale).filter(Sale.id == sale_id).first()
        if not sale:
            raise ValueError(f"Venta #{sale_id} inexistente.")
        details = {d.id: d for d in session.query(SaleDetail).filter(SaleDetail.sale_id == sale_id)}
        returned = _returned_by_product(session, sale_id)
        sold = {}
        for d in details.values():
            sold[d.product_id] = sold.get(d.product_id, Decimal('0')) + to_decimal_qty(d.quantity)

        lines, total, requested = [], Decimal('0.00'), {}
        for item in items:
            qty = to_decimal_qty(item.get("quantity") or 0)
            if qty == 0:
                continue
            detail = details.get(item["detail_id"])
            if not detail:
                raise ValueError(f"La línea {item['detail_id']} no pertenece a la venta #{sale_id}.")
            product = session.query(Product).filter(Product.id == detail.product_id).first() if detail.product_id else None
            if not product:
                raise ValueError("No se puede devolver un producto que fue eliminado del catálogo.")
            try:
                qty = validate_sale_quantity(qty, product.is_weighable)
            except ValueError as e:
                raise ValueError(f"{product.name}: {e}")
            requested[product.id] = requested.get(product.id, Decimal('0')) + qty
            remaining = sold[product.id] - returned.get(product.id, Decimal('0'))
            if requested[product.id] > remaining:
                raise ValueError(f"No se puede devolver más de lo vendido ({product.name}): quedan {format_qty(remaining, product.is_weighable)}.")
            amount = to_decimal_money(to_decimal_money(detail.price) * qty)
            total += amount
            lines.append((product, detail, qty, amount))
        if not lines:
            raise ValueError("Indique la cantidad a devolver de al menos un producto.")

        now = utc_now()
        sale_return = SaleReturn(sale_id=sale.id, reason=(reason or "").strip() or None, total_amount=total, user_id=user_id,
                                 date=now, refund_amount=Decimal('0.00'))
        session.add(sale_return)
        session.flush()
        for product, detail, qty, amount in lines:
            session.add(SaleReturnDetail(sale_return_id=sale_return.id, product_id=product.id, quantity=qty, price_at_return=detail.price))
            # Paridad con sales.signals.update_stock_on_return
            product.stock = to_decimal_qty(product.stock or 0) + qty
            session.add(InventoryMovement(product_id=product.id, quantity=qty, movement_type='IN',
                                          reference=f"Devolución #{sale_return.id}", user_id=user_id, date=now))

        credit = Decimal('0.00')
        if sale.customer_id:
            previous = [f"Devolución #{rid}" for (rid,) in session.query(SaleReturn.id)
                        .filter(SaleReturn.sale_id == sale.id, SaleReturn.id != sale_return.id)]
            already = session.query(func.sum(CurrentAccount.amount)).filter(
                CurrentAccount.customer_id == sale.customer_id, CurrentAccount.entry_type == 'CREDIT',
                CurrentAccount.reference.in_(previous)).scalar() if previous else None
            credit = capped_return_credit(total, _credit_portion(session, sale), already or 0)
            if credit > 0:
                customer = session.query(Customer).filter(Customer.id == sale.customer_id).first()
                customer.balance = to_decimal_money(customer.balance or 0) - credit
                session.add(CurrentAccount(customer_id=customer.id, amount=credit, entry_type='CREDIT', date=now,
                                           reference=f"Devolución #{sale_return.id}", balance_after=customer.balance))

        refund = total - credit
        refund_method = None
        if refund > 0:
            if refund_method_id:
                refund_method = session.query(PaymentMethod).filter(PaymentMethod.id == refund_method_id, PaymentMethod.active == True).first()
            else:
                refund_method = session.query(PaymentMethod).filter(PaymentMethod.name == CASH_METHOD).first()
            if not refund_method or refund_method.name == CURRENT_ACCOUNT_METHOD:
                raise ValueError("Elija un medio válido para reintegrar el dinero.")
            if refund_method.name == CASH_METHOD and not _open_session_for(session, user_id):
                raise ValueError("Abra la caja para reintegrar efectivo.")
            # Queda registrado en la devolución: la web y el escritorio lo descuentan del arqueo igual
            sale_return.refund_amount = refund
            sale_return.refund_method_id = refund_method.id
            _sync_open_cash_session(session, user_id)

        detail_text = ", ".join(f"{p.name} ({format_qty(q, p.is_weighable)})" for p, _, q, _ in lines)
        session.add(ActivityLog(user_id=user_id, module="Ventas", date=now, details=detail_text,
                                action=f"Devolución procesada #{sale_return.id} de Venta #{sale.id}"))
        data = {"return_id": sale_return.id, "sale_id": sale.id, "total": total, "credited": credit, "refund": refund,
                "refund_method": refund_method.name if refund_method else None}
        session.commit()
        msg = f"Devolución #{sale_return.id} registrada por ${total}."
        if credit > 0:
            msg += f" Acreditado en Cuenta Corriente: ${credit}."
        if refund > 0:
            msg += f" A reintegrar ({data['refund_method']}): ${refund}."
        return True, msg, data
    except Exception as e:
        session.rollback()
        return False, str(e), {}
    finally:
        session.close()


# --- Fase 6: copias de seguridad ------------------------------------------------------------------

def get_backup_status():
    """Carpeta de respaldos automáticos y los existentes (más nuevo primero), para la UI."""
    folder = backup_manager.backups_dir(db.db_path)
    return {"folder": folder, "keep": backup_manager.KEEP,
            "backups": [{"name": p.name, "size_kb": round(p.stat().st_size / 1024)} for p in backup_manager.list_backups(folder)]}

def create_manual_backup(dest_dir=None):
    """Copia ahora: en backups/ (con rotación) o en una carpeta externa elegida (ej. pendrive, sin rotación).
    Devuelve (ok, mensaje, {'path'})."""
    try:
        path = backup_manager.create_backup(db.db_path, dest_dir)
        if dest_dir is None:
            backup_manager.rotate_backups(backup_manager.backups_dir(db.db_path))
        return True, f"Copia de seguridad creada:\n{path}", {"path": path}
    except Exception as e:
        return False, f"No se pudo crear la copia de seguridad: {e}", {}

