from django.test import TestCase

from core.bootstrap import BASE_PAYMENT_METHODS, FINAL_CONSUMER_NAME, ensure_initial_data
from core.stock_math import FINAL_CONSUMER_DNI
from customers.models import Customer
from finance.models import PaymentMethod


class BootstrapTests(TestCase):
    """SPEC-BOOT-01: una base nueva siempre tiene medios de pago y Consumidor Final, sin duplicados."""

    def base_names(self):
        return {name for name, _, _ in BASE_PAYMENT_METHODS}

    def test_migrations_seed_initial_data(self):
        self.assertTrue(self.base_names() <= set(PaymentMethod.objects.values_list('name', flat=True)))
        cf = Customer.objects.get(dni_cuit=FINAL_CONSUMER_DNI)
        self.assertEqual(cf.limite_credito, 0)

    def test_empty_database_gets_seeded(self):
        PaymentMethod.objects.all().delete()
        Customer.objects.all().delete()
        created = ensure_initial_data()
        self.assertEqual(set(PaymentMethod.objects.values_list('name', flat=True)), self.base_names())
        self.assertEqual(PaymentMethod.objects.get(name="Efectivo").is_digital, False)
        self.assertEqual(PaymentMethod.objects.get(name="Tarjeta Débito").is_digital, True)
        self.assertEqual(Customer.objects.get(dni_cuit=FINAL_CONSUMER_DNI).full_name, FINAL_CONSUMER_NAME)
        self.assertIn(FINAL_CONSUMER_NAME, created)

    def test_idempotent_and_does_not_modify_existing(self):
        PaymentMethod.objects.filter(name="Efectivo").update(active=False)
        Customer.objects.filter(dni_cuit=FINAL_CONSUMER_DNI).update(full_name="CF Mostrador", limite_credito=0)
        before = PaymentMethod.objects.count()
        self.assertEqual(ensure_initial_data(), [])
        self.assertEqual(ensure_initial_data(), [])
        self.assertEqual(PaymentMethod.objects.count(), before)
        self.assertFalse(PaymentMethod.objects.get(name="Efectivo").active)
        self.assertEqual(Customer.objects.get(dni_cuit=FINAL_CONSUMER_DNI).full_name, "CF Mostrador")

    def test_existing_aliases_are_not_duplicated(self):
        # Bases anteriores usan "Tarjeta de Débito" / "Transferencia": no crear el equivalente
        PaymentMethod.objects.filter(name="Tarjeta Débito").update(name="Tarjeta de Débito")
        PaymentMethod.objects.filter(name="Transferencia / QR").update(name="transferencia")
        ensure_initial_data()
        names = set(PaymentMethod.objects.values_list('name', flat=True))
        self.assertNotIn("Tarjeta Débito", names)
        self.assertNotIn("Transferencia / QR", names)


class InitialAdminTests(TestCase):
    """admin/admin solo en una instalación sin usuarios; nunca pisa usuarios existentes."""

    def test_created_only_when_no_users(self):
        from django.contrib.auth.models import User
        from core.bootstrap import ensure_initial_admin
        self.assertTrue(ensure_initial_admin())
        self.assertTrue(User.objects.get(username="admin").check_password("admin"))
        self.assertFalse(ensure_initial_admin())
        self.assertEqual(User.objects.count(), 1)

    def test_existing_users_are_untouched(self):
        from django.contrib.auth.models import User
        from core.bootstrap import ensure_initial_admin
        admin = User.objects.create_superuser("admin", "a@a.com", "clave-segura")
        User.objects.create_user("cajero", password="x")
        admin.delete()  # admin borrado a propósito: no se recrea
        self.assertFalse(ensure_initial_admin())
        self.assertFalse(User.objects.filter(username="admin").exists())
        self.assertTrue(User.objects.get(username="cajero").check_password("x"))
