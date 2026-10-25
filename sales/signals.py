from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from .models import Sale, SaleDetail, SaleReturn, SaleReturnDetail
from core.models import ActivityLog
from customers.models import CurrentAccount
from products.models import InventoryMovement
from decimal import Decimal

@receiver(post_save, sender=Sale)
def handle_sale_effects(sender, instance, created, **kwargs):
    if created:
        # 1. Registrar Actividad
        ActivityLog.objects.create(
            user=instance.user,
            action=f"Venta confirmada #{instance.id} - Total: ${instance.total_amount}",
            module="Ventas"
        )

        # Puntos y Cuenta Corriente (solo la porción fiada) los aplica sales.services.register_sale:
        # aquí se duplicarían y no conocen el desglose de pagos mixtos.

# Devoluciones: el ActivityLog (con detalle) lo registra sales.views.sale_return y la
# Cuenta Corriente sales.services.credit_return_to_current_account.

@receiver(post_save, sender=SaleReturnDetail)
def update_stock_on_return(sender, instance, created, **kwargs):
    if created:
        # Reingresar stock
        product = instance.product
        product.stock += instance.quantity
        product.save()

        # Registrar movimiento de inventario
        InventoryMovement.objects.create(
            product=product,
            quantity=instance.quantity,
            movement_type='IN',
            reference=f"Devolución #{instance.sale_return.id}",
            user=instance.sale_return.user
        )
