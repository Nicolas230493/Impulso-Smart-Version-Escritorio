from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.utils import timezone
from django.db import models
from decimal import Decimal
from .models import CashSession, CashExpense, PaymentMethod
from sales.models import Sale, SaleDetail, SalePayment
from customers.models import Payment
from products.models import Purchase

from django.http import HttpResponse
from .utils import generate_cash_report_pdf
from .reports import get_profitability_summary
from .cash import recalculate_cash_session
import urllib.parse

@login_required
def export_cash_report(request, pk):
    session = get_object_or_404(CashSession, pk=pk)
    
    # Recalcular métricas para el reporte por si hubo cambios manuales
    start = session.start_date
    end = session.end_date if not session.is_open else timezone.now()
    
    # Desglose real por medio (incluye ventas con pago mixto)
    sales_summary = SalePayment.objects.filter(
        sale__user=session.user,
        sale__date__range=[start, end]
    ).values('payment_method__name').annotate(total=models.Sum('amount'))
    
    payments_summary = Payment.objects.filter(
        user=session.user,
        date__range=[start, end]
    ).values('payment_method__name').annotate(total=models.Sum('amount'))
    
    expenses = session.expenses.all()
    
    response = HttpResponse(content_type='application/pdf')
    filename = f"Arqueo_Caja_{session.id}.pdf"
    response['Content-Disposition'] = f'attachment; filename={filename}'
    
    # Updated generate_cash_report_pdf to handle the updated summaries
    generate_cash_report_pdf(response, session, sales_summary, payments_summary, expenses)
    return response

@staff_member_required
def cash_dashboard(request):
    # Filtrar por usuario actual para soporte de turnos
    active_session = CashSession.objects.filter(is_open=True, user=request.user).first()
    recent_sessions = CashSession.objects.filter(is_open=False).order_by('-end_date')[:5]
    
    # Ganancia Neta Real del día actual para todos los usuarios (Vista Gerencial)
    now = timezone.localtime()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    summary = get_profitability_summary(day_start, now)

    other_payments = []
    if active_session:
        # Métodos de pago
        cash_method = PaymentMethod.objects.filter(name='Efectivo').first()
        cc_method = PaymentMethod.objects.filter(name='Cuenta Corriente').first()

        # Misma fórmula que el escritorio (core.cash): ventas, cobros de deuda, reintegros y gastos
        recalculate_cash_session(active_session)

        # Otras métricas (Tarjetas, Transferencias) para información del cajero
        session_payments = SalePayment.objects.filter(
            sale__user=request.user,
            sale__date__gte=active_session.start_date
        )
        other_payments = session_payments.exclude(payment_method__in=[cash_method, cc_method]).values('payment_method__name').annotate(total=models.Sum('amount'))
        
    return render(request, 'finance/dashboard.html', {
        'session': active_session,
        'recent_sessions': recent_sessions,
        'other_payments': other_payments,
        'profit_stats': {
            'revenue': summary['total_sales'],
            'cost': summary['cmv'],
            'profit': summary['gross_profit'],
            'margin': summary['gross_margin_pct'],
            'expenses': summary['expenses'],
            'shrinkage': summary['shrinkage_cost'],
            'net': summary['net_profit'],
        },
        'auto_adjustments': summary['auto_adjustments'],
    })

@login_required
def open_cash(request):
    if request.method == 'POST':
        # Evitar múltiples cajas abiertas para el mismo usuario
        if CashSession.objects.filter(user=request.user, is_open=True).exists():
            messages.error(request, "Ya tienes una sesión de caja activa.")
            return redirect('finance:cash_dashboard')
            
        try:
            amount = Decimal(request.POST.get('amount', '0.00'))
            CashSession.objects.create(user=request.user, initial_amount=amount)
            messages.success(request, f"¡Caja abierta! Buen turno, {request.user.username}.")
        except Exception as e:
            messages.error(request, f"Error al abrir caja: {str(e)}")
            
    return redirect('finance:cash_dashboard')

@login_required
def add_expense(request):
    if request.method == 'POST':
        session = CashSession.objects.filter(is_open=True, user=request.user).first()
        if not session:
            messages.error(request, "Error: Debes tener una caja abierta para registrar egresos.")
            return redirect('finance:cash_dashboard')
            
        try:
            amount = Decimal(request.POST.get('amount', '0.00'))
            description = request.POST.get('description')
            CashExpense.objects.create(session=session, amount=amount, description=description)
            messages.success(request, "Egreso registrado correctamente.")
        except Exception as e:
            messages.error(request, f"Error al registrar egreso: {str(e)}")
            
    return redirect('finance:cash_dashboard')

