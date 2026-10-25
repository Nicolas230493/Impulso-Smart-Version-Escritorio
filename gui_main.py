import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
import tkinter.messagebox as messagebox
import tkinter.simpledialog
from tkinter import filedialog
import webbrowser
from whatsapp_utils import send_whatsapp_ticket, send_payment_reminder
from business_logic import (process_sale, open_cash_session, close_cash_session, add_cash_expense, get_bi_stats,
                            get_inventory_list, search_products_for_sale, find_product_by_code, get_payment_methods,
                            get_customers_list, get_suppliers_list, get_open_cash_session, register_purchase_or_stock_entry,
                            calculate_weighted_average_cost, validate_quantity, to_decimal_money, format_qty, CASH_METHOD)
from business_logic import (get_last_closed_cash_session, get_profitability_and_audit_summary, get_product, save_product,
                            get_categories_list, parse_local_date, local_now, UNIT_CHOICES, CURRENT_ACCOUNT_METHOD)
from business_logic import (register_shrinkage, LOSS_REASONS, get_customer, save_customer, register_debt_payment,
                            get_customer_account_statement, save_supplier, get_recent_sales, get_sale_return_info,
                            register_sale_return, get_backup_status, create_manual_backup)
from ticket_printer import (generate_sale_ticket_text, save_ticket, print_ticket, TICKET_WIDTHS, DEFAULT_WIDTH,
                            build_payment_receipt_text, save_payment_receipt)
from report_export import export_summary

NO_CUSTOMER = "— Sin cliente —"
NO_SUPPLIER = "— Sin proveedor (ingreso de stock) —"
SHORTCUTS_LEGEND = "[F2] Buscar | [F4] Peso/Cant | [Enter] Agregar | [F5] Cobrar Efectivo | [F6] Pago Mixto | [F8] Historial | [Supr] Quitar último | [Esc] Vaciar"
SHRINKAGE_REASONS = [LOSS_REASONS[c] for c in ('EXP', 'MER', 'DAM', 'INT')]
MONO_FONT = ("Courier New", 13)

class AfterCleanupMixin:
    """Cancela los after() pendientes de la ventana al destruirla.

    Si no, Tk ejecuta callbacks de una ventana ya destruida ('invalid command name ...'), por ejemplo
    el chequeo de DPI de CustomTkinter al pasar del login al Dashboard o un focus diferido de un diálogo.
    """
    def _pending_afters(self):
        if "_pending_after_ids" not in self.__dict__:
            self.__dict__["_pending_after_ids"] = set()
        return self.__dict__["_pending_after_ids"]

    def after(self, ms, func=None, *args):
        if func is None:
            return super().after(ms)
        holder = {}

        def run(*a):
            self._pending_afters().discard(holder.get("id"))
            return func(*a)
        holder["id"] = super().after(ms, run, *args)
        self._pending_afters().add(holder["id"])
        return holder["id"]

    def after_cancel(self, id):
        self._pending_afters().discard(id)
        super().after_cancel(id)

    def destroy(self):
        for after_id in list(self._pending_afters()):
            try:
                super().after_cancel(after_id)
            except tk.TclError:
                pass
        self._pending_afters().clear()
        super().destroy()

def app_of(widget):
    """DashboardApp dueña del widget (también desde diálogos Toplevel)."""
    w = widget
    while w is not None and not hasattr(w, "user_id"):
        w = w.master
    return w

def current_user_id(widget):
    app = app_of(widget)
    return app.user_id if app else 1

def entry_has_focus_with_text(widget):
    # Para no robarle Supr/Backspace a un campo donde el usuario está escribiendo
    w = widget.focus_get()
    return isinstance(w, tk.Entry) and bool(w.get())

# --- CONFIGURACIÓN GLOBAL ---
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class SidebarButton(ctk.CTkButton):
    def __init__(self, master, text, command, **kwargs):
        # Configuramos los parámetros predeterminados de forma segura
        params = {
            "anchor": "w",
            "height": 45,
            "corner_radius": 10,
            "fg_color": "transparent",
            "text_color": ("gray10", "gray90"),
            "hover_color": ("gray70", "gray30"),
            "font": ctk.CTkFont(size=14, weight="bold")
        }
        # Sobrescribimos con los valores pasados en kwargs si existen
        params.update(kwargs)
        
        super().__init__(master, text=text, command=command, **params)

# --- FRAMES MODULARES ---
# (Se mantienen DashboardFrame, InventoryFrame, SalesFrame, CustomersFrame, CashFrame, SuppliersFrame, ConfigFrame iguales)
class DashboardFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure((0, 1, 2), weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.refresh()

    def refresh(self):
        for w in self.winfo_children(): w.destroy()
        stats = get_bi_stats()
        
        ctk.CTkLabel(self, text="Dashboard & Analítica", font=ctk.CTkFont(size=28, weight="bold")).grid(row=0, column=0, columnspan=3, pady=20, padx=20, sticky="w")
        
        self.create_stat_card("Ventas Totales", f"${stats['total_revenue']:.2f}", 1, 0, "#4318ff")
        self.create_stat_card("Stock Crítico", f"{stats['critical_stock']} Prod.", 1, 1, "#e74c3c")
        self.create_stat_card("Ranking Proveedores", "Top 5 Listos", 1, 2, "#2ecc71")

        top_frame = ctk.CTkFrame(self)
        top_frame.grid(row=2, column=0, columnspan=3, sticky="nsew", padx=20, pady=20)
        ctk.CTkLabel(top_frame, text="Top 5 Productos Más Vendidos", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=10)
        for p in stats['top_products']:
            ctk.CTkLabel(top_frame, text=f"• {p['name']}: {format_qty(p['quantity'], p['is_weighable'])}", font=ctk.CTkFont(size=14)).pack(anchor="w", padx=40)

    def create_stat_card(self, title, value, row, col, color):
        card = ctk.CTkFrame(self, height=150, corner_radius=20, fg_color=("#ffffff", "#1e293b"))
        card.grid(row=row, column=col, padx=15, pady=15, sticky="nsew")
        card.grid_propagate(False)
        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=14, weight="bold"), text_color="gray").pack(pady=(20, 5))
        ctk.CTkLabel(card, text=str(value), font=ctk.CTkFont(size=32, weight="bold")).pack()
        ctk.CTkFrame(card, height=4, width=120, fg_color=color).pack(pady=10)

class InventoryFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.setup_ui()

    def setup_ui(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=10)
        ctk.CTkLabel(header, text="Gestión de Inventario", font=ctk.CTkFont(size=24, weight="bold")).pack(side="left")
        ctk.CTkButton(header, text="+ Nuevo Producto", fg_color=app_of(self).current_accent,
                      command=lambda: ProductDialog(self, on_done=self.load_data)).pack(side="right")
        ctk.CTkButton(header, text="✎ Editar seleccionado", fg_color="gray", command=self.edit_selected).pack(side="right", padx=10)
        ctk.CTkButton(header, text="- Registrar Baja / Merma", fg_color="#e67e22",
                      command=self.register_loss).pack(side="right", padx=(10, 0))
        ctk.CTkButton(header, text="+ Ingresar Mercadería / Compra", fg_color="#2ecc71", font=ctk.CTkFont(weight="bold"),
                      command=lambda: StockEntryDialog(self, on_done=self.load_data)).pack(side="right", padx=10)

        self.tree = ttk.Treeview(self, columns=("SKU", "Nombre", "Precio", "Costo", "Stock", "Vence"), show='headings')
        for col in self.tree["columns"]: self.tree.heading(col, text=col)
        self.tree.grid(row=1, column=0, sticky="nsew", padx=20, pady=10)
        self.tree.bind("<Double-1>", lambda e: self.edit_selected())
        self.load_data()

    def register_loss(self):
        selection = self.tree.selection()
        ShrinkageDialog(self, on_done=self.load_data, product_id=int(selection[0]) if selection else None)

    def edit_selected(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Editar producto", "Seleccione un producto de la lista (o haga doble clic sobre él).")
            return
        ProductDialog(self, on_done=self.load_data, product_id=int(selection[0]))

    def refresh(self):
        self.load_data()

    def load_data(self):
        for i in self.tree.get_children(): self.tree.delete(i)
        for p in get_inventory_list():
            vence = p['expiry_date'].strftime('%d/%m/%Y') if p['expiry_date'] else "---"
            self.tree.insert("", "end", iid=str(p['id']), values=(p['sku'], p['name'], f"${p['price']}", f"${p['cost_price']}", format_qty(p['stock'], p['is_weighable']), vence))

class ProductDialog(AfterCleanupMixin, ctk.CTkToplevel):
    """Alta / edición de producto. El stock de un producto existente entra por Ingreso de Mercadería (CPP)."""
    NONE = "— Ninguno —"

    def __init__(self, master, on_done, product_id=None):
        super().__init__(master)
        self.on_done = on_done
        self.product_id = product_id
        self.user_id = current_user_id(master)
        product = get_product(product_id) if product_id else None
        if product_id and not product:
            self.destroy()
            messagebox.showerror("Producto", "El producto ya no existe.")
            return
        self.title("Editar Producto" if product else "Nuevo Producto")
        self.geometry("520x680")
        self.suppliers = {s['name']: s['id'] for s in get_suppliers_list()}
        self.categories = {c['name']: c['id'] for c in get_categories_list()}

        form = ctk.CTkScrollableFrame(self)
        form.pack(fill="both", expand=True, padx=15, pady=15)
        form.grid_columnconfigure(1, weight=1)
        self.entries = {}
        fields = [("name", "Nombre *"), ("sku", "SKU (vacío = automático)"), ("barcode", "Código de barras"),
                  ("price", "Precio de venta $ *"), ("cost_price", "Costo $"), ("tax_rate", "IVA %"),
                  ("min_stock", "Stock mínimo"), ("expiry_date", "Vencimiento (dd/mm/aaaa)"), ("description", "Descripción")]
        if not product:
            fields.append(("initial_stock", "Stock inicial (opcional)"))
        for row, (key, label) in enumerate(fields):
            ctk.CTkLabel(form, text=label, anchor="w").grid(row=row, column=0, sticky="w", padx=5, pady=4)
            entry = ctk.CTkEntry(form)
            entry.grid(row=row, column=1, sticky="ew", padx=5, pady=4)
            self.entries[key] = entry
        row = len(fields)
        ctk.CTkLabel(form, text="Unidad", anchor="w").grid(row=row, column=0, sticky="w", padx=5, pady=4)
        self.unit_menu = ctk.CTkOptionMenu(form, values=UNIT_CHOICES)
        self.unit_menu.grid(row=row, column=1, sticky="ew", padx=5, pady=4)
        self.weighable = ctk.CTkSwitch(form, text="Pesable (se vende por peso: 0,750 kg)",
                                       command=lambda: self.weighable.get() and self.unit_menu.get() == "unidad" and self.unit_menu.set("kg"))
        self.weighable.grid(row=row + 1, column=0, columnspan=2, sticky="w", padx=5, pady=8)
        ctk.CTkLabel(form, text="Proveedor", anchor="w").grid(row=row + 2, column=0, sticky="w", padx=5, pady=4)
        self.supplier_menu = ctk.CTkOptionMenu(form, values=[self.NONE] + list(self.suppliers))
        self.supplier_menu.grid(row=row + 2, column=1, sticky="ew", padx=5, pady=4)
        ctk.CTkLabel(form, text="Categoría", anchor="w").grid(row=row + 3, column=0, sticky="w", padx=5, pady=4)
        self.category_menu = ctk.CTkOptionMenu(form, values=[self.NONE] + list(self.categories))
        self.category_menu.grid(row=row + 3, column=1, sticky="ew", padx=5, pady=4)

        if product:
            values = {"name": product['name'], "sku": product['sku'], "barcode": product['barcode'] or "",
                      "price": f"{product['price']:.2f}", "cost_price": f"{product['cost_price']:.2f}",
                      "tax_rate": f"{product['tax_rate']:.2f}", "min_stock": f"{product['min_stock']:f}",
                      "expiry_date": product['expiry_date'].strftime("%d/%m/%Y") if product['expiry_date'] else "",
                      "description": product['description']}
            self.unit_menu.set(product['unit'] if product['unit'] in UNIT_CHOICES else "unidad")
            if product['is_weighable']:
                self.weighable.select()
            self.supplier_menu.set(next((n for n, i in self.suppliers.items() if i == product['supplier_id']), self.NONE))
            self.category_menu.set(next((n for n, i in self.categories.items() if i == product['category_id']), self.NONE))
        else:
            values = {"tax_rate": "21", "min_stock": "5", "cost_price": "0"}
        for key, value in values.items():
            self.entries[key].insert(0, value)

        ctk.CTkButton(self, text="GUARDAR", height=45, fg_color="#2ecc71", font=ctk.CTkFont(weight="bold"),
                      command=self.save).pack(fill="x", padx=15, pady=(0, 15))
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(100, self.grab_set)
        self.after(150, self.entries["name"].focus_set)

    def save(self):
        data = {key: entry.get() for key, entry in self.entries.items()}
        data.update(unit=self.unit_menu.get(), is_weighable=bool(self.weighable.get()),
                    supplier_id=self.suppliers.get(self.supplier_menu.get()),
                    category_id=self.categories.get(self.category_menu.get()))
        ok, res = save_product(data, product_id=self.product_id, user_id=self.user_id)
        if not ok:
            messagebox.showerror("Producto", res, parent=self)
            return
        self.grab_release()
        self.destroy()
        self.on_done()

class FormDialog(AfterCleanupMixin, ctk.CTkToplevel):
    """Formulario simple: on_submit(data) -> (ok, mensaje, resultado); on_done(resultado) al guardar."""
    def __init__(self, master, title, fields, values, on_submit, on_done, readonly=(), note=""):
        super().__init__(master)
        self.title(title)
        self.geometry("480x" + str(170 + 46 * len(fields)))
        self.on_submit, self.on_done = on_submit, on_done
        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=15, pady=15)
        form.grid_columnconfigure(1, weight=1)
        self.entries = {}
        for row, (key, label) in enumerate(fields):
            ctk.CTkLabel(form, text=label, anchor="w").grid(row=row, column=0, sticky="w", padx=5, pady=4)
            entry = ctk.CTkEntry(form)
            entry.grid(row=row, column=1, sticky="ew", padx=5, pady=4)
            entry.insert(0, "" if values.get(key) is None else str(values[key]))
            entry.bind("<Return>", lambda e: self.save())
            if key in readonly:
                entry.configure(state="disabled")
            self.entries[key] = entry
        if note:
            ctk.CTkLabel(form, text=note, text_color="gray", wraplength=420, justify="left").grid(
                row=len(fields), column=0, columnspan=2, sticky="w", padx=5, pady=6)
        ctk.CTkButton(self, text="GUARDAR", height=45, fg_color="#2ecc71", font=ctk.CTkFont(weight="bold"),
                      command=self.save).pack(fill="x", padx=15, pady=(0, 15))
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(100, self.grab_set)
        self.after(150, lambda: self.entries[fields[0][0]].focus_set())

    def data(self):
        return {key: entry.get() for key, entry in self.entries.items()}

    def save(self):
        ok, msg, result = self.on_submit(self.data())
        if not ok:
            messagebox.showerror(self.title(), msg, parent=self)
            return
        self.grab_release()
        self.destroy()
        self.on_done(result)

CUSTOMER_FIELDS = [("name", "Nombre *"), ("dni_cuit", "DNI / CUIT"), ("phone", "Teléfono (WhatsApp)"),
                   ("email", "Email"), ("address", "Dirección"), ("credit_limit", "Límite de crédito $ (0 = sin límite)")]
SUPPLIER_FIELDS = [("name", "Nombre *"), ("phone", "Teléfono"), ("email", "Email"), ("address", "Dirección")]

def open_customer_dialog(master, on_done, customer=None):
    values = {}
    if customer:
        values = {"name": customer['full_name'], "dni_cuit": customer['dni_cuit'], "phone": customer['phone'],
                  "email": customer['email'], "address": customer['address'], "credit_limit": f"{customer['limite_credito']:.2f}"}
    final_consumer = bool(customer and customer['is_final_consumer'])

    def submit(data):
        if customer:
            data["id"] = customer['id']
        if final_consumer:  # los campos bloqueados no se envían editados
            data.update(dni_cuit=customer['dni_cuit'], credit_limit="0")
        return save_customer(data)
    return FormDialog(master, "Editar Cliente" if customer else "Nuevo Cliente", CUSTOMER_FIELDS, values, submit, on_done,
                      readonly=("dni_cuit", "credit_limit") if final_consumer else (),
                      note="Consumidor Final: no se le puede fiar (DNI y límite bloqueados)." if final_consumer else "")

def open_supplier_dialog(master, on_done, supplier=None):
    def submit(data):
        if supplier:
            data["id"] = supplier['id']
        return save_supplier(data)
    return FormDialog(master, "Editar Proveedor" if supplier else "Nuevo Proveedor", SUPPLIER_FIELDS, supplier or {}, submit, on_done)

class ShrinkageDialog(AfterCleanupMixin, ctk.CTkToplevel):
    """Baja / merma con el costo valorizado de la pérdida antes de confirmar."""
    def __init__(self, master, on_done, product_id=None):
        super().__init__(master)
        self.title("Registrar Baja / Merma")
        self.geometry("520x470")
        self.on_done = on_done
        self.user_id = current_user_id(master)
        self.products = {f"{p['name']} ({p['sku']})": p for p in get_inventory_list()}
        if not self.products:
            self.after(10, self.destroy)
            messagebox.showinfo("Baja / Merma", "No hay productos cargados.")
            return
        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=15, pady=15)
        form.grid_columnconfigure(1, weight=1)
        labels = ["Producto", "Stock actual", "Cantidad (kg o u.)", "Motivo", "Notas", ""]
        for row, label in enumerate(labels):
            ctk.CTkLabel(form, text=label, anchor="w").grid(row=row, column=0, sticky="w", padx=5, pady=6)
        self.product_menu = ctk.CTkOptionMenu(form, values=list(self.products), command=lambda _: self.update_preview())
        self.product_menu.grid(row=0, column=1, sticky="ew", padx=5)
        selected = next((k for k, p in self.products.items() if p['id'] == product_id), next(iter(self.products)))
        self.product_menu.set(selected)
        self.stock_label = ctk.CTkLabel(form, text="", anchor="w")
        self.stock_label.grid(row=1, column=1, sticky="w", padx=5)
        self.qty_entry = ctk.CTkEntry(form, placeholder_text="0,350")
        self.qty_entry.grid(row=2, column=1, sticky="ew", padx=5)
        self.qty_entry.bind("<KeyRelease>", lambda e: self.update_preview())
        self.qty_entry.bind("<Return>", lambda e: self.confirm())
        # Editable: se puede elegir o escribir el motivo
        self.reason = ctk.CTkComboBox(form, values=SHRINKAGE_REASONS)
        self.reason.set(SHRINKAGE_REASONS[0])
        self.reason.grid(row=3, column=1, sticky="ew", padx=5)
        self.notes = ctk.CTkEntry(form, placeholder_text="Opcional")
        self.notes.grid(row=4, column=1, sticky="ew", padx=5)
        self.cost_label = ctk.CTkLabel(form, text="", font=ctk.CTkFont(size=16, weight="bold"), text_color="#e74c3c")
        self.cost_label.grid(row=5, column=0, columnspan=2, sticky="w", padx=5, pady=12)
        ctk.CTkButton(self, text="CONFIRMAR BAJA", height=45, fg_color="#e67e22", font=ctk.CTkFont(weight="bold"),
                      command=self.confirm).pack(fill="x", padx=15, pady=(0, 15))
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_preview()
        self.after(100, self.grab_set)
        self.after(150, self.qty_entry.focus_set)

    def product(self):
        return self.products[self.product_menu.get()]

    def update_preview(self):
        p = self.product()
        self.stock_label.configure(text=f"{format_qty(p['stock'], p['is_weighable'])}  ·  costo ${p['cost_price']:.2f}")
        try:
            qty = validate_quantity(self.qty_entry.get(), p['is_weighable'])
            self.cost_label.configure(text=f"Costo valorizado de la pérdida: ${to_decimal_money(qty * p['cost_price']):.2f}")
        except ValueError:
            self.cost_label.configure(text="Costo valorizado de la pérdida: —")

    def confirm(self):
        ok, msg, _ = register_shrinkage(self.product()['id'], self.qty_entry.get(), self.reason.get(),
                                        user_id=self.user_id, notes=self.notes.get())
        if not ok:
            messagebox.showerror("Baja / Merma", msg, parent=self)
            return
        self.grab_release()
        self.destroy()
        self.on_done()
        messagebox.showinfo("Baja / Merma", msg)

