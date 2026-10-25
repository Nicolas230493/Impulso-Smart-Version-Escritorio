"""Cálculos puros de stock y dinero compartidos por la app de escritorio y las vistas Django.

Sin dependencias de Django ni SQLAlchemy para poder importarse desde ambos lados.
"""
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

# Nombres y referencias de negocio que ambos lados deben escribir/leer igual
CASH_METHOD = "Efectivo"
CURRENT_ACCOUNT_METHOD = "Cuenta Corriente"
FINAL_CONSUMER_DNI = "00000000"
AUTO_ADJUST_TYPE = 'ADJ'  # movement_type es varchar(3) en Django: IN / OUT / ADJ
AUTO_ADJUST_REASON = "Ajuste automático por venta sin stock previo (Desposte/Mostrador)"

QTY_STEP = Decimal('0.001')
MONEY_STEP = Decimal('0.01')
ZERO_QTY = Decimal('0.000')

def _parse_decimal(val):
    if isinstance(val, bool) or val is None:
        raise ValueError(f"Valor numérico inválido: {val!r}")
    if isinstance(val, Decimal):
        num = val
    elif isinstance(val, int):
        num = Decimal(val)
    elif isinstance(val, float):
        num = Decimal(str(val))
    else:
        text = str(val).strip().replace(' ', '')
        if ',' in text and '.' in text:
            text = text.replace('.', '')  # "1.250,5" -> separador de miles + coma decimal
        text = text.replace(',', '.')
        try:
            num = Decimal(text)
        except InvalidOperation:
            raise ValueError(f"Valor numérico inválido: {val!r}")
    if not num.is_finite():
        raise ValueError(f"Valor numérico inválido: {val!r}")
    return num

def to_decimal_qty(val) -> Decimal:
    """'1,250' -> Decimal('1.250') (paso 0.001, ROUND_HALF_UP)."""
    return _parse_decimal(val).quantize(QTY_STEP, rounding=ROUND_HALF_UP)

def to_decimal_money(val) -> Decimal:
    """'1500,5' -> Decimal('1500.50') (paso 0.01, ROUND_HALF_UP)."""
    return _parse_decimal(val).quantize(MONEY_STEP, rounding=ROUND_HALF_UP)

def validate_quantity(val, is_weighable) -> Decimal:
    """Cantidad > 0; los productos no pesables solo admiten cantidades enteras."""
    qty = to_decimal_qty(val)
    if qty <= 0:
        raise ValueError("La cantidad debe ser mayor a cero.")
    if not is_weighable and qty != qty.to_integral_value():
        raise ValueError("Este producto se vende por unidad: ingrese una cantidad entera.")
    return qty

validate_sale_quantity = validate_quantity

def calculate_weighted_average_cost(stock, current_cost, incoming_qty, incoming_cost) -> Decimal:
    """Costo Promedio Ponderado. Con stock previo <= 0 el costo pasa a ser el entrante."""
    stock = to_decimal_qty(stock or 0)
    incoming_qty = to_decimal_qty(incoming_qty)
    incoming_cost = to_decimal_money(incoming_cost)
    if stock <= ZERO_QTY:
        return incoming_cost
    current_cost = to_decimal_money(current_cost or 0)  # producto sin costo cargado: cuenta como 0
    cpp = (stock * current_cost + incoming_qty * incoming_cost) / (stock + incoming_qty)
    return cpp.quantize(MONEY_STEP, rounding=ROUND_HALF_UP)

def capped_return_credit(return_total, credit_portion, already_credited):
    """Lo que una devolución acredita en Cuenta Corriente: nunca más de lo que se fió en esa venta,
    descontando lo ya acreditado por devoluciones anteriores (misma regla en web y escritorio)."""
    available = to_decimal_money(credit_portion or 0) - to_decimal_money(already_credited or 0)
    return max(Decimal('0.00'), min(to_decimal_money(return_total), available))

def format_qty(qty, is_weighable):
    """Pesables con 3 decimales (1.250 kg); unitarios enteros (12 u.)."""
    return f"{qty:.3f} kg" if is_weighable else f"{qty:.0f} u."
