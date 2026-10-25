from sqlalchemy import create_engine, inspect, Column, Integer, String, ForeignKey, DateTime, Date, Numeric, Boolean, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.types import TypeDecorator
from decimal import Decimal
import sys
from pathlib import Path

# Django (USE_TZ=True) guarda las fechas en UTC sin offset en SQLite: el escritorio escribe igual
from core.timeutils import utc_now

Base = declarative_base()

class SqliteDecimal(TypeDecorator):
    """DecimalField de Django sobre SQLite (afinidad NUMERIC): se lee como Decimal cuantizado.

    SQLite no tiene decimal nativo; Numeric(asdecimal=True) avisa de posibles redondeos en cada
    consulta. Se lee el valor numérico y se cuantiza a los decimales del campo, igual que Django.
    """
    impl = Numeric
    cache_ok = True

    def __init__(self, precision, scale):
        super().__init__(precision=precision, scale=scale, asdecimal=False)
        self.step = Decimal(1).scaleb(-scale)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return str(Decimal(str(value)).quantize(self.step))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(str(value)).quantize(self.step)

def Money(precision=10, scale=2):
    return SqliteDecimal(precision, scale)

def Qty():
    return SqliteDecimal(10, 3)

class User(Base):
    """Solo lectura: los usuarios los administra Django (auth)."""
    __tablename__ = 'auth_user'
    id = Column(Integer, primary_key=True)
    password = Column(String(128))
    last_login = Column(DateTime)
    is_superuser = Column(Boolean)
    username = Column(String(150))
    first_name = Column(String(150))
    last_name = Column(String(150))
    email = Column(String(254))
    is_staff = Column(Boolean)
    is_active = Column(Boolean)
    date_joined = Column(DateTime)

class Category(Base):
    __tablename__ = 'products_category'
    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    description = Column(Text)

class Supplier(Base):
    __tablename__ = 'suppliers_supplier'
    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    phone = Column(String(20))
    email = Column(String(254))
    address = Column(Text)
    created_at = Column(DateTime, default=utc_now)

class Product(Base):
    __tablename__ = 'products_product'
    id = Column(Integer, primary_key=True)
    sku = Column(String(50), unique=True)
    barcode = Column(String(100), unique=True)
    name = Column(String(200))
    description = Column(Text)
    unit = Column(String(10), default='unidad')
    price = Column(Money())
    cost_price = Column(Money())
    stock = Column(Qty(), default=0)
    is_weighable = Column(Boolean, default=False)
    min_stock = Column(Qty(), default=5)
    tax_rate = Column(Money(5, 2))
    expiry_date = Column(Date)  # DateField en Django
    category_id = Column(Integer, ForeignKey('products_category.id'))
    supplier_id = Column(Integer, ForeignKey('suppliers_supplier.id'))
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

class PaymentMethod(Base):
    __tablename__ = 'finance_paymentmethod'
    id = Column(Integer, primary_key=True)
    name = Column(String(50))
    active = Column(Boolean, default=True)
    is_digital = Column(Boolean, default=False)

class Customer(Base):
    __tablename__ = 'customers_customer'
    id = Column(Integer, primary_key=True)
    full_name = Column(String(255))
    dni_cuit = Column(String(20), unique=True)
    phone = Column(String(20))
    email = Column(String(254))
    address = Column(String(255))
    balance = Column(Money(), default=0)
    points = Column(Integer, default=0)
    limite_credito = Column(Money(), default=0)
    created_at = Column(DateTime, default=utc_now)

class Sale(Base):
    __tablename__ = 'sales_sale'
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=utc_now)
    total_amount = Column(Money())
    tax_amount = Column(Money(), default=0)
    discount_amount = Column(Money(), default=0)
    points_redeemed = Column(Integer, default=0)
    points_discount = Column(Money(), default=0)
    promo_discount = Column(Money(), default=0)
    surcharge_amount = Column(Money(), default=0)
    customer_id = Column(Integer, ForeignKey('customers_customer.id'))
    payment_method_id = Column(Integer, ForeignKey('finance_paymentmethod.id'))
    payment_method_old = Column(String(10))  # Legado de una migración de Django
    user_id = Column(Integer, ForeignKey('auth_user.id'))

