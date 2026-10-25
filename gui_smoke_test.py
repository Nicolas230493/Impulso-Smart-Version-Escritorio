"""Prueba de humo de la interfaz de escritorio (necesita Tk y una pantalla).

Uso: python gui_smoke_test.py
Abre Login y Dashboard reales sobre una base temporal, recorre todas las pantallas, diálogos y atajos
y falla si algún callback de Tk lanza una excepción. Los cuadros bloqueantes (messagebox, selector de
archivo, navegador, impresora) se reemplazan por registradores. Nunca toca la base real.
"""
import os
import sys
import tempfile
import traceback
from decimal import Decimal as D
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pos_system.settings')
TMP = Path(tempfile.mkdtemp())

import django
from django.conf import settings
settings.DATABASES['default']['NAME'] = TMP / 'db.sqlite3'
django.setup()

import tkinter.filedialog
import tkinter.messagebox
import tkinter.simpledialog
import webbrowser

import business_logic as bl
import db_manager
import ticket_printer
from core.bootstrap import ensure_initial_admin, prepare_database

db_manager.db = bl.db = db_manager.DatabaseManager(TMP / 'db.sqlite3')
prepare_database(db_manager.db)
ensure_initial_admin()

dialogs, errors = [], []
for name in ("showinfo", "showwarning", "showerror"):
    setattr(tkinter.messagebox, name, lambda title, msg, _n=name, **kw: dialogs.append((_n, title, str(msg))))
tkinter.messagebox.askyesno = lambda *a, **kw: True
tkinter.messagebox.askyesnocancel = lambda *a, **kw: False
tkinter.simpledialog.askstring = lambda *a, **kw: "1000,00"
tkinter.filedialog.asksaveasfilename = lambda **kw: str(TMP / kw.get("initialfile", "export.xlsx"))
tkinter.filedialog.askdirectory = lambda **kw: str(TMP / "pendrive")
webbrowser.open = lambda url, *a, **kw: dialogs.append(("browser", url, ""))
ticket_printer.tickets_dir = lambda: TMP / "tickets"

import gui_main
import login_gui
gui_main.print_ticket = lambda path: (True, "impreso (simulado)")


def record_tk_error(exc, val, tb):
    errors.append("".join(traceback.format_exception(exc, val, tb)))


def pump(widget):
    for _ in range(3):
        widget.update()


def find(widget, cls):
    """Ventanas/widgets de una clase entre todos los descendientes (los diálogos cuelgan de cada pantalla)."""
    found = []
    for child in widget.winfo_children():
        if isinstance(child, cls):
            found.append(child)
        found += find(child, cls)
    return found


def check(cond, msg):
    if not cond:
        errors.append(f"FALLÓ: {msg}")


