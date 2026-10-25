"""Inicialización zero-config: migraciones con respaldo y datos base mínimos.

Se usa desde la migración core.0003, el arranque de escritorio (login_gui) y el de la web (launcher).
Requiere Django configurado (django.setup()).
"""
from core.stock_math import CASH_METHOD, CURRENT_ACCOUNT_METHOD, FINAL_CONSUMER_DNI

# (nombre a crear, alias que se consideran el mismo medio, es digital)
BASE_PAYMENT_METHODS = [
    (CASH_METHOD, (), False),
    ("Transferencia / QR", ("Transferencia", "QR", "Mercado Pago"), True),
    ("Tarjeta Débito", ("Tarjeta de Débito", "Débito"), True),
    ("Tarjeta Crédito", ("Tarjeta de Crédito", "Crédito"), True),
    (CURRENT_ACCOUNT_METHOD, ("Fiado",), False),
]
FINAL_CONSUMER_NAME = "Consumidor Final"


def ensure_initial_data(apps=None):
    """Crea medios de pago base y el Consumidor Final si faltan. Idempotente: nunca duplica ni modifica.

    `apps` es el registro histórico cuando se llama desde una migración.
    """
    if apps is None:
        from django.apps import apps
    PaymentMethod = apps.get_model('finance', 'PaymentMethod')
    Customer = apps.get_model('customers', 'Customer')

    existing = {name.casefold() for name in PaymentMethod.objects.values_list('name', flat=True)}
    created = []
    for name, aliases, is_digital in BASE_PAYMENT_METHODS:
        if not existing & {n.casefold() for n in (name, *aliases)}:
            PaymentMethod.objects.create(name=name, is_digital=is_digital, active=True)
            created.append(name)

    _, customer_created = Customer.objects.get_or_create(
        dni_cuit=FINAL_CONSUMER_DNI,
        defaults={'full_name': FINAL_CONSUMER_NAME, 'limite_credito': 0},
    )
    if customer_created:
        created.append(FINAL_CONSUMER_NAME)
    return created


def ensure_initial_admin():
    """Solo en una instalación sin usuarios crea admin/admin (cambiar la clave desde la web).

    Nunca toca usuarios existentes ni recrea 'admin' si fue renombrado o borrado. Devuelve True si lo creó.
    """
    from django.contrib.auth.models import User
    if User.objects.exists():
        return False
    User.objects.create_superuser('admin', 'admin@impulso.com', 'admin')
    print("Instalación nueva: usuario inicial admin/admin creado. Cambie la contraseña.")
    return True


def prepare_database(db=None):
    """Aplica migraciones pendientes (respaldando antes la base con db.backup()) y asegura los datos base."""
    from django.core.management import call_command
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    if executor.migration_plan(executor.loader.graph.leaf_nodes()):
        backup = db.backup() if db else None
        if backup:
            print(f"Respaldo de base creado en: {backup}")
        call_command('migrate', interactive=False, verbosity=1)
    created = ensure_initial_data()
    if created:
        print(f"Datos base creados: {', '.join(created)}")
    if db:
        from core.backup_manager import ensure_daily_backup
        daily = ensure_daily_backup(db.db_path)
        if daily:
            print(f"Respaldo diario creado: {daily}")
    if db:
        missing = db.missing_columns()
        if missing:
            raise RuntimeError(f"Esquema de base desactualizado, faltan columnas: {missing}")
    return created