class StatementDialog(AfterCleanupMixin, ctk.CTkToplevel):
    """Estado de cuenta: ventas fiadas, pagos y devoluciones."""
    def __init__(self, master, customer_id, on_pay):
        super().__init__(master)
        st = get_customer_account_statement(customer_id)
        c = st['customer']
        self.title(f"Estado de Cuenta - {c['full_name']}")
        self.geometry("760x520")
        ctk.CTkLabel(self, text=f"{c['full_name']}   ·   Saldo actual: ${st['balance']:.2f}",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color="#e74c3c" if st['balance'] > 0 else ("gray10", "gray90")).pack(padx=15, pady=(15, 5), anchor="w")
        lines = [f"{'Fecha':<17}{'Concepto':<32}{'Debe':>11}{'Haber':>11}{'Saldo':>12}", "-" * 83]
        for e in st['entries']:
            debit = f"{e['debit']:.2f}" if e['debit'] else ""
            credit = f"{e['credit']:.2f}" if e['credit'] else ""
            lines.append(f"{e['date'].strftime('%d/%m/%Y %H:%M'):<17}{e['reference'][:31]:<32}"
                         f"{debit:>11}{credit:>11}{e['balance_after']:>12.2f}")
        if not st['entries']:
            lines.append("Sin movimientos en Cuenta Corriente.")
        lines += ["-" * 83, f"{'Totales':<49}{st['total_debit']:>11.2f}{st['total_credit']:>11.2f}{st['balance']:>12.2f}"]
        box = ctk.CTkTextbox(self, font=ctk.CTkFont(family=MONO_FONT[0], size=12), wrap="none")
        box.pack(fill="both", expand=True, padx=15, pady=5)
        box.insert("1.0", "\n".join(lines))
        box.configure(state="disabled")
        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=15, pady=15)
        if st['balance'] > 0:
            ctk.CTkButton(btns, text="$ Cobrar Deuda", fg_color="#2ecc71",
                          command=lambda: (self.destroy(), on_pay(customer_id))).pack(side="left")
        ctk.CTkButton(btns, text="Cerrar", fg_color="gray", command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(100, self.grab_set)

class DebtPaymentDialog(AfterCleanupMixin, ctk.CTkToplevel):
    """Cobro de deuda con recibo en texto plano (ticket_printer)."""
    def __init__(self, master, customer_id, on_done):
        super().__init__(master)
        self.customer = get_customer(customer_id)
        self.on_done = on_done
        self.user_id = current_user_id(master)
        self.title(f"Cobrar Deuda - {self.customer['full_name']}")
        self.geometry("440x380")
        self.methods = {m['name']: m['id'] for m in get_payment_methods() if m['name'] != CURRENT_ACCOUNT_METHOD}
        ctk.CTkLabel(self, text=f"Deuda actual: ${self.customer['balance']:.2f}", font=ctk.CTkFont(size=20, weight="bold"),
                     text_color="#e74c3c").pack(pady=(20, 10))
        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="x", padx=20)
        form.grid_columnconfigure(1, weight=1)
        for row, label in enumerate(("Monto a cobrar $", "Medio de pago", "Notas")):
            ctk.CTkLabel(form, text=label, anchor="w").grid(row=row, column=0, sticky="w", padx=5, pady=6)
        self.amount = ctk.CTkEntry(form)
        self.amount.insert(0, f"{self.customer['balance']:.2f}")
        self.amount.grid(row=0, column=1, sticky="ew", padx=5)
        self.amount.bind("<Return>", lambda e: self.confirm())
        self.method = ctk.CTkOptionMenu(form, values=list(self.methods) or ["-"])
        if CASH_METHOD in self.methods:
            self.method.set(CASH_METHOD)
        self.method.grid(row=1, column=1, sticky="ew", padx=5)
        self.notes = ctk.CTkEntry(form, placeholder_text="Opcional")
        self.notes.grid(row=2, column=1, sticky="ew", padx=5)
        ctk.CTkButton(self, text="REGISTRAR PAGO", height=45, fg_color="#2ecc71", font=ctk.CTkFont(weight="bold"),
                      command=self.confirm).pack(fill="x", padx=20, pady=20)
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(100, self.grab_set)
        self.after(150, self.amount.focus_set)

    def confirm(self):
        ok, msg, data = register_debt_payment(self.customer['id'], self.amount.get(), self.methods.get(self.method.get()),
                                              notes=self.notes.get(), user_id=self.user_id)
        if not ok:
            messagebox.showerror("Cobro", msg, parent=self)
            return
        master = self.master
        self.grab_release()
        self.destroy()
        text = build_payment_receipt_text(data, app_of(master).ticket_width)
        path = save_payment_receipt(data['payment_id'], text)
        TicketPreviewDialog(master, msg, text, path, on_close=self.on_done)

