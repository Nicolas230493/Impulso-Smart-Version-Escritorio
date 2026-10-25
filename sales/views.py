from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse, FileResponse
from products.models import Product, InventoryMovement, PriceList, ProductPrice
from customers.models import Customer
from finance.models import PaymentMethod, CashSession
from .models import Sale, SaleDetail, SalePayment, SaleReturn, SaleReturnDetail, Promotion
from .services import credit_return_to_current_account, register_sale, returnable_quantity
from core.stock_math import to_decimal_qty, to_decimal_money, validate_quantity
from core.models import ActivityLog
from django.utils import timezone
from .utils import generate_sale_pdf, generate_thermal_ticket, generate_total_sales_report
import json
from decimal import Decimal

@login_required
def export_sale_pdf(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename=Venta_{sale.id}.pdf'
    generate_sale_pdf(response, sale)
    return response

@login_required
def export_thermal_ticket(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    buffer = generate_thermal_ticket(sale)
    return FileResponse(buffer, as_attachment=False, filename=f"Ticket_{sale.id}.pdf")

@login_required
def export_consolidated_report(request):
    sales = Sale.objects.all().order_by('-date')
    buffer = generate_total_sales_report(sales)
    return FileResponse(buffer, as_attachment=True, filename="Reporte_Ventas_ImpulsoSmart.pdf")

@login_required
def pos_view(request):
    # Validar sesión de caja activa
    active_session = CashSession.objects.filter(user=request.user, is_open=True).exists()
    if not active_session:
        messages.warning(request, "Debes abrir una sesión de caja antes de realizar ventas.")
        return redirect('finance:cash_dashboard')

    # Sin filtro de stock: el desposte dinámico permite vender sin stock previo
    products = Product.objects.all().order_by('name')
    customers = Customer.objects.all()
    payment_methods = PaymentMethod.objects.filter(active=True)
    price_lists = PriceList.objects.filter(active=True)
    default_customer = Customer.objects.filter(dni_cuit='00000000').first()
    last_sale_id = request.session.pop('last_sale_id', None)
    
    # Promociones Activas
    today = timezone.localdate()
    active_promos = Promotion.objects.filter(active=True, start_date__lte=today, end_date__gte=today)
    
    # Preparar datos de promociones para JS
    promos_data = []
    for p in active_promos:
        promos_data.append({
            'id': p.id,
            'name': p.name,
            'type': p.promo_type,
            'discount': float(p.discount_percentage),
            'fixed_qty': p.fixed_qty,
            'fixed_price': float(p.fixed_price),
            'day': p.day_of_week,
            'product_ids': list(p.products.values_list('id', flat=True)),
            'category_ids': list(p.categories.values_list('id', flat=True))
        })

    if request.method == 'POST':
        try:
            cart = json.loads(request.POST.get('cart_data') or '[]')
            customer_id = request.POST.get('customer_id')
            customer = Customer.objects.get(id=customer_id) if customer_id else default_customer
            # Cobro mixto: payments_data; si no viene, el medio seleccionado cobra el total
            payments = json.loads(request.POST.get('payments_data') or '[]') or \
                [{'payment_method_id': request.POST.get('payment_method'), 'rest': True}]
            with transaction.atomic():
                result = register_sale(
                    user=request.user,
                    customer=customer,
                    cart=cart,
                    payments=payments,
                    discount=request.POST.get('discount_amount'),
                    surcharge=request.POST.get('surcharge_amount'),
                    points_redeemed=request.POST.get('points_redeemed'),
                    points_discount=request.POST.get('points_discount'),
                )
            sale = result['sale']
            request.session['last_sale_id'] = sale.id
            pays = " + ".join(f"{pm.name} ${amt}" for pm, amt in result['payments'])
            messages.success(request, f"Venta #{sale.id} registrada ({pays}).")
            if result['auto_adjustments']:
                messages.warning(request, "Desposte dinámico (stock ajustado automáticamente): " + ", ".join(
                    f"{a['product_name']} +{a['adjusted_qty']}" for a in result['auto_adjustments']))
        except Exception as e:
            messages.error(request, f"Error al procesar venta: {str(e)}")
        return redirect('sales:pos')
            
    # Preparar datos de precios especiales para el JS
    product_prices = {}
    for pp in ProductPrice.objects.filter(price_list__active=True):
        if pp.product_id not in product_prices:
            product_prices[pp.product_id] = {}
        product_prices[pp.product_id][pp.price_list_id] = float(pp.price)

    return render(request, 'sales/pos.html', {
        'products': products,
        'customers': customers,
        'payment_methods': payment_methods,
        'price_lists': price_lists,
        'default_customer': default_customer,
        'last_sale_id': last_sale_id,
        'product_prices_json': json.dumps(product_prices),
        'promotions_json': json.dumps(promos_data)
    })

@login_required
def sale_list(request):
    sales = Sale.objects.all().order_by('-date')
    return render(request, 'sales/sale_list.html', {'sales': sales})

@login_required
def whatsapp_ticket(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    if not sale.customer or not sale.customer.phone:
        messages.error(request, "El cliente no tiene un teléfono registrado.")
        return redirect('sales:sale_list')
    
    resumen = f"*Ticket Digital - Impulso Smart*\n"
    resumen += f"Venta #{sale.id} - {timezone.localtime(sale.date).strftime('%d/%m/%Y')}\n"
    resumen += f"--------------------------\n"
    for item in sale.details.all():
        name = item.product.name if item.product else "Producto eliminado"
        resumen += f"{name} x{item.quantity}: ${item.subtotal}\n"
    
    if sale.discount_amount > 0: resumen += f"Descuento: -${sale.discount_amount}\n"
    if sale.points_discount > 0: resumen += f"Canje Puntos: -${sale.points_discount}\n"
    
    resumen += f"--------------------------\n"
    resumen += f"*TOTAL: ${sale.total_amount}*\n"
    resumen += f"Gracias por su compra!"
    
    import urllib.parse
    link = f"https://wa.me/{sale.customer.phone}?text={urllib.parse.quote(resumen)}"
    return redirect(link)

@login_required
def sale_return(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    refund_methods = PaymentMethod.objects.filter(active=True).exclude(name='Cuenta Corriente')
    if request.method == 'POST':
        try:
            with transaction.atomic():
                total_return_amount = Decimal('0.00')
                sale_return = SaleReturn.objects.create(
                    sale=sale,
                    reason=request.POST.get('reason'),
                    total_amount=0,
                    user=request.user
                )
                
                return_details_text = []
                for detail in sale.details.all():
                    qty_to_return = to_decimal_qty(request.POST.get(f'qty_{detail.id}') or 0)
                    if qty_to_return > 0:
                        if detail.product is None:
                            raise Exception("No se puede devolver un producto que fue eliminado del catálogo.")
                        validate_quantity(qty_to_return, detail.product.is_weighable)
                        # Contra lo vendido menos lo ya devuelto antes (antes solo se comparaba con lo vendido)
                        remaining = returnable_quantity(sale, detail.product_id)
                        if qty_to_return > remaining:
                            raise Exception(f"No se puede devolver más de lo vendido ({detail.product.name}): quedan {remaining} por devolver")
                        
                        item_return_amount = to_decimal_money(detail.price * qty_to_return)
                        total_return_amount += item_return_amount
                        
                        SaleReturnDetail.objects.create(
                            sale_return=sale_return,
                            product=detail.product,
                            quantity=qty_to_return,
                            price_at_return=detail.price
                        )
                        return_details_text.append(f"{detail.product.name} ({qty_to_return})")
                
                if total_return_amount == 0:
                    raise Exception("Debe seleccionar al menos un producto para devolver")
                
                sale_return.total_amount = total_return_amount
                sale_return.save()
                # Solo se acredita en Cuenta Corriente hasta lo fiado en la venta
                credited = credit_return_to_current_account(sale_return)
                # El resto se devuelve al cliente: queda registrado para el arqueo (finance.cash / core.cash)
                refund = total_return_amount - credited
                if refund > 0:
                    method = refund_methods.filter(pk=request.POST.get('refund_method')).first() or refund_methods.filter(name='Efectivo').first()
                    if not method:
                        raise Exception("Elija un medio válido para reintegrar el dinero.")
                    sale_return.refund_amount = refund
                    sale_return.refund_method = method
                    sale_return.save(update_fields=['refund_amount', 'refund_method'])
                
                ActivityLog.objects.create(
                    user=request.user,
                    action=f"Devolución procesada #{sale_return.id} de Venta #{sale.id}",
                    module="Ventas",
                    details=", ".join(return_details_text)
                )
                
                msg = f"Devolución #{sale_return.id} procesada correctamente."
                if credited > 0:
                    msg += f" Se acreditaron ${credited} en la Cuenta Corriente del cliente."
                if refund > 0:
                    msg += f" A reintegrar ({sale_return.refund_method.name}): ${refund}."
                messages.success(request, msg)
                return redirect('sales:sale_list')
                
        except Exception as e:
            messages.error(request, f"Error al procesar devolución: {str(e)}")
            
    return render(request, 'sales/sale_return.html', {'sale': sale, 'refund_methods': refund_methods})
