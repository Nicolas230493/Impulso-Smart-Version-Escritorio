# Los asientos de Cuenta Corriente se registran explícitamente donde ocurren:
# - deuda de ventas: sales.services.register_sale / business_logic.process_sale (solo la porción fiada)
# - pagos: customers.views.customer_payment
# - devoluciones: sales.services.credit_return_to_current_account
# Antes había señales aquí que duplicaban el asiento del pago y una que nunca se ejecutaba.
