import json
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.stock_math import calculate_weighted_average_cost, format_qty, to_decimal_money, to_decimal_qty, validate_quantity
from suppliers.models import Supplier
from .models import InventoryMovement, Product, PurchaseDetail, PurchaseOrder, PurchaseOrderDetail, StockLoss


class StockMathTests(SimpleTestCase):
    def test_conversions(self):
        self.assertEqual(to_decimal_qty("1,250"), D("1.250"))
        self.assertEqual(to_decimal_qty("0.7505"), D("0.751"))
        self.assertEqual(to_decimal_money("10,005"), D("10.01"))
        for bad in ("abc", "", None, "nan", True):
            with self.assertRaises(ValueError):
                to_decimal_qty(bad)

    def test_validate_quantity(self):
        self.assertEqual(validate_quantity("0,750", True), D("0.750"))
        with self.assertRaises(ValueError):
            validate_quantity("1.5", False)
        with self.assertRaises(ValueError):
            validate_quantity("0", True)

    def test_weighted_average_cost(self):
        self.assertEqual(calculate_weighted_average_cost("10", "2000", "18.5", "2600"), D("2389.47"))
        self.assertEqual(calculate_weighted_average_cost("0", "2000", "5", "2600"), D("2600.00"))
        self.assertEqual(calculate_weighted_average_cost("-1.2", "7777", "5", "8000"), D("8000.00"))

    def test_format_qty(self):
        self.assertEqual(format_qty(D("1.25"), True), "1.250 kg")
        self.assertEqual(format_qty(D("12.000"), False), "12 u.")


class WebStockEntryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("tester", "t@t.com", "x")
        self.client.force_login(self.user)
        self.supplier = Supplier.objects.create(name="Avícola Test")
        self.pollo = Product.objects.create(sku="POLLO", barcode="779000001", name="Pollo", unit="kg", price=D("4000"),
                                            cost_price=D("2000"), stock=D("10.000"), is_weighable=True)
        self.coca = Product.objects.create(sku="COCA", name="Coca", price=D("1500"), cost_price=D("900"), stock=D("10"))

    def post_purchase(self, items):
        return self.client.post(reverse("products:purchase_create"), {
            "supplier_id": self.supplier.id, "invoice_number": "A-1", "items_data": json.dumps(items)})

    def test_purchase_accepts_decimal_qty_and_applies_cpp(self):
        self.post_purchase([{"product_id": self.pollo.id, "qty": "18.5", "cost": "2600"}])
        self.pollo.refresh_from_db()
        self.assertEqual(self.pollo.stock, D("28.500"))
        self.assertEqual(self.pollo.cost_price, D("2389.47"))
        detail = PurchaseDetail.objects.get(product=self.pollo)
        self.assertEqual(detail.quantity, D("18.500"))
        self.assertEqual(detail.purchase.total_amount, D("48100.00"))
        mov = InventoryMovement.objects.get(product=self.pollo, movement_type="IN")
        self.assertEqual((mov.quantity, mov.cost_price), (D("18.500"), D("2389.47")))

    def test_purchase_rejects_fraction_for_unit_product_atomically(self):
        self.post_purchase([{"product_id": self.pollo.id, "qty": "1", "cost": "1"},
                            {"product_id": self.coca.id, "qty": "1.5", "cost": "900"}])
        self.pollo.refresh_from_db()
        self.assertEqual((self.pollo.stock, self.pollo.cost_price), (D("10.000"), D("2000.00")))
        self.assertFalse(PurchaseDetail.objects.exists())

    def test_purchase_order_reception_applies_cpp(self):
        order = PurchaseOrder.objects.create(supplier=self.supplier, status="ORDERED")
        PurchaseOrderDetail.objects.create(order=order, product=self.pollo, quantity=D("5"), estimated_cost=D("2600"))
        self.client.post(reverse("products:update_purchase_order_status", args=[order.pk]), {"status": "RECEIVED"})
        self.pollo.refresh_from_db()
        self.assertEqual(self.pollo.stock, D("15.000"))
        self.assertEqual(self.pollo.cost_price, D("2200.00"))  # (10*2000 + 5*2600) / 15

    def test_scanner_accepts_decimal_and_keeps_cost(self):
        self.client.post(reverse("products:stock_entry_scanner"), {"barcode": "779000001", "quantity": "0.750"})
        self.pollo.refresh_from_db()
        self.assertEqual((self.pollo.stock, self.pollo.cost_price), (D("10.750"), D("2000.00")))

    def test_stock_loss_accepts_decimal(self):
        self.client.post(reverse("products:stock_loss_create"), {"product": self.pollo.id, "quantity": "0,350", "reason": "DAM"})
        self.pollo.refresh_from_db()
        self.assertEqual(self.pollo.stock, D("9.650"))
        self.assertEqual(StockLoss.objects.get().quantity, D("0.350"))


class ProductDeleteRegressionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("tester", "t@t.com", "x")
        self.client.force_login(self.user)

    def test_product_with_history_is_not_deleted(self):
        # Bug: el CASCADE borraba movimientos, compras y bajas (o daba error 500 si tenía devoluciones)
        product = Product.objects.create(sku="H", name="Con historia", price=D("10"), stock=D("1"))
        InventoryMovement.objects.create(product=product, quantity=D("1"), movement_type="IN", reference="x")
        response = self.client.post(reverse("products:product_delete", args=[product.pk]), follow=True)
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())
        self.assertContains(response, "No se puede eliminar")

    def test_product_without_history_is_deleted(self):
        product = Product.objects.create(sku="N", name="Nuevo", price=D("10"))
        self.client.post(reverse("products:product_delete", args=[product.pk]))
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())
