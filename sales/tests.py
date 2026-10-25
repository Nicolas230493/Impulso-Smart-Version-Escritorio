from decimal import Decimal as D

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from customers.models import CurrentAccount, Customer
from finance.models import PaymentMethod
from products.models import Product
from .models import Sale, SaleDetail, SalePayment


class ReturnWithMixedPaymentTests(TestCase):
    """Una devolución acredita en Cuenta Corriente solo hasta lo fiado en la venta."""

    def setUp(self):
        self.user = User.objects.create_superuser("tester", "t@t.com", "x")
        self.client.force_login(self.user)
        self.cash = PaymentMethod.objects.get(name="Efectivo")  # sembrados por core.0003
        self.cc = PaymentMethod.objects.get(name="Cuenta Corriente")
        self.customer = Customer.objects.create(full_name="Juan", dni_cuit="30111222", balance=D("1500.00"))
        self.pollo = Product.objects.create(sku="POLLO", name="Pollo", unit="kg", price=D("4000"), stock=D("5"), is_weighable=True)

    def make_sale(self, payments, primary):
        total = sum(a for _, a in payments)
        sale = Sale.objects.create(user=self.user, customer=self.customer, total_amount=total, payment_method=primary)
        detail = SaleDetail.objects.create(sale=sale, product=self.pollo, quantity=D("1.250"), price=D("4000"), subtotal=total)
        for method, amount in payments:
            SalePayment.objects.create(sale=sale, payment_method=method, amount=amount)
        return sale, detail

    def do_return(self, sale, detail, qty):
        self.client.post(reverse("sales:sale_return", args=[sale.pk]), {"reason": "test", f"qty_{detail.id}": qty})

    def credits(self):
        return list(CurrentAccount.objects.filter(customer=self.customer, entry_type="CREDIT").values_list("amount", flat=True))

    def test_full_return_credits_only_the_credit_portion(self):
        sale, detail = self.make_sale([(self.cash, D("3500")), (self.cc, D("1500"))], self.cash)
        self.do_return(sale, detail, "1,250")
        self.assertEqual(sale.returns.get().total_amount, D("5000.00"))
        self.assertEqual(self.credits(), [D("1500.00")])
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.balance, D("0.00"))
        self.pollo.refresh_from_db()
        self.assertEqual(self.pollo.stock, D("6.250"))

    def test_partial_returns_are_capped_cumulatively(self):
        sale, detail = self.make_sale([(self.cash, D("3500")), (self.cc, D("1500"))], self.cash)
        self.do_return(sale, detail, "0.250")  # $1000 -> acredita 1000
        self.do_return(sale, detail, "0.500")  # $2000 -> solo quedan 500 fiados
        self.assertEqual(sorted(self.credits()), [D("500.00"), D("1000.00")])
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.balance, D("0.00"))

    def test_cash_only_sale_does_not_touch_current_account(self):
        sale, detail = self.make_sale([(self.cash, D("5000"))], self.cash)
        self.do_return(sale, detail, "1.250")
        self.assertEqual(self.credits(), [])

    def test_legacy_sale_without_payments_uses_sale_method(self):
        sale = Sale.objects.create(user=self.user, customer=self.customer, total_amount=D("5000"), payment_method=self.cc)
        detail = SaleDetail.objects.create(sale=sale, product=self.pollo, quantity=D("1.250"), price=D("4000"), subtotal=D("5000"))
        self.do_return(sale, detail, "0.500")
        self.assertEqual(self.credits(), [D("2000.00")])