class SaleDetail(Base):
    __tablename__ = 'sales_saledetail'
    id = Column(Integer, primary_key=True)
    sale_id = Column(Integer, ForeignKey('sales_sale.id'))
    product_id = Column(Integer, ForeignKey('products_product.id'))
    quantity = Column(Qty())
    price = Column(Money())
    cost_price_at_sale = Column(Money(), default=0)
    tax_rate = Column(Money(5, 2), default=21.00)
    tax_amount = Column(Money(), default=0)
    subtotal = Column(Money())

class SalePayment(Base):
    __tablename__ = 'sales_salepayment'
    id = Column(Integer, primary_key=True)
    sale_id = Column(Integer, ForeignKey('sales_sale.id'))
    payment_method_id = Column(Integer, ForeignKey('finance_paymentmethod.id'))
    amount = Column(Money())

class SaleReturn(Base):
    __tablename__ = 'sales_salereturn'
    id = Column(Integer, primary_key=True)
    sale_id = Column(Integer, ForeignKey('sales_sale.id'))
    date = Column(DateTime, default=utc_now)
    reason = Column(Text)
    total_amount = Column(Money())
    user_id = Column(Integer, ForeignKey('auth_user.id'))
    refund_amount = Column(Money(), default=0)  # parte devuelta al cliente (no acreditada en Cuenta Corriente)
    refund_method_id = Column(Integer, ForeignKey('finance_paymentmethod.id'))

class SaleReturnDetail(Base):
    __tablename__ = 'sales_salereturndetail'
    id = Column(Integer, primary_key=True)
    sale_return_id = Column(Integer, ForeignKey('sales_salereturn.id'))
    product_id = Column(Integer, ForeignKey('products_product.id'))
    quantity = Column(Qty())
    price_at_return = Column(Money())

class Payment(Base):
    """Pago de deuda de Cuenta Corriente (customers.Payment)."""
    __tablename__ = 'customers_payment'
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey('customers_customer.id'))
    amount = Column(Money())
    payment_method_id = Column(Integer, ForeignKey('finance_paymentmethod.id'))
    payment_method_old = Column(String(10))
    date = Column(DateTime, default=utc_now)
    notes = Column(String(255))
    user_id = Column(Integer, ForeignKey('auth_user.id'))

class CurrentAccount(Base):
    __tablename__ = 'customers_currentaccount'
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey('customers_customer.id'))
    date = Column(DateTime, default=utc_now)
    amount = Column(Money())
    entry_type = Column(String(10)) # DEBT, CREDIT
    reference = Column(String(100))
    balance_after = Column(Money())

class PriceLog(Base):
    __tablename__ = 'products_pricelog'
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey('products_product.id'))
    old_price = Column(Money())
    new_price = Column(Money())
    user_id = Column(Integer, ForeignKey('auth_user.id'))
    date = Column(DateTime, default=utc_now)

class InventoryMovement(Base):
    __tablename__ = 'products_inventorymovement'
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey('products_product.id'))
    quantity = Column(Qty())
    movement_type = Column(String(3)) # IN, OUT, ADJ (ADJ también para desposte dinámico)
    reference = Column(String(100))
    date = Column(DateTime, default=utc_now)
    user_id = Column(Integer, ForeignKey('auth_user.id'))
    cost_price = Column(Money())  # Costo resultante (CPP) en ingresos
    sale_price = Column(Money())

class StockLoss(Base):
    __tablename__ = 'products_stockloss'
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey('products_product.id'))
    quantity = Column(Qty())
    reason = Column(String(3)) # EXP, DAM, INT, OTH
    unit_cost = Column(Money())  # Costo al momento de la baja (valoriza mermas)
    date = Column(DateTime, default=utc_now)
    notes = Column(Text)
    user_id = Column(Integer, ForeignKey('auth_user.id'))

