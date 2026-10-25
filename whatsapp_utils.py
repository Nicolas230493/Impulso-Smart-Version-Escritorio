import urllib.parse
import webbrowser

def send_whatsapp_ticket(customer_name, phone, sale_id, date, items, total, discount=0):
    if not phone:
        return False
        
    resumen = f"*Ticket Digital - Impulso Smart*\n"
    resumen += f"Venta #{sale_id} - {date}\n"
    resumen += f"--------------------------\n"
    for item in items:
        resumen += f"{item['name']} x{item['quantity']}: ${item['subtotal']}\n"
    
    if discount > 0:
        resumen += f"Descuento: -${discount}\n"
    
    resumen += f"--------------------------\n"
    resumen += f"*TOTAL: ${total}*\n"
    resumen += f"Gracias por su compra!"
    
    link = f"https://wa.me/{phone}?text={urllib.parse.quote(resumen)}"
    webbrowser.open(link)
    return True

def send_payment_reminder(customer_name, phone, balance):
    if not phone or balance <= 0:
        return False
        
    mensaje = f"Hola {customer_name}, te saludamos de IMPULSO SMART. Te recordamos que posees un saldo pendiente de ${balance}. ¡Muchas gracias!"
    link = f"https://wa.me/{phone}?text={urllib.parse.quote(mensaje)}"
    webbrowser.open(link)
    return True