class SalesHistoryDialog(AfterCleanupMixin, ctk.CTkToplevel):
    """Ventas del día: reimprimir ticket y registrar devoluciones."""
    def __init__(self, master, on_change):
        super().__init__(master)
        self.title("Historial de Ventas / Devoluciones")
        self.geometry("900x560")
        self.on_change = on_change
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=15, pady=(15, 5))
        ctk.CTkLabel(top, text="Día:").pack(side="left")
        self.day_entry = ctk.CTkEntry(top, width=120)
        self.day_entry.insert(0, local_now().strftime("%d/%m/%Y"))
        self.day_entry.pack(side="left", padx=8)
        self.day_entry.bind("<Return>", lambda e: self.load())
        ctk.CTkButton(top, text="Ver", width=70, command=self.load).pack(side="left")
        cols = ("N°", "Hora", "Cliente", "Total", "Devuelto", "Pagos")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=16)
        for col, width in zip(cols, (70, 70, 180, 100, 100, 330)):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=15, pady=5)
        self.tree.bind("<Double-1>", lambda e: self.reprint())
        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=15, pady=15)
        ctk.CTkButton(btns, text="Reimprimir ticket", command=self.reprint).pack(side="left")
        ctk.CTkButton(btns, text="Devolución...", fg_color="#e67e22", command=self.open_return).pack(side="left", padx=10)
        ctk.CTkButton(btns, text="Cerrar", fg_color="gray", command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self.load()
        self.after(100, self.grab_set)

    def load(self):
        try:
            day = parse_local_date(self.day_entry.get()) or local_now().date()
        except ValueError as e:
            messagebox.showerror("Historial", str(e), parent=self)
            return
        for i in self.tree.get_children(): self.tree.delete(i)
        for s in get_recent_sales(day):
            self.tree.insert("", "end", iid=str(s['id']), values=(s['id'], s['date'].strftime('%H:%M'), s['customer'],
                             f"${s['total']:.2f}", f"${s['returned']:.2f}" if s['returned'] else "", s['payments']))

    def selected_sale(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Historial", "Seleccione una venta.", parent=self)
            return None
        return int(selection[0])

    def reprint(self):
        sale_id = self.selected_sale()
        if sale_id:
            text = generate_sale_ticket_text(sale_id, app_of(self.master).ticket_width)
            TicketPreviewDialog(self, f"Reimpresión Venta #{sale_id}", text, save_ticket(sale_id, text), on_close=lambda: None)

    def open_return(self):
        sale_id = self.selected_sale()
        if sale_id:
            ReturnDialog(self, sale_id, on_done=self.after_return)

    def after_return(self):
        self.load()
        self.on_change()

class ReturnDialog(AfterCleanupMixin, ctk.CTkToplevel):
    """Devolución parcial o total; el reintegro no fiado sale de la caja del cajero."""
    def __init__(self, master, sale_id, on_done):
        super().__init__(master)
        self.info = get_sale_return_info(sale_id)
        self.on_done = on_done
        self.user_id = current_user_id(master)
        self.title(f"Devolución - Venta #{sale_id}")
        self.geometry("760x520")
        info = self.info
        header = f"Venta #{sale_id} · {info['date'].strftime('%d/%m/%Y %H:%M')} · {info['customer']} · Total ${info['total']:.2f}"
        if info['credit_portion'] > 0:
            header += f" · Fiado ${info['credit_portion']:.2f}"
        ctk.CTkLabel(self, text=header, font=ctk.CTkFont(weight="bold")).pack(padx=15, pady=(15, 5), anchor="w")
        grid = ctk.CTkScrollableFrame(self)
        grid.pack(fill="both", expand=True, padx=15, pady=5)
        grid.grid_columnconfigure(0, weight=1)
        for col, title in enumerate(("Producto", "Vendido", "Ya devuelto", "Precio", "A devolver")):
            ctk.CTkLabel(grid, text=title, text_color="gray").grid(row=0, column=col, sticky="w", padx=6)
        self.entries = {}
        for row, line in enumerate(info['lines'], start=1):
            w = line['is_weighable']
            for col, text in enumerate((line['name'], format_qty(line['sold'], w), format_qty(line['returned'], w), f"${line['price']:.2f}")):
                ctk.CTkLabel(grid, text=text, anchor="w").grid(row=row, column=col, sticky="w", padx=6, pady=2)
            entry = ctk.CTkEntry(grid, width=100, placeholder_text="0")
            entry.grid(row=row, column=4, padx=6, pady=2)
            entry.bind("<KeyRelease>", lambda e: self.update_total())
            if line['remaining'] <= 0:
                entry.configure(state="disabled")
            self.entries[line['detail_id']] = (entry, line)
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(bottom, text="Motivo:").pack(side="left")
        self.reason = ctk.CTkEntry(bottom, width=220)
        self.reason.pack(side="left", padx=8)
        self.methods = {m['name']: m['id'] for m in get_payment_methods() if m['name'] != CURRENT_ACCOUNT_METHOD}
        ctk.CTkLabel(bottom, text="Reintegrar en:").pack(side="left", padx=(10, 0))
        self.refund_method = ctk.CTkOptionMenu(bottom, values=list(self.methods) or ["-"], width=160)
        if CASH_METHOD in self.methods:
            self.refund_method.set(CASH_METHOD)
        self.refund_method.pack(side="left", padx=8)
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=15, pady=15)
        ctk.CTkButton(actions, text="Devolver todo lo pendiente", fg_color="gray", command=self.fill_all).pack(side="left")
        self.total_label = ctk.CTkLabel(actions, text="", font=ctk.CTkFont(size=16, weight="bold"))
        self.total_label.pack(side="left", padx=20)
        ctk.CTkButton(actions, text="CONFIRMAR DEVOLUCIÓN", fg_color="#e67e22", font=ctk.CTkFont(weight="bold"),
                      command=self.confirm).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_total()
        self.after(100, self.grab_set)

    def fill_all(self):
        for entry, line in self.entries.values():
            if line['remaining'] > 0:
                entry.delete(0, "end")
                entry.insert(0, format_qty(line['remaining'], line['is_weighable']).split()[0])
        self.update_total()

    def update_total(self):
        total = to_decimal_money(0)
        for entry, line in self.entries.values():
            try:
                total += to_decimal_money(line['price'] * validate_quantity(entry.get(), line['is_weighable']))
            except ValueError:
                pass
        self.total_label.configure(text=f"Total a devolver: ${total:.2f}")

    def confirm(self):
        items = [{"detail_id": detail_id, "quantity": entry.get()} for detail_id, (entry, _) in self.entries.items() if entry.get().strip()]
        ok, msg, _ = register_sale_return(self.info['sale_id'], items, reason=self.reason.get(),
                                          refund_method_id=self.methods.get(self.refund_method.get()), user_id=self.user_id)
        if not ok:
            messagebox.showerror("Devolución", msg, parent=self)
            return
        self.grab_release()
        self.destroy()
        self.on_done()
        messagebox.showinfo("Devolución", msg)

class StockEntryDialog(AfterCleanupMixin, ctk.CTkToplevel):
    """Ingreso de mercadería / compra a proveedor con vista previa del Costo Promedio Ponderado."""
    COLUMNS = ("Producto", "Stock actual", "Costo actual", "Cantidad", "Costo unit. $", "Nuevo CPP", "")

    def __init__(self, master, on_done):
        super().__init__(master)
        self.title("Ingreso de Mercadería / Compra")
        self.geometry("900x640")
        self.on_done = on_done
        self.user_id = current_user_id(master)
        self.lines = {}
        self._search_job = None
        self._next_row = 0  # fila de grid creciente: al quitar líneas no se pisan filas

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(15, 5))
        self.suppliers = {s['name']: s['id'] for s in get_suppliers_list()}
        self.supplier_menu = ctk.CTkOptionMenu(top, values=[NO_SUPPLIER] + list(self.suppliers), width=320)
        self.supplier_menu.pack(side="left")
        self.invoice_entry = ctk.CTkEntry(top, placeholder_text="N° de factura (opcional)", width=220)
        self.invoice_entry.pack(side="right")

        self.search_entry = ctk.CTkEntry(self, placeholder_text="Buscar producto o escanear código y presionar Enter...", height=40)
        self.search_entry.pack(fill="x", padx=20, pady=5)
        self.search_entry.bind("<KeyRelease>", self.schedule_search)
        self.search_entry.bind("<Return>", self.add_from_search)
        self.results = ctk.CTkScrollableFrame(self, height=110)
        self.results.pack(fill="x", padx=20)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=20, pady=(10, 0))
        self.lines_frame = ctk.CTkScrollableFrame(self)
        self.lines_frame.pack(fill="both", expand=True, padx=20, pady=5)
        for frame in (head, self.lines_frame):
            frame.grid_columnconfigure(0, weight=1)
        for col, title in enumerate(self.COLUMNS):
            ctk.CTkLabel(head, text=title, text_color="gray", width=110 if col else 200, anchor="w").grid(row=0, column=col, padx=4, sticky="w")

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=20, pady=15)
        self.total_label = ctk.CTkLabel(bottom, text="Total compra: $0.00", font=ctk.CTkFont(size=18, weight="bold"))
        self.total_label.pack(side="left")
        ctk.CTkButton(bottom, text="CONFIRMAR INGRESO", height=45, fg_color="#2ecc71", font=ctk.CTkFont(weight="bold"),
                      command=self.confirm).pack(side="right")

        self.bind("<Escape>", lambda e: self.destroy())
        self.render_results()
        self.after(100, self.grab_set)
        self.after(150, self.search_entry.focus_set)

    def schedule_search(self, event=None):
        if event is not None and event.keysym == "Return":
            return
        if self._search_job:
            self.after_cancel(self._search_job)
        self._search_job = self.after(250, self.render_results)

    def render_results(self):
        self._search_job = None
        for w in self.results.winfo_children(): w.destroy()
        for p in search_products_for_sale(self.search_entry.get())[:15]:
            ctk.CTkButton(self.results, anchor="w", fg_color="transparent", border_width=1, text_color=("gray10", "gray90"),
                          text=f"{p['name']}   ·   Stock {format_qty(p['stock'], p['is_weighable'])}   ·   Costo ${p['cost_price']}",
                          command=lambda item=p: self.add_line(item)).pack(fill="x", pady=1)

    def add_from_search(self, event=None):
        query = self.search_entry.get().strip()
        if not query:
            return "break"
        product = find_product_by_code(query)
        if not product:
            matches = search_products_for_sale(query)
            if len(matches) != 1:
                self.bell()
                return "break"
            product = matches[0]
        self.add_line(product)
        return "break"

    def add_line(self, p):
        if p['id'] in self.lines:
            self.lines[p['id']]['qty'].focus_set()
            return
        r = self._next_row
        self._next_row += 1
        widgets = [
            ctk.CTkLabel(self.lines_frame, text=p['name'], anchor="w", width=200),
            ctk.CTkLabel(self.lines_frame, text=format_qty(p['stock'], p['is_weighable']), width=110, anchor="w"),
            ctk.CTkLabel(self.lines_frame, text=f"${p['cost_price']:.2f}", width=110, anchor="w"),
        ]
        qty = ctk.CTkEntry(self.lines_frame, width=110, placeholder_text="18,500" if p['is_weighable'] else "12")
        cost = ctk.CTkEntry(self.lines_frame, width=110)
        cost.insert(0, f"{p['cost_price']:.2f}")
        cpp = ctk.CTkLabel(self.lines_frame, text="—", width=110, anchor="w", font=ctk.CTkFont(weight="bold"))
        remove = ctk.CTkButton(self.lines_frame, text="✕", width=30, fg_color="#e74c3c", command=lambda pid=p['id']: self.remove_line(pid))
        widgets += [qty, cost, cpp, remove]
        for col, w in enumerate(widgets):
            w.grid(row=r, column=col, padx=4, pady=2, sticky="w")
        for e in (qty, cost):
            e.bind("<KeyRelease>", lambda ev, pid=p['id']: self.update_preview(pid))
            e.bind("<Return>", lambda ev: (self.search_entry.focus_set(), "break")[1])
        self.lines[p['id']] = {"product": p, "qty": qty, "cost": cost, "cpp": cpp, "widgets": widgets}
        self.search_entry.delete(0, "end")
        self.render_results()
        qty.focus_set()

    def remove_line(self, pid):
        for w in self.lines.pop(pid)["widgets"]: w.destroy()
        self.update_total()

    def parse_line(self, line):
        p = line["product"]
        qty = validate_quantity(line["qty"].get(), p['is_weighable'])
        cost = to_decimal_money(line["cost"].get())
        if cost < 0:
            raise ValueError("El costo no puede ser negativo.")
        return qty, cost

    def update_preview(self, pid):
        line = self.lines[pid]
        p = line["product"]
        try:
            qty, cost = self.parse_line(line)
            new_cpp = calculate_weighted_average_cost(p['stock'], p['cost_price'], qty, cost)
            color = "#e74c3c" if new_cpp > p['cost_price'] else ("#2ecc71" if new_cpp < p['cost_price'] else ("gray10", "gray90"))
            line["cpp"].configure(text=f"${new_cpp:.2f}", text_color=color)
        except ValueError:
            line["cpp"].configure(text="—", text_color="gray")
        self.update_total()

    def update_total(self):
        total = to_decimal_money(0)
        for line in self.lines.values():
            try:
                qty, cost = self.parse_line(line)
                total += to_decimal_money(qty * cost)
            except ValueError:
                pass
        self.total_label.configure(text=f"Total compra: ${total:.2f}")

    def confirm(self):
        if not self.lines:
            messagebox.showwarning("Ingreso", "Agregue al menos un producto.", parent=self)
            return
        items = []
        for line in self.lines.values():
            try:
                qty, cost = self.parse_line(line)
            except ValueError as e:
                messagebox.showerror("Dato inválido", f"{line['product']['name']}: {e}", parent=self)
                line["qty"].focus_set()
                return
            items.append({"product_id": line["product"]['id'], "quantity": qty, "unit_cost": cost})
        supplier_id = self.suppliers.get(self.supplier_menu.get())
        ok, res = register_purchase_or_stock_entry(items, supplier_id=supplier_id, invoice_number=self.invoice_entry.get().strip() or None,
                                                   user_id=self.user_id)
        if not ok:
            messagebox.showerror("Error", res, parent=self)
            return
        title = f"Compra #{res['purchase_id']} registrada" if res['purchase_id'] else "Ingreso de stock registrado"
        summary = "\n".join(
            f"• {i['product_name']}: stock {i['stock_before']} → {i['stock_after']} | costo ${i['cost_before']} → ${i['new_cost']}"
            for i in res['items'])
        self.grab_release()
        self.destroy()
        self.on_done()
        messagebox.showinfo(title, f"{summary}\n\nTotal: ${res['total']}")