class Purchase(Base):
    __tablename__ = 'products_purchase'
    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey('suppliers_supplier.id'))
    invoice_number = Column(String(50))
    date = Column(DateTime, default=utc_now)
    total_amount = Column(Money(), default=0)
    user_id = Column(Integer, ForeignKey('auth_user.id'))

class PurchaseDetail(Base):
    __tablename__ = 'products_purchasedetail'
    id = Column(Integer, primary_key=True)
    purchase_id = Column(Integer, ForeignKey('products_purchase.id'))
    product_id = Column(Integer, ForeignKey('products_product.id'))
    quantity = Column(Qty())
    cost_price = Column(Money())
    subtotal = Column(Money())

class PurchaseOrder(Base):
    __tablename__ = 'products_purchaseorder'
    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey('suppliers_supplier.id'))
    date = Column(DateTime, default=utc_now)
    status = Column(String(10), default='PENDING')
    total_amount = Column(Money(), default=0)
    notes = Column(Text)

class PurchaseOrderDetail(Base):
    __tablename__ = 'products_purchaseorderdetail'
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey('products_purchaseorder.id'))
    product_id = Column(Integer, ForeignKey('products_product.id'))
    quantity = Column(Qty())
    estimated_cost = Column(Money())

class ActivityLog(Base):
    __tablename__ = 'core_activitylog'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('auth_user.id'))
    action = Column(String(255))
    module = Column(String(100))
    date = Column('timestamp', DateTime, default=utc_now)  # Django lo llama "timestamp"
    details = Column(Text)
    ip_address = Column(String(39))

class CashSession(Base):
    __tablename__ = 'finance_cashsession'
    id = Column(Integer, primary_key=True)
    start_date = Column(DateTime, default=utc_now)
    end_date = Column(DateTime)
    initial_amount = Column(Money(), default=0)
    real_final_amount = Column(Money(), default=0)
    expected_final_amount = Column(Money(), default=0)
    total_sales_cash = Column(Money(), default=0)
    total_sales_digital = Column(Money(), default=0)
    total_expenses = Column(Money(), default=0)
    is_open = Column(Boolean, default=True)
    user_id = Column(Integer, ForeignKey('auth_user.id'))
    notes = Column(Text)

class CashExpense(Base):
    __tablename__ = 'finance_cashexpense'
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey('finance_cashsession.id'))
    amount = Column(Money())
    description = Column(String(255))
    date = Column(DateTime, default=utc_now)

# Columnas que deben existir para que el esquema SQLAlchemy coincida con las migraciones de Django
REQUIRED_COLUMNS = {
    'products_product': {'is_weighable'},
    'sales_salepayment': {'sale_id', 'payment_method_id', 'amount'},
    'products_stockloss': {'unit_cost'},
}

def default_db_path():
    # Misma ubicación que DATA_DIR en pos_system/settings.py (Django es dueño del esquema)
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent / 'db.sqlite3'
    return Path(__file__).resolve().parent / 'db.sqlite3'

class DatabaseManager:
    def __init__(self, db_path=None):
        self.db_path = Path(db_path) if db_path else default_db_path()
        self.engine = create_engine(f'sqlite:///{self.db_path}')
        self.Session = sessionmaker(bind=self.engine)

    def get_session(self):
        return self.Session()

    def missing_columns(self):
        """Devuelve {tabla: {columnas faltantes}}; vacío si el esquema está al día."""
        insp = inspect(self.engine)
        missing = {}
        for table, cols in REQUIRED_COLUMNS.items():
            existing = {c['name'] for c in insp.get_columns(table)} if insp.has_table(table) else set()
            if cols - existing:
                missing[table] = cols - existing
        return missing

    def backup(self):
        """Copia consistente antes de migrar, en backups/ (no entra en la rotación diaria)."""
        from core.backup_manager import create_backup
        if not self.db_path.exists() or self.db_path.stat().st_size == 0:
            return None  # instalación nueva: no hay nada que respaldar
        return create_backup(self.db_path, prefix="pre_migracion")

db = DatabaseManager()
