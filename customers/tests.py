from decimal import Decimal as D

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from finance.models import PaymentMethod
from sales.models import Sale
from .models import CurrentAccount, Customer, Payment


class CustomerPaymentRegressionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("tester", "t@t.com", "x")
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(full_name="Juan", dni_cuit="30111222", balance=D("1500.00"))
        self.cash = PaymentMethod.objects.get(name="Efectivo")

    def test_payment_form_lists_payment_methods(self):
        # Bug: la vista no pasaba payment_methods al template y el selector quedaba vacío
        response = self.client.get(reverse("customers:customer_payment", args=[self.customer.pk]))
        self.assertContains(response, f'value="{self.cash.id}"')
        self.assertNotIn("Cuenta Corriente", [m.name for m in response.context["payment_methods"]])

    def test_payment_creates_a_single_ledger_entry(self):
        # Bug: la vista y una señal creaban dos asientos CREDIT (uno con balance_after incorrecto)
        self.client.post(reverse("customers:customer_payment", args=[self.customer.pk]),
                         {"amount": "1000", "payment_method": self.cash.id, "notes": ""})
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.balance, D("500.00"))
        entries = CurrentAccount.objects.filter(customer=self.customer, entry_type="CREDIT")
        self.assertEqual(entries.count(), 1)
        self.assertEqual(entries.get().balance_after, D("500.00"))
        self.assertEqual(entries.get().reference, f"Pago #{Payment.objects.get().id} (Efectivo)")

    def test_statement_pdf_with_payments(self):
        # Bug: get_payment_method_display() no existe en un FK -> AttributeError
        Payment.objects.create(customer=self.customer, amount=D("100"), payment_method=self.cash, user=self.user)
        CurrentAccount.objects.create(customer=self.customer, amount=D("100"), entry_type="CREDIT", reference="Pago #1", balance_after=D("1400"))
        response = self.client.get(reverse("customers:export_statement_pdf", args=[self.customer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_delete_customer_with_sales_does_not_crash(self):
        # Bug: Sale.customer es PROTECT -> ProtectedError (error 500)
        Sale.objects.create(user=self.user, customer=self.customer, total_amount=D("10"), payment_method=self.cash)
        response = self.client.post(reverse("customers:customer_delete", args=[self.customer.pk]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Customer.objects.filter(pk=self.customer.pk).exists())
        self.assertContains(response, "tiene ventas registradas")