class TicketPreviewDialog(AfterCleanupMixin, ctk.CTkToplevel):
    """Vista previa del comprobante con botón Imprimir. Enter/Esc cierran y devuelven el foco al POS."""
    def __init__(self, master, header, ticket_text, ticket_path, on_close):
        super().__init__(master)
        self.title("Comprobante")
        self.ticket_path = ticket_path
        self.on_close = on_close
        width = max(len(l) for l in ticket_text.splitlines())
        self.geometry(f"{max(380, width * 10 + 80)}x640")

        ctk.CTkLabel(self, text=header, font=ctk.CTkFont(weight="bold"), justify="left").pack(padx=15, pady=(15, 5), anchor="w")
        box = ctk.CTkTextbox(self, font=ctk.CTkFont(family=MONO_FONT[0], size=MONO_FONT[1]), wrap="none")
        box.pack(fill="both", expand=True, padx=15, pady=5)
        box.insert("1.0", ticket_text)
        box.configure(state="disabled")
        ctk.CTkLabel(self, text=f"Guardado en: {ticket_path}", text_color="gray", font=ctk.CTkFont(size=11)).pack(padx=15)

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=15, pady=15)
        ctk.CTkButton(btns, text="Imprimir", height=40, command=self.print_ticket).pack(side="left", expand=True, fill="x", padx=(0, 5))
        ctk.CTkButton(btns, text="Cerrar [Enter]", height=40, fg_color="gray", command=self.close).pack(side="left", expand=True, fill="x", padx=(5, 0))
        for seq in ("<Return>", "<Escape>"):
            self.bind(seq, lambda e: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(100, self.grab_set)
        self.after(150, self.focus_force)

    def print_ticket(self):
        ok, msg = print_ticket(self.ticket_path)
        (messagebox.showinfo if ok else messagebox.showerror)("Impresión", msg, parent=self)

    def close(self):
        self.grab_release()
        self.destroy()
        self.on_close()

class MixedPaymentDialog(AfterCleanupMixin, ctk.CTkToplevel):
    """Cobro mixto: filas con monto editable y una última fila que toma el saldo restante."""
    def __init__(self, master, total, methods, on_confirm):
        super().__init__(master)
        self.title("Cobro Mixto")
        self.geometry("460x420")
        self.total = total
        self.methods = {m['name']: m['id'] for m in methods}
        self.on_confirm = on_confirm
        self.rows = []

        ctk.CTkLabel(self, text=f"TOTAL A COBRAR: ${total:.2f}", font=ctk.CTkFont(size=20, weight="bold")).pack(pady=15)
        self.rows_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.rows_frame.pack(fill="x", padx=20)

        names = list(self.methods)
        first = "Efectivo" if "Efectivo" in self.methods else names[0]
        self.add_row(first)

        rest_f = ctk.CTkFrame(self)
        rest_f.pack(fill="x", padx=20, pady=10)
        rest_default = next((n for n in names if n != first), first)
        self.rest_menu = ctk.CTkOptionMenu(rest_f, values=names, width=200)
        self.rest_menu.set(rest_default)
        self.rest_menu.pack(side="left", padx=10, pady=10)
        self.rest_label = ctk.CTkLabel(rest_f, text="", font=ctk.CTkFont(weight="bold"))
        self.rest_label.pack(side="right", padx=10)

        ctk.CTkButton(self, text="+ Agregar medio", fg_color="transparent", border_width=1,
                      command=lambda: self.add_row(first)).pack(pady=5)
        ctk.CTkButton(self, text="CONFIRMAR COBRO", height=50, fg_color="#2ecc71",
                      font=ctk.CTkFont(weight="bold"), command=self.confirm).pack(fill="x", padx=20, pady=15)
        self.update_rest()
        self.bind("<Return>", lambda e: self.confirm())
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(100, self.grab_set)

    def add_row(self, method_name):
        row = ctk.CTkFrame(self.rows_frame, fg_color="transparent")
        row.pack(fill="x", pady=3)
        menu = ctk.CTkOptionMenu(row, values=list(self.methods), width=200)
        menu.set(method_name)
        menu.pack(side="left", padx=10)
        entry = ctk.CTkEntry(row, placeholder_text="Monto $", width=140)
        entry.pack(side="right", padx=10)
        entry.bind("<KeyRelease>", lambda e: self.update_rest())
        self.rows.append((menu, entry))
        entry.focus_set()

    def entered_amounts(self, strict=False):
        amounts = []
        for menu, entry in self.rows:
            text = entry.get().strip()
            if not text:
                continue
            try:
                amount = to_decimal_money(text)
            except ValueError:
                if strict: raise
                continue
            if strict and amount <= 0:
                raise ValueError("Los montos deben ser mayores a cero.")
            amounts.append((menu.get(), amount))
        return amounts

    def remaining(self, amounts):
        return self.total - sum((a for _, a in amounts), to_decimal_money(0))

    def update_rest(self):
        rest = self.remaining(self.entered_amounts())
        self.rest_label.configure(text=f"Saldo: ${rest:.2f}", text_color="#e74c3c" if rest < 0 else ("gray10", "gray90"))

    def confirm(self):
        try:
            amounts = self.entered_amounts(strict=True)
        except ValueError as e:
            messagebox.showerror("Monto inválido", str(e), parent=self)
            return
        rest = self.remaining(amounts)
        if rest < 0:
            messagebox.showerror("Monto inválido", "Los montos ingresados superan el total.", parent=self)
            return
        if rest > 0:
            amounts.append((self.rest_menu.get(), rest))
        payments = [{"payment_method_id": self.methods[name], "amount": amt} for name, amt in amounts]
        self.grab_release()
        self.destroy()
        self.on_confirm(payments)

class SalesFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.cart = []
        self._search_job = None
        self.setup_ui()
        self.bind_shortcuts()

    def setup_ui(self):
        left_panel = ctk.CTkFrame(self, fg_color="transparent")
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(20, 10), pady=20)
        
        search_row = ctk.CTkFrame(left_panel, fg_color="transparent")
        search_row.pack(fill="x", pady=(0, 15))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self.on_search)
        self.search_entry = ctk.CTkEntry(search_row, placeholder_text="Escanear código o buscar nombre... [F2]", 
                                         textvariable=self.search_var, height=45)
        self.search_entry.pack(side="left", fill="x", expand=True)
        # Cantidad o peso a agregar: acepta "0.750" o "0,750"
        self.qty_entry = ctk.CTkEntry(search_row, placeholder_text="Cant. / Kg", width=110, height=45)
        self.qty_entry.pack(side="right", padx=(10, 0))
        self.qty_entry.insert(0, "1")
        self.search_entry.bind("<Return>", lambda e: self.add_from_search(first_match=False))
        self.qty_entry.bind("<Return>", lambda e: self.add_from_search(first_match=True))

        ctk.CTkLabel(left_panel, text=SHORTCUTS_LEGEND, text_color="gray", font=ctk.CTkFont(size=11)).pack(side="bottom", fill="x", pady=(8, 0))
        self.status_label = ctk.CTkLabel(left_panel, text="", text_color="#e67e22", anchor="w")
        self.status_label.pack(side="bottom", fill="x")

        self.prod_scroll = ctk.CTkScrollableFrame(left_panel)
        self.prod_scroll.pack(fill="both", expand=True)
        self.render_products()

        self.right_panel = ctk.CTkFrame(self, corner_radius=20, fg_color=("#f4f7fe", "#111c44"))
        self.right_panel.grid(row=0, column=1, sticky="nsew", padx=(10, 20), pady=20)
        
        ctk.CTkLabel(self.right_panel, text="Detalle de Venta", font=ctk.CTkFont(size=20, weight="bold")).pack(pady=20)
        self.cart_container = ctk.CTkScrollableFrame(self.right_panel, fg_color="transparent")
        self.cart_container.pack(fill="both", expand=True, padx=10)

        self.total_label = ctk.CTkLabel(self.right_panel, text="TOTAL: $0.00", font=ctk.CTkFont(size=28, weight="bold"))
        self.total_label.pack(pady=20)

        # Cliente (necesario para fiar en Cuenta Corriente)
        self.customer_menu = ctk.CTkOptionMenu(self.right_panel, values=[NO_CUSTOMER], height=36)
        self.customer_menu.pack(fill="x", padx=20, pady=5)
        self.load_customers()

        # Cobro rápido: un clic por medio de pago, o cobro mixto
        ctk.CTkLabel(self.right_panel, text="Cobrar con:", text_color="gray").pack(pady=(10, 0))
        self.payment_methods = get_payment_methods()
        quick = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        quick.pack(fill="x", padx=20, pady=5)
        quick.grid_columnconfigure((0, 1), weight=1)
        for i, m in enumerate(self.payment_methods):
            ctk.CTkButton(quick, text=m['name'], height=40, fg_color="#2ecc71" if m['name'] == "Efectivo" else None,
                          command=lambda mid=m['id']: self.quick_pay(mid)).grid(row=i // 2, column=i % 2, padx=3, pady=3, sticky="ew")

        ctk.CTkButton(self.right_panel, text="Historial / Devoluciones [F8]", height=36, fg_color="gray",
                      command=self.open_history).pack(side="bottom", fill="x", padx=20, pady=(0, 10))
        ctk.CTkButton(self.right_panel, text="PAGO MIXTO", height=50, font=ctk.CTkFont(weight="bold"),
                      fg_color="#8e44ad", command=self.open_mixed_payment).pack(fill="x", padx=20, pady=10)

    def refresh(self):
        self.load_customers()
        self.render_products(self.search_var.get())

    def load_customers(self):
        self.customers = {f"{c['full_name']} ({c['dni_cuit'] or 's/DNI'})": c['id'] for c in get_customers_list()}
        current = self.customer_menu.get()
        self.customer_menu.configure(values=[NO_CUSTOMER] + list(self.customers))
        self.customer_menu.set(current if current in self.customers else NO_CUSTOMER)

    def bind_shortcuts(self):
        top = self.winfo_toplevel()
        shortcuts = {
            "<F2>": self.focus_search,
            "<F4>": self.focus_qty,
            "<F5>": self.quick_pay_cash,
            "<F12>": self.quick_pay_cash,
            "<F6>": self.open_mixed_payment,
            "<F8>": self.open_history,
            "<Escape>": self.clear_cart,
            "<Delete>": self.remove_last_item,
        }
        for seq, handler in shortcuts.items():
            top.bind(seq, lambda e, h=handler: self.on_shortcut(h), add="+")

    def on_shortcut(self, handler):
        # Los atajos solo actúan con la pestaña de Ventas visible
        if not self.winfo_ismapped():
            return
        handler()
        return "break"

    def open_history(self):
        SalesHistoryDialog(self, on_change=lambda: self.render_products(self.search_var.get()))

    def focus_search(self):
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")

    def focus_qty(self):
        self.qty_entry.focus_set()
        self.qty_entry.select_range(0, "end")

    def on_search(self, *args):
        # Debounce: el lector de códigos tipea muy rápido, no redibujar por cada carácter
        if self._search_job:
            self.after_cancel(self._search_job)
        self._search_job = self.after(250, lambda: self.render_products(self.search_var.get()))

    def add_from_search(self, first_match):
        """Enter: código exacto (barcode/SKU) o resultado único; desde Cant./Kg toma el primer coincidente."""
        query = self.search_var.get().strip()
        if not query:
            self.focus_search()
            return "break"
        product = find_product_by_code(query)
        if not product:
            matches = search_products_for_sale(query)
            if len(matches) == 1 or (first_match and matches):
                product = matches[0]
            else:
                self.status_label.configure(text=f"Sin coincidencias para '{query}'." if not matches else
                                            f"{len(matches)} coincidencias: precise la búsqueda o elija con el mouse.")
                self.bell()
                return "break"
        if self.add_to_cart(product):
            self.search_var.set("")
            self.status_label.configure(text="")
        self.focus_search()
        return "break"

    def render_products(self, query=""):
        for w in self.prod_scroll.winfo_children(): w.destroy()
        for p in search_products_for_sale(query):
            card = ctk.CTkFrame(self.prod_scroll, height=70)
            card.pack(fill="x", pady=3, padx=5)
            ctk.CTkLabel(card, text=p['name'], font=ctk.CTkFont(weight="bold")).pack(side="left", padx=15)
            price_txt = f"${p['price']}/kg" if p['is_weighable'] else f"${p['price']}"
            ctk.CTkLabel(card, text=price_txt, text_color=app_of(self).current_accent).pack(side="left", padx=15)
            ctk.CTkLabel(card, text=f"Stock: {format_qty(p['stock'], p['is_weighable'])}", text_color="gray").pack(side="left", padx=15)
            ctk.CTkButton(card, text="Agregar", width=80, height=35, command=lambda item=p: self.add_to_cart(item)).pack(side="right", padx=15)

    def add_to_cart(self, p):
        try:
            qty = validate_quantity(self.qty_entry.get(), p['is_weighable'])
        except ValueError as e:
            messagebox.showerror("Cantidad inválida", f"{p['name']}: {e}")
            self.focus_qty()
            return False
        self.qty_entry.delete(0, 'end')
        self.qty_entry.insert(0, "1")
        for item in self.cart:
            if item['id'] == p['id']:
                item['quantity'] += qty
                self.update_cart_ui()
                return True
        self.cart.append({"id": p['id'], "name": p['name'], "price": p['price'], "quantity": qty, "is_weighable": p['is_weighable']})
        self.update_cart_ui()
        return True

    def remove_item(self, index):
        del self.cart[index]
        self.update_cart_ui()

    def remove_last_item(self):
        if self.cart and not entry_has_focus_with_text(self):
            self.remove_item(len(self.cart) - 1)

    def clear_cart(self):
        if self.cart and messagebox.askyesno("Vaciar carrito", "¿Quitar todos los productos del carrito?"):
            self.cart = []
            self.update_cart_ui()
        self.focus_search()

    def cart_total(self):
        # Mismo redondeo por línea que process_sale para que el total coincida al centavo
        return sum((to_decimal_money(item['price'] * item['quantity']) for item in self.cart), to_decimal_money(0))

    def update_cart_ui(self):
        for w in self.cart_container.winfo_children(): w.destroy()
        for index, item in enumerate(self.cart):
            subtotal = to_decimal_money(item['price'] * item['quantity'])
            row = ctk.CTkFrame(self.cart_container, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkButton(row, text="✕", width=24, height=24, fg_color="transparent", text_color="#e74c3c", hover_color=("gray80", "gray25"),
                          command=lambda i=index: self.remove_item(i)).pack(side="left")
            ctk.CTkLabel(row, text=f"{item['name']} x{format_qty(item['quantity'], item['is_weighable'])}", font=ctk.CTkFont(size=12)).pack(side="left")
            ctk.CTkLabel(row, text=f"${subtotal:.2f}", font=ctk.CTkFont(size=12, weight="bold")).pack(side="right")
        self.total_label.configure(text=f"TOTAL: ${self.cart_total():.2f}")

    def quick_pay(self, method_id):
        if not self.cart: return
        self.finish_sale([{"payment_method_id": method_id, "amount": self.cart_total()}])

    def quick_pay_cash(self):
        cash = next((m for m in self.payment_methods if m['name'] == CASH_METHOD), None)
        if cash:
            self.quick_pay(cash['id'])

    def open_mixed_payment(self):
        if not self.cart: return
        MixedPaymentDialog(self, self.cart_total(), self.payment_methods, self.finish_sale)

    def finish_sale(self, payments):
        customer_id = self.customers.get(self.customer_menu.get())
        success, res = process_sale(self.cart, customer_id, payments=payments, user_id=current_user_id(self))
        if not success:
            messagebox.showerror("Error", res)
            self.focus_search()
            return
        header = f"Venta #{res['sale_id']} realizada correctamente."
        if res['auto_adjustments']:
            header += "\nDesposte dinámico (stock ajustado automáticamente):\n" + "\n".join(
                f"• {a['product_name']}: +{a['adjusted_qty']}" for a in res['auto_adjustments'])
        self.cart = []
        self.customer_menu.set(NO_CUSTOMER)
        self.update_cart_ui()
        self.render_products()
        try:
            text = generate_sale_ticket_text(res['sale_id'], app_of(self).ticket_width)
            path = save_ticket(res['sale_id'], text)
        except Exception as e:
            # La venta ya quedó registrada: un fallo del comprobante no debe ocultarlo
            messagebox.showwarning("Comprobante", f"{header}\n\nNo se pudo generar el ticket: {e}")
            self.focus_search()
            return
        TicketPreviewDialog(self, header, text, path, on_close=self.focus_search)

class CustomersFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=20)
        ctk.CTkLabel(header, text="Gestión de Clientes", font=ctk.CTkFont(size=24, weight="bold")).pack(side="left")
        ctk.CTkButton(header, text="+ Nuevo Cliente", fg_color=app_of(self).current_accent,
                      command=lambda: open_customer_dialog(self, on_done=lambda _: self.load_data())).pack(side="right")
        self.scroll = ctk.CTkScrollableFrame(self)
        self.scroll.pack(fill="both", expand=True, padx=20, pady=10)
        self.load_data()

    def refresh(self):
        self.load_data()

    def load_data(self):
        for w in self.scroll.winfo_children(): w.destroy()
        for c in get_customers_list():
            row = ctk.CTkFrame(self.scroll, height=60, corner_radius=15)
            row.pack(fill="x", pady=4, padx=5)
            ctk.CTkLabel(row, text=c['full_name'], font=ctk.CTkFont(weight="bold"), width=200, anchor="w").pack(side="left", padx=(20, 5))
            ctk.CTkLabel(row, text=f"Saldo: ${c['balance']}", text_color="#e74c3c" if c['balance'] > 0 else "gray").pack(side="left", padx=10)
            if c['limite_credito'] > 0:
                ctk.CTkLabel(row, text=f"Límite: ${c['limite_credito']}", text_color="gray").pack(side="left", padx=10)
            ctk.CTkButton(row, text="WhatsApp", width=90, fg_color="#2ecc71", command=lambda x=c: self.remind(x)).pack(side="right", padx=(5, 10))
            ctk.CTkButton(row, text="$ Cobrar Deuda", width=120, state="normal" if c['balance'] > 0 else "disabled",
                          command=lambda x=c: self.collect(x['id'])).pack(side="right", padx=5)
            ctk.CTkButton(row, text="Ver Estado de Cuenta", width=150, fg_color="gray",
                          command=lambda x=c: StatementDialog(self, x['id'], on_pay=self.collect)).pack(side="right", padx=5)
            ctk.CTkButton(row, text="✎ Editar Cliente", width=120, fg_color="gray",
                          command=lambda x=c: self.edit(x['id'])).pack(side="right", padx=5)

    def edit(self, customer_id):
        open_customer_dialog(self, on_done=lambda _: self.load_data(), customer=get_customer(customer_id))

    def collect(self, customer_id):
        DebtPaymentDialog(self, customer_id, on_done=self.load_data)

    def remind(self, customer):
        if not customer['phone']:
            messagebox.showinfo("WhatsApp", f"{customer['full_name']} no tiene teléfono cargado.")
        elif customer['balance'] <= 0:
            messagebox.showinfo("WhatsApp", f"{customer['full_name']} no tiene saldo deudor.")
        else:
            send_payment_reminder(customer['full_name'], customer['phone'], customer['balance'])

class CashFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.refresh()

    def refresh(self):
        for w in self.winfo_children(): w.destroy()
        uid = current_user_id(self)
        open_s = get_open_cash_session(user_id=uid)
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True)

        ctk.CTkLabel(body, text="Gestión de Caja y Arqueo", font=ctk.CTkFont(size=24, weight="bold")).pack(pady=20)

        if not open_s:
            box = ctk.CTkFrame(body, width=400, height=300)
            box.pack(pady=30)
            ctk.CTkLabel(box, text="LA CAJA ESTÁ CERRADA", font=ctk.CTkFont(weight="bold")).pack(pady=20)
            self.amt_ent = ctk.CTkEntry(box, placeholder_text="Monto Inicial $", width=200)
            self.amt_ent.pack(pady=10)
            ctk.CTkButton(box, text="ABRIR TURNO", command=self.open_s, fg_color="#2ecc71").pack(pady=20)
            last = get_last_closed_cash_session(user_id=uid)
            if last:
                self.render_summary(body, get_profitability_and_audit_summary(cash_session_id=last['id']),
                                    f"Último turno cerrado (#{last['id']})")
        else:
            info = ctk.CTkFrame(body)
            info.pack(fill="x", padx=40, pady=20)
            ctk.CTkLabel(info, text=f"Sesión abierta el {open_s['start_date'].strftime('%d/%m %H:%M')}", font=ctk.CTkFont(size=16)).pack(pady=10)
            
            metrics = ctk.CTkFrame(body, fg_color="transparent")
            metrics.pack(fill="x", padx=40)
            self.create_metric(metrics, "Efectivo en Ventas", open_s['total_sales_cash'])
            self.create_metric(metrics, "Ventas Digitales", open_s['total_sales_digital'])
            self.create_metric(metrics, "Gastos/Egresos", open_s['total_expenses'])
            
            gasto_f = ctk.CTkFrame(body)
            gasto_f.pack(pady=20, padx=40, fill="x")
            self.g_desc = ctk.CTkEntry(gasto_f, placeholder_text="Descripción del gasto...", width=300)
            self.g_desc.pack(side="left", padx=10, pady=10)
            self.g_amt = ctk.CTkEntry(gasto_f, placeholder_text="Monto $", width=100)
            self.g_amt.pack(side="left", padx=10)
            ctk.CTkButton(gasto_f, text="Registrar Gasto", command=self.add_g).pack(side="right", padx=10)

            self.render_summary(body, get_profitability_and_audit_summary(cash_session_id=open_s['id']), "Rentabilidad del turno actual")
            ctk.CTkButton(body, text="CERRAR CAJA (ARQUEO FINAL)", fg_color="#e74c3c", height=50, command=self.close_s).pack(pady=20)

        # Reporte por rango de fechas
        range_f = ctk.CTkFrame(body)
        range_f.pack(fill="x", padx=40, pady=(10, 20))
        ctk.CTkLabel(range_f, text="Reporte por rango:", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=10, pady=10)
        today = local_now().strftime("%d/%m/%Y")
        self.range_from = ctk.CTkEntry(range_f, width=110, placeholder_text="dd/mm/aaaa")
        self.range_to = ctk.CTkEntry(range_f, width=110, placeholder_text="dd/mm/aaaa")
        for e in (self.range_from, self.range_to):
            e.insert(0, today)
            e.pack(side="left", padx=5)
        ctk.CTkButton(range_f, text="Ver rango", width=100, command=lambda: self.show_range(body)).pack(side="left", padx=10)
        self.range_container = ctk.CTkFrame(body, fg_color="transparent")
        self.range_container.pack(fill="x")

    def show_range(self, body):
        try:
            start_day, end_day = parse_local_date(self.range_from.get()), parse_local_date(self.range_to.get())
        except ValueError as e:
            messagebox.showerror("Fechas inválidas", str(e))
            return
        if not start_day or not end_day:
            messagebox.showerror("Fechas inválidas", "Complete ambas fechas (dd/mm/aaaa).")
            return
        # Días completos del negocio: incluye 21:00–23:59 (en UTC ya es el día siguiente)
        start = local_now().replace(year=start_day.year, month=start_day.month, day=start_day.day, hour=0, minute=0, second=0, microsecond=0)
        end = start.replace(year=end_day.year, month=end_day.month, day=end_day.day, hour=23, minute=59, second=59, microsecond=999999)
        if start > end:
            messagebox.showerror("Fechas inválidas", "La fecha 'desde' es posterior a 'hasta'.")
            return
        for w in self.range_container.winfo_children(): w.destroy()
        title = f"Rango {start.strftime('%d/%m/%Y')} – {end.strftime('%d/%m/%Y')}"
        self.render_summary(self.range_container, get_profitability_and_audit_summary(start, end), title)

    def render_summary(self, parent, summary, title):
        """Ganancia Neta Real + alerta de despostes + exportación."""
        box = ctk.CTkFrame(parent)
        box.pack(fill="x", padx=40, pady=10)
        head = ctk.CTkFrame(box, fg_color="transparent")
        head.pack(fill="x", padx=15, pady=(10, 0))
        ctk.CTkLabel(head, text=title, font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        ctk.CTkButton(head, text="Exportar Resumen (CSV/Excel)", width=200,
                      command=lambda: self.export(summary, title)).pack(side="right")

        grid = ctk.CTkFrame(box, fg_color="transparent")
        grid.pack(fill="x", padx=10, pady=10)
        cells = [("Ventas netas", summary['total_sales'], None), ("CMV", summary['cmv'], None),
                 (f"Margen bruto ({summary['gross_margin_pct']}%)", summary['gross_profit'], None),
                 ("Gastos de caja", summary['expenses'], None), ("Mermas valorizadas", summary['shrinkage_cost'], None),
                 ("GANANCIA NETA REAL", summary['net_profit'], "#2ecc71" if summary['net_profit'] >= 0 else "#e74c3c")]
        for i, (label, value, color) in enumerate(cells):
            cell = ctk.CTkFrame(grid)
            cell.grid(row=i // 3, column=i % 3, padx=5, pady=5, sticky="nsew")
            grid.grid_columnconfigure(i % 3, weight=1)
            ctk.CTkLabel(cell, text=label, text_color="gray").pack(pady=(8, 0))
            ctk.CTkLabel(cell, text=f"${value:.2f}", font=ctk.CTkFont(size=18, weight="bold"),
                         text_color=color or ("gray10", "gray90")).pack(pady=(0, 8))
        if summary['returns'] > 0:
            ctk.CTkLabel(box, text=f"Incluye devoluciones por ${summary['returns']:.2f}", text_color="gray").pack(anchor="w", padx=15)

        count = summary['auto_adjustments_count']
        if count:
            ctk.CTkLabel(box, text=f"⚠ {count} ajuste(s) automático(s) por desposte dinámico (AUTO_ADJUST_IN) a auditar:",
                         text_color="#e67e22", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=15, pady=(5, 0))
            for a in summary['auto_adjustments'][:15]:
                ref = a['reference'].split(' - ')[0]
                ctk.CTkLabel(box, text=f"• {a['date'].strftime('%d/%m %H:%M')}  {a['product']}: +{a['quantity']}  ({ref})",
                             anchor="w").pack(anchor="w", padx=30)
            if count > 15:
                ctk.CTkLabel(box, text=f"… y {count - 15} más (ver exportación)", text_color="gray").pack(anchor="w", padx=30)
        else:
            ctk.CTkLabel(box, text="Sin ajustes por desposte dinámico en el período.", text_color="gray").pack(anchor="w", padx=15)
        ctk.CTkFrame(box, height=8, fg_color="transparent").pack()

    def export(self, summary, title):
        default = "resumen_" + "".join(c if c.isalnum() else "_" for c in title.lower()).strip("_") + ".xlsx"
        path = filedialog.asksaveasfilename(title="Exportar resumen", initialfile=default, defaultextension=".xlsx",
                                            filetypes=[("Excel", "*.xlsx"), ("CSV", "*.csv")])
        if not path:
            return
        try:
            export_summary(summary, path)
            messagebox.showinfo("Exportación", f"Resumen guardado en:\n{path}")
        except Exception as e:
            messagebox.showerror("Exportación", f"No se pudo exportar: {e}")

    def create_metric(self, master, label, val):
        f = ctk.CTkFrame(master)
        f.pack(side="left", expand=True, padx=10, fill="both")
        ctk.CTkLabel(f, text=label, text_color="gray").pack(pady=5)
        ctk.CTkLabel(f, text=f"${val:.2f}", font=ctk.CTkFont(size=20, weight="bold")).pack(pady=5)

    def open_s(self):
        self.show_result("Caja", *open_cash_session(self.amt_ent.get(), user_id=current_user_id(self)))

    def add_g(self):
        self.show_result("Gasto", *add_cash_expense(self.g_amt.get(), self.g_desc.get(), user_id=current_user_id(self)))

    def close_s(self):
        ans = tk.simpledialog.askstring("Cierre de Caja", "Monto REAL contado en caja ($):", parent=self)
        if ans is not None:
            self.show_result("Cierre", *close_cash_session(ans, user_id=current_user_id(self)))

    def show_result(self, title, success, msg):
        if success:
            messagebox.showinfo(title, msg)
            self.refresh()
        else:
            messagebox.showerror(title, msg)

class SuppliersFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=20)
        ctk.CTkLabel(header, text="Proveedores y El Dean Ranking", font=ctk.CTkFont(size=24, weight="bold")).pack(side="left")
        ctk.CTkButton(header, text="+ Nuevo Proveedor", fg_color=app_of(self).current_accent,
                      command=lambda: open_supplier_dialog(self, on_done=lambda _: self.refresh())).pack(side="right")
        ctk.CTkButton(header, text="✎ Editar seleccionado", fg_color="gray", command=self.edit_selected).pack(side="right", padx=10)
        ctk.CTkButton(header, text="Ver en Maps", fg_color="gray", command=self.open_maps).pack(side="right")
        
        self.rank_f = ctk.CTkFrame(self, height=200)
        self.rank_f.grid(row=1, column=0, sticky="ew", padx=20, pady=10)

        self.tree = ttk.Treeview(self, columns=("Nombre", "Teléfono", "Email", "Dirección"), show='headings')
        for col in self.tree["columns"]: self.tree.heading(col, text=col)
        self.tree.grid(row=2, column=0, sticky="nsew", padx=20, pady=10)
        self.tree.bind("<Double-1>", lambda e: self.edit_selected())
        self.refresh()

    def refresh(self):
        for w in self.rank_f.winfo_children(): w.destroy()
        ctk.CTkLabel(self.rank_f, text="Ranking 'El Dean' (Por Volumen de Productos)", font=ctk.CTkFont(weight="bold")).pack(pady=10)
        for name, count in get_bi_stats()['supplier_ranking']:
            row = ctk.CTkFrame(self.rank_f, fg_color="transparent")
            row.pack(fill="x", padx=20)
            ctk.CTkLabel(row, text=name, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=f"{count} artículos", text_color="#3498db").pack(side="right")
        self.load_data()

    def load_data(self):
        self.suppliers = {str(s['id']): s for s in get_suppliers_list()}
        for i in self.tree.get_children(): self.tree.delete(i)
        for iid, s in self.suppliers.items():
            self.tree.insert("", "end", iid=iid, values=(s['name'], s['phone'] or "", s['email'] or "", s['address'] or ""))

    def selected(self):
        selection = self.tree.selection()
        return self.suppliers.get(selection[0]) if selection else None

    def edit_selected(self):
        supplier = self.selected()
        if not supplier:
            messagebox.showinfo("Proveedores", "Seleccione un proveedor (o haga doble clic sobre él).")
            return
        open_supplier_dialog(self, on_done=lambda _: self.refresh(), supplier=supplier)

    def open_maps(self, event=None):
        supplier = self.selected()
        if not supplier:
            messagebox.showinfo("Proveedores", "Seleccione un proveedor para verlo en el mapa.")
            return
        query = supplier['address'] or f"{supplier['name']} Santiago del Estero"
        webbrowser.open(f"https://www.google.com/maps/search/{query}")

class ConfigFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        ctk.CTkLabel(self, text="Configuración y Personalización", font=ctk.CTkFont(size=24, weight="bold")).pack(pady=20)
        ctk.CTkLabel(self, text="Color de Acento (Interfaz):").pack(pady=10)
        colors_f = ctk.CTkFrame(self, fg_color="transparent")
        colors_f.pack()
        
        accent_list = {
            "Blue": "#4318ff", "Green": "#2ecc71", "Purple": "#8e44ad",
            "Orange": "#e67e22", "Red": "#e74c3c", "Teal": "#1abc9c",
            "Pink": "#fd79a8", "Yellow": "#f1c40f", "Dark": "#2d3436", "Indigo": "#3f51b5"
        }
        
        i = 0
        for name, hex in accent_list.items():
            btn = ctk.CTkButton(colors_f, text="", fg_color=hex, width=40, height=40, corner_radius=20,
                                command=lambda h=hex: app_of(self).update_accent(h))
            btn.grid(row=i//5, column=i%5, padx=10, pady=10)
            i += 1

        ctk.CTkLabel(self, text="Modo Visual:").pack(pady=(30, 10))
        ctk.CTkSegmentedButton(self, values=["Light", "Dark", "System"], command=ctk.set_appearance_mode).pack()

        ctk.CTkLabel(self, text="Ancho del ticket (impresora térmica):").pack(pady=(30, 10))
        widths = ctk.CTkSegmentedButton(self, values=list(TICKET_WIDTHS), command=self.set_ticket_width)
        widths.set(next(k for k, v in TICKET_WIDTHS.items() if v == app_of(self).ticket_width))
        widths.pack()

        # Copias de seguridad: diaria automática (al iniciar y al cerrar caja) + manual / pendrive
        ctk.CTkLabel(self, text="Copias de seguridad:").pack(pady=(30, 5))
        self.backup_label = ctk.CTkLabel(self, text="", text_color="gray", justify="center")
        self.backup_label.pack()
        backup_f = ctk.CTkFrame(self, fg_color="transparent")
        backup_f.pack(pady=10)
        ctk.CTkButton(backup_f, text="Crear Copia de Seguridad Ahora", fg_color="#2ecc71",
                      command=self.backup_now).pack(side="left", padx=5)
        ctk.CTkButton(backup_f, text="Exportar copia a carpeta / pendrive...", fg_color="gray",
                      command=self.backup_external).pack(side="left", padx=5)
        self.refresh()

    def refresh(self):
        status = get_backup_status()
        last = status['backups'][0]['name'] if status['backups'] else "ninguna todavía"
        self.backup_label.configure(text=f"Carpeta: {status['folder']}\nÚltima: {last} · se conservan las {status['keep']} más recientes")

    def backup_now(self):
        self.show_backup_result(*create_manual_backup())

    def backup_external(self):
        folder = filedialog.askdirectory(title="Elegir carpeta o pendrive para la copia de seguridad")
        if folder:
            self.show_backup_result(*create_manual_backup(folder))

    def show_backup_result(self, ok, msg, data):
        (messagebox.showinfo if ok else messagebox.showerror)("Copia de seguridad", msg)
        self.refresh()

    def set_ticket_width(self, value):
        app_of(self).ticket_width = TICKET_WIDTHS[value]

# --- APP PRINCIPAL ---
class DashboardApp(AfterCleanupMixin, ctk.CTk):
    def __init__(self, username, user_id=None, accent="#4318ff"):
        super().__init__()
        self.username = username
        self.user_id = user_id or 1  # fallback histórico: admin
        self.logout_requested = False
        self.current_accent = accent
        self.ticket_width = DEFAULT_WIDTH
        self.title(f"Impulso Smart - Bienvenido {username}")
        self.geometry("1300x850")
        
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self.sidebar = ctk.CTkFrame(self, width=240, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(self.sidebar, text="IMPULSO SMART", font=ctk.CTkFont(size=22, weight="bold")).pack(pady=30)
        
        self.btns = {}
        nav = [("Dashboard", "Dashboard"), ("Ventas / POS", "Ventas"), ("Inventario", "Inventario"), 
               ("Clientes", "Clientes"), ("Proveedores", "Proveedores"), ("Caja", "Caja"), ("Configuración", "Config")]
        
        for label, name in nav:
            self.btns[name] = SidebarButton(self.sidebar, label, lambda n=name: self.show_frame(n))
            self.btns[name].pack(fill="x", padx=15, pady=5)
        
        # Botón Cerrar Sesión
        SidebarButton(self.sidebar, "Cerrar Sesión", self.logout, fg_color="#e74c3c", hover_color="#c0392b").pack(fill="x", padx=15, pady=20, side="bottom")

        profile = ctk.CTkFrame(self.sidebar, height=60, fg_color="transparent")
        profile.pack(side="bottom", fill="x", pady=10, padx=10)
        ctk.CTkLabel(profile, text=f"Usuario: {username}", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=10)

        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        self.frames = {}
        self.frames["Dashboard"] = DashboardFrame(self.container)
        self.frames["Ventas"] = SalesFrame(self.container)
        self.frames["Inventario"] = InventoryFrame(self.container)
        self.frames["Clientes"] = CustomersFrame(self.container)
        self.frames["Proveedores"] = SuppliersFrame(self.container)
        self.frames["Caja"] = CashFrame(self.container)
        self.frames["Config"] = ConfigFrame(self.container)

        self.show_frame("Dashboard")

    def on_closing(self):
        ans = messagebox.askyesnocancel("Salir", "¿Desea salir de la aplicación o cerrar sesión?", 
                                        detail="Sí: Salir, No: Cerrar Sesión, Cancelar: Continuar")
        if ans is True: # Salir
            self.destroy()
        elif ans is False: # Cerrar sesión
            self.logout()

    def logout(self):
        # login_gui.main() vuelve a mostrar el login al terminar este mainloop
        if messagebox.askyesno("Cerrar Sesión", f"¿Está seguro de que desea cerrar la sesión de {self.username}?"):
            self.logout_requested = True
            self.destroy()

    def show_frame(self, name):
        for f in self.frames.values(): f.grid_forget()
        self.frames[name].grid(row=0, column=0, sticky="nsew")
        if hasattr(self.frames[name], 'refresh'): self.frames[name].refresh()
        for k, b in self.btns.items():
            b.configure(fg_color=self.current_accent if k == name else "transparent", text_color="white" if k == name else ("gray10", "gray90"))

    def update_accent(self, hex):
        self.current_accent = hex
        messagebox.showinfo("Tema", "Color de acento actualizado.")
        for k, b in self.btns.items():
            if b.cget("fg_color") != "transparent": b.configure(fg_color=hex)