def ensure_daily_backup_for_django():
    """Respaldo diario también al cerrar caja desde la web (ver core.backup_manager)."""
    from django.conf import settings
    from core.backup_manager import ensure_daily_backup
    try:
        ensure_daily_backup(settings.DATABASES['default']['NAME'])
    except Exception as e:  # un fallo del respaldo no debe impedir cerrar la caja
        print(f"Respaldo diario no realizado: {e}")

@login_required
def close_cash(request):
    if request.method == 'POST':
        session = CashSession.objects.filter(is_open=True, user=request.user).first()
        if not session:
            messages.error(request, "No se encontró una sesión activa para cerrar.")
            return redirect('finance:cash_dashboard')
            
        try:
            real_amount = Decimal(request.POST.get('real_amount', '0.00'))
            notes = request.POST.get('notes', '')
            
            # Esperado recalculado al momento del cierre (antes quedaba el de la última vez que se abrió el dashboard)
            session.end_date = timezone.now()
            recalculate_cash_session(session, save=False)
            session.real_final_amount = real_amount
            session.notes = notes
            session.is_open = False
            session.save()
            ensure_daily_backup_for_django()
            
            difference = real_amount - session.expected_final_amount
            if difference == 0:
                messages.success(request, "Caja cerrada perfectamente. ¡Todo coincide!")
            elif difference > 0:
                messages.info(request, f"Caja cerrada con SOBRANTE de ${difference}.")
            else:
                messages.warning(request, f"Caja cerrada con FALTANTE de ${abs(difference)}.")
                
        except Exception as e:
            messages.error(request, f"Error al cerrar caja: {str(e)}")
            
    return redirect('finance:cash_dashboard')

@staff_member_required
def fiscal_reports(request):
    month = request.GET.get('month', timezone.now().month)
    year = request.GET.get('year', timezone.now().year)
    
    # IVA Ventas
    sales = Sale.objects.filter(date__month=month, date__year=year).order_by('date')
    
    # IVA Compras
    purchases = Purchase.objects.filter(date__month=month, date__year=year).order_by('date')

    if 'export' in request.GET:
        import pandas as pd
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename=Reporte_Fiscal_{month}_{year}.xlsx'
        
        with pd.ExcelWriter(response, engine='openpyxl') as writer:
            # Hoja Ventas
            sales_data = []
            for s in sales:
                neto = s.total_amount - s.tax_amount
                sales_data.append({
                    'Fecha': timezone.localtime(s.date).strftime('%d/%m/%Y'),
                    'Comprobante': f'Ticket #{s.id}',
                    'Cliente': s.customer.full_name if s.customer else 'Consumidor Final',
                    'DNI/CUIT': s.customer.dni_cuit if s.customer else '---',
                    'Neto Gravado': neto,
                    'IVA Liquidado': s.tax_amount,
                    'Total': s.total_amount
                })
            pd.DataFrame(sales_data).to_excel(writer, sheet_name='IVA Ventas', index=False)
            
            purchases_data = []
            for p in purchases:
                total = p.total_amount
                iva = total - (total / Decimal('1.21'))
                neto = total - iva
                purchases_data.append({
                    'Fecha': timezone.localtime(p.date).strftime('%d/%m/%Y'),
                    'Proveedor': p.supplier.name,
                    'Factura': p.invoice_number,
                    'Neto Gravado': neto,
                    'IVA Crédito': iva,
                    'Total': total
                })
            pd.DataFrame(purchases_data).to_excel(writer, sheet_name='IVA Compras', index=False)
        return response

    return render(request, 'finance/fiscal_reports.html', {
        'sales': sales,
        'purchases': purchases,
        'selected_month': int(month),
        'selected_year': int(year)
    })

@login_required
def whatsapp_report(request, pk):
    session = get_object_or_404(CashSession, pk=pk)
    fecha = timezone.localtime(session.end_date).strftime('%d/%m/%Y') if session.end_date else timezone.now().strftime('%d/%m/%Y')
    if session.is_open or session.real_final_amount is None:
        messages.error(request, "La caja todavía no fue cerrada: no hay arqueo para informar.")
        return redirect('finance:cash_dashboard')
    total = session.real_final_amount + session.total_sales_digital
    efectivo = session.real_final_amount
    digital = session.total_sales_digital
    diferencia = session.real_final_amount - session.expected_final_amount
    
    estado_dif = f"Faltante: ${abs(diferencia)}" if diferencia < 0 else (f"Sobrante: ${diferencia}" if diferencia > 0 else "Sin diferencias")
    
    mensaje = f"📊 CIERRE IMPULSO SMART - {fecha} | Total: ${total} | Efec: ${efectivo} | Dig: ${digital} | {estado_dif}"
    link = f"https://wa.me/?text={urllib.parse.quote(mensaje)}"
    return redirect(link)