class WebPOSTests(TestCase):
    """SPEC-WEB-02: el POS web vende pesables, aplica desposte dinámico y registra cobros mixtos."""

    def setUp(self):
        from finance.models import CashSession
        from products.models import InventoryMovement
        self.InventoryMovement = InventoryMovement
        self.user = User.objects.create_superuser("cajero", "c@t.com", "x")
        self.client.force_login(self.user)
        CashSession.objects.create(user=self.user, initial_amount=D("0"))
        self.cash = PaymentMethod.objects.get(name="Efectivo")
        self.transfer = PaymentMethod.objects.get(name="Transferencia / QR")
        self.cc = PaymentMethod.objects.get(name="Cuenta Corriente")
        self.customer = Customer.objects.create(full_name="Ana", dni_cuit="27111222", balance=D("0"), limite_credito=D("5000"))
        self.pollo = Product.objects.create(sku="POLLO", name="Pollo", unit="kg", price=D("4000"), cost_price=D("2000"),
                                            stock=D("0.300"), is_weighable=True)
        self.coca = Product.objects.create(sku="COCA", name="Coca", price=D("1500"), cost_price=D("900"), stock=D("10"))

    def post_sale(self, cart, payments=None, customer=None, method=None):
        data = {"cart_data": __import__("json").dumps(cart), "payment_method": (method or self.cash).id,
                "customer_id": (customer or self.customer).id, "discount_amount": "0", "surcharge_amount": "0",
                "points_redeemed": "0", "points_discount": "0"}
        if payments is not None:
            data["payments_data"] = __import__("json").dumps(payments)
        return self.client.post(reverse("sales:pos"), data, follow=True)

    def item(self, product, qty, price):
        return {"id": product.id, "qty": qty, "discounted_price": price, "original_price_at_sale": price}

    def test_weighable_sale_with_dynamic_auto_adjust(self):
        self.post_sale([self.item(self.pollo, "1.250", 4000)])
        sale = Sale.objects.get()
        self.assertEqual(sale.total_amount, D("5000.00"))
        self.assertEqual(sale.details.get().quantity, D("1.250"))
        self.pollo.refresh_from_db()
        self.assertEqual(self.pollo.stock, D("0.000"))
        movs = sorted(self.InventoryMovement.objects.filter(product=self.pollo).values_list("movement_type", "quantity"))
        self.assertEqual(movs, [("ADJ", D("0.950")), ("OUT", D("1.250"))])
        self.assertEqual(list(sale.payments.values_list("payment_method__name", "amount")), [("Efectivo", D("5000.00"))])

    def test_mixed_payment_with_rest_and_credit_portion(self):
        # $5000 pollo + $3000 coca = $8000: 2000 transferencia + 1500 fiado + resto efectivo
        self.post_sale([self.item(self.pollo, "1.250", 4000), self.item(self.coca, 2, 1500)], payments=[
            {"payment_method_id": self.transfer.id, "amount": "2000"},
            {"payment_method_id": self.cc.id, "amount": "1500.00"},
            {"payment_method_id": self.cash.id, "rest": True}])
        sale = Sale.objects.get()
        pays = dict(sale.payments.values_list("payment_method__name", "amount"))
        self.assertEqual(pays, {"Transferencia / QR": D("2000.00"), "Cuenta Corriente": D("1500.00"), "Efectivo": D("4500.00")})
        self.assertEqual(sale.payment_method, self.cash)  # medio principal = mayor monto
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.balance, D("1500.00"))  # solo la porción fiada
        self.assertEqual(self.customer.points, 8)
        self.assertEqual(CurrentAccount.objects.get(customer=self.customer).amount, D("1500.00"))

    def test_fraction_for_unit_product_is_rejected_atomically(self):
        response = self.post_sale([self.item(self.pollo, "0.5", 4000), self.item(self.coca, "1.5", 1500)])
        self.assertFalse(Sale.objects.exists())
        self.assertContains(response, "entera")
        self.pollo.refresh_from_db()
        self.assertEqual(self.pollo.stock, D("0.300"))

    def test_payments_exceeding_total_are_rejected(self):
        self.post_sale([self.item(self.coca, 1, 1500)], payments=[
            {"payment_method_id": self.transfer.id, "amount": "2000"}, {"payment_method_id": self.cash.id, "rest": True}])
        self.assertFalse(Sale.objects.exists())

    def test_final_consumer_cannot_take_credit_portion(self):
        cf = Customer.objects.get(dni_cuit="00000000")
        self.post_sale([self.item(self.coca, 1, 1500)], customer=cf, payments=[
            {"payment_method_id": self.cc.id, "amount": "500"}, {"payment_method_id": self.cash.id, "rest": True}])
        self.assertFalse(Sale.objects.exists())

    def test_pos_lists_products_without_stock(self):
        self.pollo.stock = D("0")
        self.pollo.save()
        response = self.client.get(reverse("sales:pos"))
        self.assertContains(response, 'data-weighable="1"')
        self.assertContains(response, "Pollo")


class SaleDocumentsRegressionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("tester2", "t2@t.com", "x")
        self.client.force_login(self.user)
        self.cash = PaymentMethod.objects.get(name="Efectivo")
        self.transfer = PaymentMethod.objects.get(name="Transferencia / QR")
        self.customer = Customer.objects.create(full_name="Ana", dni_cuit="27999888", phone="5493850000000")
        self.pollo = Product.objects.create(sku="POLLO-R", name="Pollo", price=D("4000"), stock=D("5"), is_weighable=True)
        self.sale = Sale.objects.create(user=self.user, customer=self.customer, total_amount=D("5000"), payment_method=self.cash)
        self.detail = SaleDetail.objects.create(sale=self.sale, product=self.pollo, quantity=D("1.250"), price=D("4000"), subtotal=D("5000"))
        SalePayment.objects.create(sale=self.sale, payment_method=self.cash, amount=D("3000"))
        SalePayment.objects.create(sale=self.sale, payment_method=self.transfer, amount=D("2000"))

    def test_thermal_ticket_pdf(self):
        # Bug: sale.get_payment_method_display() no existe (FK) y el POS web abre este ticket tras cada venta
        response = self.client.get(reverse("sales:export_thermal_ticket", args=[self.sale.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_documents_with_deleted_product(self):
        # SaleDetail.product queda en NULL si se borra el producto: no debe romper ticket ni WhatsApp
        SaleDetail.objects.filter(pk=self.detail.pk).update(product=None)
        self.assertEqual(self.client.get(reverse("sales:export_thermal_ticket", args=[self.sale.pk])).status_code, 200)
        response = self.client.get(reverse("sales:whatsapp_ticket", args=[self.sale.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("Producto%20eliminado", response["Location"])

    def test_return_of_deleted_product_shows_error(self):
        SaleDetail.objects.filter(pk=self.detail.pk).update(product=None)
        response = self.client.post(reverse("sales:sale_return", args=[self.sale.pk]), {f"qty_{self.detail.id}": "1"}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.sale.returns.exists())

    def test_return_is_logged_once(self):
        from core.models import ActivityLog
        self.client.post(reverse("sales:sale_return", args=[self.sale.pk]), {f"qty_{self.detail.id}": "0.250", "reason": "x"})
        self.assertEqual(ActivityLog.objects.filter(action__startswith="Devolución procesada").count(), 1)


class CumulativeReturnTests(TestCase):
    """Regresión: dos devoluciones no pueden sumar más de lo vendido (antes cada una solo se comparaba con lo vendido)."""

    def test_second_return_cannot_exceed_remaining(self):
        user = User.objects.create_superuser("acum", "a@t.com", "x")
        self.client.force_login(user)
        cash = PaymentMethod.objects.get(name="Efectivo")
        pollo = Product.objects.create(sku="AC", name="Pollo", price=D("4000"), stock=D("0"), is_weighable=True)
        sale = Sale.objects.create(user=user, total_amount=D("5000"), payment_method=cash)
        detail = SaleDetail.objects.create(sale=sale, product=pollo, quantity=D("1.250"), price=D("4000"), subtotal=D("5000"))
        url = reverse("sales:sale_return", args=[sale.pk])
        self.client.post(url, {f"qty_{detail.id}": "1.000"})
        response = self.client.post(url, {f"qty_{detail.id}": "1.000"}, follow=True)
        self.assertEqual(sale.returns.count(), 1)
        self.assertContains(response, "quedan 0.250")
        pollo.refresh_from_db()
        self.assertEqual(pollo.stock, D("1.000"))
