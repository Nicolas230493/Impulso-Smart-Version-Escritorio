import os
import sys

import django

# Configurar Django antes de importar nada que use la autenticación
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pos_system.settings')
if not django.apps.apps.ready:
    django.setup()

import customtkinter as ctk
from django.contrib.auth import authenticate

from core.timeutils import local_now
from db_manager import db
from gui_main import AfterCleanupMixin, DashboardApp

def prepare_database():
    # Migraciones pendientes (con respaldo previo) + medios de pago y Consumidor Final
    from core.bootstrap import prepare_database as bootstrap_database
    bootstrap_database(db)

def check_admin_exists():
    from core.bootstrap import ensure_initial_admin
    return ensure_initial_admin()

class LoginApp(AfterCleanupMixin, ctk.CTk):
    def __init__(self):
        super().__init__()
        self._running = True
        self.authenticated_user = None  # (id, username) tras un login correcto
        
        self.title("Impulso Smart - Autenticación")
        self.geometry("450x650")
        self.configure(fg_color="#F3F4F6")
        
        self.eval('tk::PlaceWindow . center')
        
        # Frame Principal (Tarjeta)
        self.main_frame = ctk.CTkFrame(self, width=380, height=520, corner_radius=25, fg_color="white")
        self.main_frame.place(relx=0.5, rely=0.5, anchor="center")
        
        # Header Branding
        icon_box = ctk.CTkFrame(self.main_frame, width=60, height=60, corner_radius=12, fg_color="#3B82F6")
        icon_box.pack(pady=(40, 10))
        # Sin emoji a color: Tk 8.6 en Linux aborta al dibujar fuentes de emoji (Noto Color Emoji)
        ctk.CTkLabel(icon_box, text="IS", font=ctk.CTkFont(size=24, weight="bold"), text_color="white").pack(expand=True)
        
        ctk.CTkLabel(self.main_frame, text="Impulso Smart", font=ctk.CTkFont(size=24, weight="bold"), text_color="#1F2937").pack()
        ctk.CTkLabel(self.main_frame, text="Gestión de Ventas e Inventario", font=ctk.CTkFont(size=14), text_color="gray").pack(pady=(0, 20))
        
        # Inputs
        self.user_entry = ctk.CTkEntry(self.main_frame, placeholder_text="Usuario", height=45, width=300)
        self.user_entry.pack(pady=10)
        
        self.pass_entry = ctk.CTkEntry(self.main_frame, placeholder_text="••••••••", show="*", height=45, width=300)
        self.pass_entry.pack(pady=10)
        for entry in (self.user_entry, self.pass_entry):
            entry.bind("<Return>", lambda e: self.validate_login())
        self.after(150, self.user_entry.focus_set)
        
        # Botón
        ctk.CTkButton(self.main_frame, text="INGRESAR AL SISTEMA", height=50, width=300, 
                      fg_color="#4D2CFA", font=ctk.CTkFont(weight="bold"),
                      command=self.validate_login).pack(pady=20)
        
        # Feedback y Reloj
        self.error_label = ctk.CTkLabel(self.main_frame, text="", text_color="red")
        self.error_label.pack()
        
        self.clock_label = ctk.CTkLabel(self.main_frame, text="", font=ctk.CTkFont(size=11), text_color="gray")
        self.clock_label.pack(side="bottom", pady=40)
        self.update_clock()
        
        ctk.CTkLabel(self.main_frame, text="© 2026 Impulso Digital Sgo", font=ctk.CTkFont(size=10), text_color="gray").pack(side="bottom", pady=10)

    def update_clock(self):
        if self._running:
            now = local_now().strftime("%d/%m/%Y - %H:%M")
            if self.clock_label.winfo_exists():
                self.clock_label.configure(text=now)
            self.clock_loop = self.after(1000, self.update_clock)

    def validate_login(self):
        username = self.user_entry.get()
        password = self.pass_entry.get()
        
        user = authenticate(username=username, password=password)
        
        if user is not None:
            # main() abre el Dashboard al terminar este mainloop (sin mainloops anidados)
            self.authenticated_user = (user.id, user.get_username())
            self.destroy()
        else:
            self.error_label.configure(text="Usuario o contraseña inválidos")
            self.user_entry.delete(0, 'end')
            self.pass_entry.delete(0, 'end')

    def destroy(self):
        self._running = False
        if hasattr(self, 'clock_loop'):
            try:
                self.after_cancel(self.clock_loop)
            except Exception:
                pass
        super().destroy()

def main():
    """Punto de entrada del escritorio: base lista, login y Dashboard; 'Cerrar sesión' vuelve al login."""
    prepare_database()
    check_admin_exists()
    while True:
        login = LoginApp()
        login.mainloop()
        if not login.authenticated_user:
            break  # ventana de login cerrada
        user_id, username = login.authenticated_user
        dashboard = DashboardApp(username=username, user_id=user_id, accent="#4D2CFA")
        dashboard.mainloop()
        if not dashboard.logout_requested:
            break
    return 0

if __name__ == "__main__":
    sys.exit(main())
