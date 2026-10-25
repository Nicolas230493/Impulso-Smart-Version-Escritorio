# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

added_files = [
    ('static', 'static'),
    ('templates', 'templates'),
    # media/ no se empaqueta: launcher.py la crea junto al ejecutable (MEDIA_ROOT = DATA_DIR / 'media')
    ('logo.ico', '.'),
]
# Temas/fuentes de CustomTkinter y base de zonas horarias (Windows no trae una propia)
added_files += collect_data_files('customtkinter') + collect_data_files('tzdata')

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=added_files,
    hiddenimports=[
        'waitress',
        'django.contrib.admin',
        'django.contrib.auth',
        'django.contrib.contenttypes',
        'django.contrib.sessions',
        'django.contrib.messages',
        'django.contrib.staticfiles',
        'widget_tweaks',
        'core',
        'suppliers',
        'products',
        'sales',
        'customers',
        'finance',
        'reportlab',
        'pandas',
        'openpyxl',
        # App de escritorio (launcher -> login_gui -> gui_main)
        'login_gui',
        'gui_main',
        'business_logic',
        'db_manager',
        'ticket_printer',
        'report_export',
        'whatsapp_utils',
        'customtkinter',
        'sqlalchemy.dialects.sqlite',
        'barcode',
        'PIL',
        'tzdata',
        # Módulos compartidos de core/ (importados en tiempo de ejecución por el escritorio y la web)
        'core.bootstrap',
        'core.backup_manager',
        'core.cash',
        'core.middleware',  # se carga por nombre desde settings.MIDDLEWARE
        'core.profitability',
        'core.stock_math',
        'core.timeutils',
        'finance.cash',
        'finance.reports',
        'products.services',
        'sales.services',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ImpulsoSmart',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='logo.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ImpulsoSmart',
)
