from decimal import Decimal as D

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from sales.models import Sale, SalePayment
from .models import CashSession, PaymentMethod


class PaymentBreakdownReportTests(TestCase):
    """Los reportes suman desde SalePayment: una venta mixta no se atribuye entera a un medio."""

    def setUp(self):
        self.user = User.objects.create_superuser("tester", "t@t.com", "x")
        self.client.force_login(self.user)
        self.cash = PaymentMethod.objects.get(name="Efectivo")  # sembrados por core.0003
        self.transfer = PaymentMethod.objects.get(name="Transferencia / QR")
        self.cc = PaymentMethod.objects.get(name="Cuenta Corriente")
        self.session = CashSession.objects.create(user=self.user, initial_amount=D("500"))
        sale = Sale.objects.create(user=self.user, total_amount=D("5000"), payment_method=self.cash)
        for method, amount in ((self.cash, "2000"), (self.transfer, "1500"), (self.cc, "1500")):
            SalePayment.objects.create(sale=sale, payment_method=method, amount=D(amount))

    def test_cash_dashboard_uses_payment_portions(self):
        response = self.client.get(reverse("finance:cash_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.total_sales_cash, D("2000.00"))
        self.assertEqual(self.session.total_sales_digital, D("1500.00"))
        self.assertEqual(self.session.expected_final_amount, D("2500.00"))
        others = {p["payment_method__name"]: p["total"] for p in response.context["other_payments"]}
        self.assertEqual(others, {"Transferencia / QR": D("1500.00")})

    def test_export_cash_report_pdf(self):
        response = self.client.get(reverse("finance:export_cash_report", args=[self.session.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")


class NetProfitTests(TestCase):
    """SPEC-FIN-06: Ganancia Neta Real = Ventas netas - CMV - Gastos - Mermas valorizadas."""

    def setUp(self):
        from customers.models import Customer
        from products.models import InventoryMovement, Product, StockLoss
        from sales.models import SaleDetail, SaleReturn, SaleReturnDetail
        from .models import CashExpense
        self.user = User.objects.create_superuser("tester", "t@t.com", "x")
        self.session = CashSession.objects.create(user=self.user, initial_amount=D("0"))
        cash = PaymentMethod.objects.get(name="Efectivo")
        pollo = Product.objects.create(sku="P", name="Pollo", price=D("4000"), cost_price=D("2000"), stock=D("5"), is_weighable=True)
        coca = Product.objects.create(sku="C", name="Coca", price=D("1500"), cost_price=D("900"), stock=D("10"))
        sale = Sale.objects.create(user=self.user, total_amount=D("8000"), payment_method=cash)
        SalePayment.objects.create(sale=sale, payment_method=cash, amount=D("8000"))
        SaleDetail.objects.create(sale=sale, product=pollo, quantity=D("1.250"), price=D("4000"), cost_price_at_sale=D("2000"), subtotal=D("5000"))
        SaleDetail.objects.create(sale=sale, product=coca, quantity=D("2"), price=D("1500"), cost_price_at_sale=D("900"), subtotal=D("3000"))
        InventoryMovement.objects.create(product=pollo, quantity=D("0.250"), movement_type="ADJ", user=self.user,
                                         reference=f"Venta #{sale.id} - Ajuste automático por venta sin stock previo (Desposte/Mostrador)")
        ret = SaleReturn.objects.create(sale=sale, total_amount=D("1500"), user=self.user)
        SaleReturnDetail.objects.create(sale_return=ret, product=coca, quantity=D("1"), price_at_return=D("1500"))
        CashExpense.objects.create(session=self.session, amount=D("500"), description="Hielo")
        StockLoss.objects.create(product=pollo, quantity=D("0.350"), reason="DAM", unit_cost=D("2000"), user=self.user)
        StockLoss.objects.create(product=coca, quantity=D("1"), reason="EXP", user=self.user)  # sin costo: usa el vigente

    def test_session_summary(self):
        from .reports import get_profitability_summary
        s = get_profitability_summary(cash_session=self.session)
        self.assertEqual((s["gross_sales"], s["returns"], s["total_sales"]), (D("8000.00"), D("1500.00"), D("6500.00")))
        self.assertEqual(s["cmv"], D("3400.00"))            # 2500 + 1800 - 900 devuelto
        self.assertEqual(s["gross_profit"], D("3100.00"))
        self.assertEqual(s["expenses"], D("500.00"))
        self.assertEqual(s["shrinkage_cost"], D("1600.00"))  # 0.350*2000 + 1*900
        self.assertEqual(s["net_profit"], D("1000.00"))
        self.assertEqual(s["auto_adjustments_count"], 1)
        self.assertEqual(s["payments_breakdown"], {"Efectivo": D("8000.00")})

    def test_dashboard_shows_net_profit(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("finance:cash_dashboard"))
        self.assertEqual(response.context["profit_stats"]["net"], D("1000.00"))
        self.assertEqual(len(response.context["auto_adjustments"]), 1)


class TimezoneAndReportRegressionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("tz", "tz@t.com", "x")
        self.client.force_login(self.user)
        self.cash = PaymentMethod.objects.get(name="Efectivo")

    def test_business_time_zone(self):
        from django.conf import settings
        self.assertEqual(settings.TIME_ZONE, "America/Argentina/Buenos_Aires")
        self.assertTrue(settings.USE_TZ)

    def test_day_boundary_uses_local_day(self):
        # Bug: con TIME_ZONE='UTC' el día terminaba a las 21:00 hora argentina
        import datetime
        from django.utils import timezone
        today = timezone.localdate()
        local_midnight = timezone.make_aware(datetime.datetime.combine(today, datetime.time.min))
        before = Sale.objects.create(user=self.user, total_amount=D("1"), payment_method=self.cash)
        after = Sale.objects.create(user=self.user, total_amount=D("2"), payment_method=self.cash)
        # 22:30 de ayer (01:30 UTC de hoy) y 00:30 de hoy (03:30 UTC)
        Sale.objects.filter(pk=before.pk).update(date=local_midnight - datetime.timedelta(minutes=90))
        Sale.objects.filter(pk=after.pk).update(date=local_midnight + datetime.timedelta(minutes=30))
        self.assertEqual(list(Sale.objects.filter(date__date=today).values_list("pk", flat=True)), [after.pk])

    def test_whatsapp_report_of_open_session(self):
        # Bug: real_final_amount es None con la caja abierta -> TypeError
        session = CashSession.objects.create(user=self.user, initial_amount=D("0"))
        response = self.client.get(reverse("finance:whatsapp_report", args=[session.pk]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "todavía no fue cerrada")


class CashSessionWebRegressionTests(TestCase):
    """SPEC-FIN-07 en la web: reintegros de devoluciones, cobros digitales y esperado al cierre."""

    def setUp(self):
        from customers.models import Customer, Payment
        from products.models import Product
        from sales.models import SaleDetail
        self.user = User.objects.create_superuser("cajera", "c@t.com", "x")
        self.client.force_login(self.user)
        self.cash = PaymentMethod.objects.get(name="Efectivo")
        self.transfer = PaymentMethod.objects.get(name="Transferencia / QR")
        self.session = CashSession.objects.create(user=self.user, initial_amount=D("1000"))
        product = Product.objects.create(sku="W", name="Pollo", price=D("4000"), stock=D("5"), is_weighable=True)
        self.sale = Sale.objects.create(user=self.user, total_amount=D("2000"), payment_method=self.cash)
        SalePayment.objects.create(sale=self.sale, payment_method=self.cash, amount=D("2000"))
        self.detail = SaleDetail.objects.create(sale=self.sale, product=product, quantity=D("0.500"), price=D("4000"), subtotal=D("2000"))
        customer = Customer.objects.create(full_name="Deudor", dni_cuit="20999", balance=D("500"))
        Payment.objects.create(customer=customer, amount=D("500"), payment_method=self.transfer, user=self.user)

    def test_web_return_refund_is_recorded_and_discounted(self):
        from django.urls import reverse
        self.client.post(reverse("sales:sale_return", args=[self.sale.pk]),
                         {f"qty_{self.detail.id}": "0.100", "refund_method": self.cash.id})
        ret = self.sale.returns.get()
        self.assertEqual((ret.refund_amount, ret.refund_method), (D("400.00"), self.cash))
        self.client.get(reverse("finance:cash_dashboard"))
        self.session.refresh_from_db()
        self.assertEqual((self.session.total_sales_cash, self.session.total_sales_digital, self.session.expected_final_amount),
                         (D("1600.00"), D("500.00"), D("2600.00")))  # cobro digital incluido, reintegro descontado

    def test_close_recalculates_expected_without_opening_dashboard(self):
        # Antes: el esperado quedaba el de la última vez que se abrió el dashboard (acá, nunca -> 0)
        from django.urls import reverse
        response = self.client.post(reverse("finance:close_cash"), {"real_amount": "3000", "notes": ""}, follow=True)
        self.session.refresh_from_db()
        self.assertFalse(self.session.is_open)
        self.assertEqual(self.session.expected_final_amount, D("3000.00"))
        self.assertContains(response, "perfectamente")
