"""Comprobante de venta en texto plano para impresoras térmicas (58mm = 32 col, 80mm = 42 col)."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from business_logic import get_sale_ticket_data, format_qty
from db_manager import default_db_path

TICKET_WIDTHS = {"58mm": 32, "80mm": 42}
DEFAULT_WIDTH = TICKET_WIDTHS["80mm"]
BUSINESS_NAME = "IMPULSO SMART"

def tickets_dir():
    # Junto a la base de datos (misma carpeta de datos que usa la app instalada)
    return default_db_path().parent / "tickets"

def _line(left, right, width):
    """Texto a la izquierda y monto alineado a la derecha; si no entra, el monto baja de renglón."""
    if len(left) + 1 + len(right) <= width:
        return [left + right.rjust(width - len(left))]
    return textwrap.wrap(left, width) + [right.rjust(width)]

def build_ticket_text(data, width=DEFAULT_WIDTH):
    sep = "-" * width
    out = [BUSINESS_NAME.center(width).rstrip(), sep]
    out.append(f"Fecha: {data['date'].strftime('%d/%m/%Y %H:%M')}")
    out.append(f"Venta N°: {data['sale_id']:06d}")
    out += textwrap.wrap(f"Cliente: {data['customer']}", width)
    out.append(sep)
    for item in data["items"]:
        out += textwrap.wrap(item["name"], width)
        detail = f"  {format_qty(item['quantity'], item['is_weighable'])} x ${item['price']:.2f}"
        out += _line(detail, f"${item['subtotal']:.2f}", width)
    out.append(sep)
    if data["discount"] > 0:
        out += _line("Descuento", f"-${data['discount']:.2f}", width)
    if data["points_discount"] > 0:
        out += _line("Canje de puntos", f"-${data['points_discount']:.2f}", width)
    if data["surcharge"] > 0:
        out += _line("Recargo", f"${data['surcharge']:.2f}", width)
    out += _line("TOTAL", f"${data['total']:.2f}", width)
    out.append(sep)
    out.append("Pagos:")
    for p in data["payments"]:
        out += _line(f"  {p['name']}", f"${p['amount']:.2f}", width)
    out.append(sep)
    out.append("¡Gracias por su compra!".center(width).rstrip())
    return "\n".join(out) + "\n"

def generate_sale_ticket_text(sale_id: int, width: int = DEFAULT_WIDTH) -> str:
    return build_ticket_text(get_sale_ticket_data(sale_id), width)

def build_payment_receipt_text(data, width=DEFAULT_WIDTH):
    """Recibo de cobro de deuda de Cuenta Corriente (datos de business_logic.register_debt_payment)."""
    sep = "-" * width
    out = [BUSINESS_NAME.center(width).rstrip(), "RECIBO DE PAGO".center(width).rstrip(), sep,
           f"Fecha: {data['date'].strftime('%d/%m/%Y %H:%M')}", f"Recibo N°: {data['payment_id']:06d}"]
    out += textwrap.wrap(f"Cliente: {data['customer']}", width)
    out.append(sep)
    out += _line("Saldo anterior", f"${data['balance_before']:.2f}", width)
    out += _line(f"Pago ({data['method']})", f"-${data['amount']:.2f}", width)
    out += _line("SALDO ACTUAL", f"${data['balance_after']:.2f}", width)
    if data.get("notes"):
        out.append(sep)
        out += textwrap.wrap(f"Nota: {data['notes']}", width)
    out.append(sep)
    out.append("¡Gracias!".center(width).rstrip())
    return "\n".join(out) + "\n"

def _save(name, text, folder=None):
    folder = Path(folder) if folder else tickets_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path

def save_ticket(sale_id, text, folder=None):
    return _save(f"ticket_venta_{sale_id:06d}.txt", text, folder)

def save_payment_receipt(payment_id, text, folder=None):
    return _save(f"recibo_pago_{payment_id:06d}.txt", text, folder)

def print_ticket(path):
    """Envía el archivo a la impresora predeterminada del sistema. Devuelve (ok, mensaje)."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path), "print")
        else:
            cmd = ["lp", str(path)] if subprocess.run(["which", "lp"], capture_output=True).returncode == 0 else ["lpr", str(path)]
            subprocess.run(cmd, check=True, capture_output=True)
        return True, "Ticket enviado a la impresora."
    except Exception as e:
        return False, f"No se pudo imprimir: {e}"