def run():
    # --- Login: clave incorrecta y luego admin/admin (instalación nueva)
    login = login_gui.LoginApp()
    login.report_callback_exception = record_tk_error
    login.user_entry.insert(0, "admin")
    login.pass_entry.insert(0, "mala")
    login.validate_login()
    check(login.authenticated_user is None, "login con clave incorrecta")
    login.user_entry.insert(0, "admin")
    login.pass_entry.insert(0, "admin")
    login.validate_login()
    check(login.authenticated_user and login.authenticated_user[1] == "admin", "login admin/admin")
    user_id = login.authenticated_user[0]

    app = gui_main.DashboardApp(username="admin", user_id=user_id)
    app.report_callback_exception = record_tk_error
    pump(app)
    for name in app.frames:
        app.show_frame(name)
        pump(app)

    # --- Inventario: alta con el botón "+ Nuevo Producto" y edición
    inv = app.frames["Inventario"]
    app.show_frame("Inventario")
    gui_main.ProductDialog(inv, on_done=inv.load_data)
    pump(app)
    dlg = find(inv, gui_main.ProductDialog)[-1]
    for key, value in {"name": "Pollo entero", "barcode": "779000111", "price": "4000", "cost_price": "2000",
                       "initial_stock": "0,300"}.items():
        dlg.entries[key].insert(0, value)
    dlg.weighable.select()
    dlg.save()
    pump(app)
    pollo = bl.find_product_by_code("779000111")
    check(pollo and pollo["is_weighable"] and pollo["stock"] == D("0.300"), "alta de producto pesable desde la GUI")
    inv.tree.selection_set(str(pollo["id"]))
    inv.edit_selected()
    pump(app)
    edit = find(inv, gui_main.ProductDialog)[-1]
    edit.entries["price"].delete(0, "end")
    edit.entries["price"].insert(0, "4200")
    edit.save()
    pump(app)
    check(bl.get_product(pollo["id"])["price"] == D("4200.00"), "edición de precio")
    ok, coca_id = bl.save_product({"name": "Coca 1L", "price": "1500", "cost_price": "900", "barcode": "779000222"})

    # --- Ingreso de mercadería con CPP
    gui_main.StockEntryDialog(inv, on_done=inv.load_data)
    pump(app)
    entry = find(inv, gui_main.StockEntryDialog)[-1]
    entry.add_line(bl.find_product_by_code("779000222"))
    line = entry.lines[coca_id]
    line["qty"].insert(0, "10")
    line["cost"].delete(0, "end")
    line["cost"].insert(0, "1000")
    entry.update_preview(coca_id)
    entry.confirm()
    pump(app)
    check(bl.get_product(coca_id)["stock"] == D("10.000"), "ingreso de mercadería")

    # --- Caja: abrir turno y registrar gasto
    app.show_frame("Caja")
    cash = app.frames["Caja"]
    cash.amt_ent.insert(0, "500")
    cash.open_s()
    pump(app)
    cash.g_desc.insert(0, "Hielo")
    cash.g_amt.insert(0, "100,50")
    cash.add_g()
    pump(app)
    check(bl.get_open_cash_session(user_id=user_id)["total_expenses"] == D("100.50"), "gasto de caja")

    # --- POS: escáner + peso con Enter, atajos y cobro rápido en efectivo
    app.show_frame("Ventas")
    sales = app.frames["Ventas"]
    pump(app)
    sales.qty_entry.delete(0, "end")
    sales.qty_entry.insert(0, "1,250")
    sales.search_var.set("779000111")
    sales.add_from_search(first_match=False)
    sales.search_var.set("779000222")
    sales.add_from_search(first_match=False)
    sales.search_var.set("779000222")
    sales.add_from_search(first_match=False)
    check(len(sales.cart) == 2 and sales.cart[0]["quantity"] == D("1.250") and sales.cart[1]["quantity"] == D("2"),
          "carrito por escáner")
    sales.on_shortcut(sales.focus_search)
    sales.on_shortcut(sales.focus_qty)
    sales.on_shortcut(sales.quick_pay_cash)  # F5
    pump(app)
    tickets = find(sales, gui_main.TicketPreviewDialog)
    check(len(tickets) == 1 and sales.cart == [], "cobro F5 + vista previa del ticket")
    if tickets:
        tickets[0].print_ticket()
        tickets[0].close()
    check(any(p.name.startswith("ticket_venta_") for p in (TMP / "tickets").iterdir()), "ticket guardado")

    # --- Pago mixto (F6): 2000 en efectivo y el resto al segundo medio
    sales.search_var.set("779000222")
    sales.add_from_search(first_match=False)
    sales.on_shortcut(sales.open_mixed_payment)
    pump(app)
    mixed = find(sales, gui_main.MixedPaymentDialog)[-1]
    mixed.rows[0][1].insert(0, "1000")
    mixed.update_rest()
    mixed.confirm()
    pump(app)
    for t in find(sales, gui_main.TicketPreviewDialog):
        t.close()
    sales.search_var.set("779000222")
    sales.add_from_search(first_match=False)
    sales.on_shortcut(sales.remove_last_item)  # Supr
    check(sales.cart == [], "quitar último ítem")

    # --- Baja / merma con el producto marcado en la tabla
    app.show_frame("Inventario")
    inv.load_data()
    inv.tree.selection_set(str(coca_id))
    inv.register_loss()
    pump(app)
    loss = find(inv, gui_main.ShrinkageDialog)[-1]
    check(loss.product()["id"] == coca_id, "baja: producto preseleccionado")
    loss.qty_entry.insert(0, "1")
    loss.reason.set("Rotura")
    loss.update_preview()
    check("$1000.00" in loss.cost_label.cget("text"), "baja: costo valorizado")
    loss.confirm()
    pump(app)
    check(bl.get_product(coca_id)["stock"] == D("6.000"), "baja descuenta stock")  # 10 - 3 vendidas - 1 baja

    # --- Proveedores: alta y edición
    app.show_frame("Proveedores")
    sup_frame = app.frames["Proveedores"]
    gui_main.open_supplier_dialog(sup_frame, on_done=lambda _: sup_frame.refresh())
    pump(app)
    form = find(sup_frame, gui_main.FormDialog)[-1]
    form.entries["name"].insert(0, "Avícola del Norte")
    form.entries["address"].insert(0, "Ruta 9 km 1100")
    form.save()
    pump(app)
    sid = next(i for i, s in sup_frame.suppliers.items() if s["name"] == "Avícola del Norte")
    sup_frame.tree.selection_set(sid)
    sup_frame.open_maps()
    sup_frame.edit_selected()
    pump(app)
    form = find(sup_frame, gui_main.FormDialog)[-1]
    form.entries["phone"].insert(0, "3854111111")
    form.save()
    pump(app)
    check(sup_frame.suppliers[sid]["phone"] == "3854111111", "edición de proveedor")

    # --- Clientes: alta con límite, venta fiada desde el POS, estado de cuenta y cobro con recibo
    app.show_frame("Clientes")
    cust_frame = app.frames["Clientes"]
    gui_main.open_customer_dialog(cust_frame, on_done=lambda _: cust_frame.load_data())
    pump(app)
    form = find(cust_frame, gui_main.FormDialog)[-1]
    for key, value in {"name": "Doña Rosa", "dni_cuit": "27123456", "phone": "5493855000000", "credit_limit": "20000"}.items():
        form.entries[key].insert(0, value)
    form.save()
    pump(app)
    rosa = next(c for c in bl.get_customers_list() if c["full_name"] == "Doña Rosa")
    cust_frame.edit(rosa["id"])
    pump(app)
    form = find(cust_frame, gui_main.FormDialog)[-1]
    form.entries["address"].insert(0, "Libertad 50")
    form.save()
    pump(app)
    cf = next(c for c in bl.get_customers_list() if c["is_final_consumer"])
    cust_frame.edit(cf["id"])
    pump(app)
    form = find(cust_frame, gui_main.FormDialog)[-1]
    check(form.entries["credit_limit"].cget("state") == "disabled", "Consumidor Final: límite bloqueado")
    form.save()
    pump(app)

    app.show_frame("Ventas")
    sales.customer_menu.set(next(k for k, v in sales.customers.items() if v == rosa["id"]))
    sales.search_var.set("779000222")
    sales.add_from_search(first_match=False)
    cc_id = next(m["id"] for m in sales.payment_methods if m["name"] == "Cuenta Corriente")
    sales.quick_pay(cc_id)
    pump(app)
    for t in find(sales, gui_main.TicketPreviewDialog):
        t.close()
    check(bl.get_customer(rosa["id"])["balance"] == D("1500.00"), "venta fiada desde el POS")

    app.show_frame("Clientes")
    gui_main.StatementDialog(cust_frame, rosa["id"], on_pay=cust_frame.collect)
    pump(app)
    statement = find(cust_frame, gui_main.StatementDialog)[-1]
    statement.destroy()
    cust_frame.collect(rosa["id"])
    pump(app)
    pay = find(cust_frame, gui_main.DebtPaymentDialog)[-1]
    pay.amount.delete(0, "end")
    pay.amount.insert(0, "1000,00")
    pay.confirm()
    pump(app)
    receipts = find(cust_frame, gui_main.TicketPreviewDialog)
    check(len(receipts) == 1 and "RECIBO DE PAGO" in Path(receipts[0].ticket_path).read_text(encoding="utf-8"), "recibo de cobro")
    for r in receipts:
        r.close()
    check(bl.get_customer(rosa["id"])["balance"] == D("500.00"), "cobro de deuda")

    # --- Historial de ventas: reimpresión y devolución
    app.show_frame("Ventas")
    pump(app)  # los atajos solo actúan con la pantalla ya visible (mapeada)
    sales.on_shortcut(sales.open_history)  # F8
    pump(app)
    history = find(sales, gui_main.SalesHistoryDialog)[-1]
    sale_ids = history.tree.get_children()
    check(len(sale_ids) >= 3, "historial lista las ventas del día")
    history.tree.selection_set(sale_ids[-1])  # la primera venta del día (pollo + coca)
    history.reprint()
    pump(app)
    for t in find(history, gui_main.TicketPreviewDialog):
        t.close()
    history.open_return()
    pump(app)
    ret = find(history, gui_main.ReturnDialog)[-1]
    ret.fill_all()
    # 1.250 kg x $4200 (precio editado arriba) + 2 u. x $1500
    check(ret.total_label.cget("text") == "Total a devolver: $8250.00", "devolución: total previsto")
    ret.confirm()
    pump(app)
    check(any(s["returned"] > 0 for s in bl.get_recent_sales()), "devolución registrada")
    history.destroy()

    # --- Resto de pantallas y acciones
    app.show_frame("Clientes")
    app.frames["Clientes"].remind({"full_name": "Sin tel", "phone": None, "balance": D("10")})
    app.show_frame("Proveedores")
    app.frames["Proveedores"].open_maps()  # sin selección no debe fallar
    app.show_frame("Config")
    app.frames["Config"].set_ticket_width("58mm")
    check(app.ticket_width == 32, "ancho de ticket")
    app.frames["Config"].backup_now()
    app.frames["Config"].backup_external()
    check(any((TMP / "pendrive").glob("impulso_smart_*.sqlite3")), "copia de seguridad a pendrive")
    check(len(list((TMP / "backups").glob("impulso_smart_*.sqlite3"))) >= 2, "copia diaria al iniciar + copia manual")
    check("Última: impulso_smart_" in app.frames["Config"].backup_label.cget("text"), "estado de copias en Configuración")
    app.show_frame("Caja")
    pump(app)
    summary = bl.get_profitability_and_audit_summary(cash_session_id=bl.get_open_cash_session(user_id=user_id)["id"])
    check(summary["sales_count"] == 3 and summary["auto_adjustments_count"] == 1 and summary["returns"] > 0,
          "resumen del turno con desposte y devolución")
    cash.export(summary, "turno actual")
    check((TMP / "resumen_turno_actual.xlsx").exists(), "exportación a Excel")
    cash.range_from.delete(0, "end")
    cash.range_from.insert(0, "01/01/2026")
    cash.show_range(None)
    cash.close_s()  # askstring simulado: 1000,00
    pump(app)
    check(bl.get_open_cash_session(user_id=user_id) is None, "cierre de caja")
    app.show_frame("Dashboard")
    pump(app)

    app.logout()  # askyesno simulado: sí
    check(app.logout_requested, "cerrar sesión vuelve al login")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        errors.append(traceback.format_exc())
    unexpected = [d for d in dialogs if d[0] == "showerror"]
    for e in errors:
        print(e)
    for d in unexpected:
        print("Diálogo de error inesperado:", d)
    print(f"{len(dialogs)} diálogos simulados, {len(errors)} errores, {len(unexpected)} errores mostrados al usuario")
    sys.exit(1 if errors or unexpected else 0)
