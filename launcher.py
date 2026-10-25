"""Punto de entrada del ejecutable (ImpulsoSmart.spec).

Por defecto abre la app de escritorio (login + Dashboard Tkinter).
Con --web levanta el servidor Django (waitress) y abre el navegador.
"""
import multiprocessing
import os
import sys
import webbrowser

# El directorio del proyecto debe estar en sys.path para encontrar pos_system y las apps
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pos_system.settings')


def ensure_env_file():
    # Misma carpeta de datos que pos_system/settings.py, sin importarlo: settings lee el .env al
    # importarse y en el primer arranque todavía no existe.
    from pathlib import Path
    DATA_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(current_dir)
    (DATA_DIR / 'media').mkdir(exist_ok=True)
    env_path = DATA_DIR / '.env'
    if not env_path.exists():
        from django.core.management.utils import get_random_secret_key
        env_path.write_text(f"DEBUG=False\nSECRET_KEY={get_random_secret_key()}\nALLOWED_HOSTS=127.0.0.1,localhost\n")


def run_web(port=8000):
    import django
    django.setup()
    from waitress import serve
    from core.bootstrap import prepare_database
    from db_manager import db
    from pos_system.wsgi import application

    print("Verificando base de datos...")
    prepare_database(db)
    from core.bootstrap import ensure_initial_admin
    ensure_initial_admin()
    url = f"http://127.0.0.1:{port}"
    print(f"Servidor iniciado en {url}")
    webbrowser.open(url)
    serve(application, host='127.0.0.1', port=port, threads=4)


def run_desktop():
    from login_gui import main
    return main()


if __name__ == '__main__':
    multiprocessing.freeze_support()
    ensure_env_file()
    sys.exit(run_web() if '--web' in sys.argv else run_desktop())
