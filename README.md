# Impulso Smart — POS de Escritorio (Tkinter)

Sistema de **Punto de Venta (POS)**, **gestión de inventario fraccional** y **control financiero de caja** para comercios minoristas de alta rotación: pollerías, granjas, verdulerías, fiambrerías y autoservicios.

Funciona con una **arquitectura dual sobre la misma base de datos**:

| Capa | Tecnología | Uso |
|---|---|---|
| **Escritorio (100 % offline)** | CustomTkinter + SQLAlchemy | Mostrador: ventas por teclado y lector de códigos, caja, inventario, clientes, proveedores, devoluciones |
| **Panel web** | Django | Administración, reportes, POS web, ventas y caja desde el navegador |

Ambas capas comparten el **mismo núcleo de reglas** (`core/`): conversiones decimales, costo promedio ponderado, ganancia neta, arqueo de caja y respaldos. Por eso un cálculo da exactamente lo mismo desde el escritorio que desde la web.

---

## Características principales

- **Precisión numérica estricta (`Decimal`).** Cantidades con 3 decimales (`DECIMAL(10,3)`, pesaje al gramo: `1.250 kg`) y montos con 2 (`DECIMAL(10,2)`), sin errores de coma flotante. Acepta coma o punto (`0,750` = `0.750`).
- **Desposte dinámico (SPEC-INV-02).** Nunca se bloquea una venta por falta de stock teórico: el faltante se registra como ajuste automático (`ADJ`), el stock queda en `0.000` y el ajuste aparece en el cierre de caja para auditarlo.
- **Costo Promedio Ponderado — CPP (SPEC-SUP-07).** Al ingresar mercadería, el costo unitario se recalcula como `(stock × costo + entrante × costo entrante) / (stock + entrante)`, con vista previa antes de confirmar.
- **Pagos mixtos y Cuenta Corriente (SPEC-POS-08).** Un ticket puede dividirse entre Efectivo, Transferencia / QR, Tarjetas y Cuenta Corriente ("fiado"). El límite de crédito se controla solo sobre la parte fiada, el Consumidor Final no puede fiar, y los cobros de deuda emiten recibo.
- **Cierre de caja y Ganancia Neta Real (SPEC-FIN-06 / 07).** El cajero declara el efectivo contado y recién entonces ve la diferencia. Una sola fórmula de arqueo para web y escritorio:
  `Efectivo esperado = inicial + ventas efectivo + cobros de deuda efectivo − reintegros de devoluciones efectivo − gastos`.
  Rentabilidad real por turno o rango de fechas: `Ventas netas − CMV − Gastos − Mermas valorizadas`, exportable a Excel o CSV.
- **Mermas y devoluciones.** Bajas valorizadas al costo vigente; devoluciones parciales o totales que reintegran stock, acreditan en Cuenta Corriente hasta lo fiado y descuentan del arqueo el reintegro al cliente.
- **Respaldos automáticos en caliente (SPEC-BACKUP-01).** Copia diaria al iniciar y al cerrar caja (se conservan las 15 más recientes), copia antes de cada migración y exportación en 1 clic a un pendrive.
- **Tickets térmicos** de 58 mm o 80 mm en texto plano, con vista previa e impresión.
- **Zona horaria del negocio** (`America/Argentina/Buenos_Aires`): la base guarda UTC y el día comercial va de 00:00 a 23:59 hora local en ambas capas.

---

## Arquitectura del proyecto

```
├── launcher.py            # Punto de entrada: escritorio (por defecto) o --web
├── login_gui.py           # Login y ciclo login → Dashboard → cerrar sesión
├── gui_main.py            # Interfaz CustomTkinter (sin acceso directo a la base)
├── business_logic.py      # Reglas de negocio del escritorio (SQLAlchemy)
├── db_manager.py          # Modelos SQLAlchemy espejo de las tablas de Django
├── ticket_printer.py      # Tickets y recibos en texto plano + impresión
├── report_export.py       # Exportación de rentabilidad a Excel / CSV
├── core/                  # Núcleo compartido (sin dependencias de UI)
│   ├── stock_math.py      #   Decimal, validación de cantidades, CPP, tope de crédito
│   ├── cash.py            #   Fórmula única del arqueo de caja
│   ├── profitability.py   #   Ganancia Neta Real
│   ├── timeutils.py       #   Zona horaria del negocio (UTC ↔ local)
│   ├── backup_manager.py  #   Respaldos con rotación
│   └── bootstrap.py       #   Migraciones + datos base + usuario inicial
├── products/ sales/ finance/ customers/ suppliers/   # Apps Django (modelos y migraciones = esquema)
├── pos_system/            # Configuración de Django
├── templates/ static/     # Panel web
├── desktop_tests.py       # Pruebas de la capa de escritorio
├── gui_smoke_test.py      # Prueba de humo de la interfaz real
├── prebuild_check.py      # Verificación previa al empaquetado
└── ImpulsoSmart.spec      # Receta de PyInstaller
```

**Django es dueño del esquema:** toda columna nueva se crea con una migración de Django y se espeja en `db_manager.py`. Un test verifica columna por columna que ambos coincidan.

---

## Requisitos e instalación

**Requisitos:** Python **3.11 o 3.12** (recomendado; 3.10 funciona para la web y las pruebas sin interfaz) y Git.

### Linux (Debian / Ubuntu / Mint)

```bash
sudo apt install python3-tk python3-venv
git clone https://github.com/Nicolas230493/Impulso-Smart-POS-Tkinter.git
cd Impulso-Smart-POS-Tkinter
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Windows

Instalar Python desde [python.org](https://www.python.org/downloads/) (marcar *Add Python to PATH*; ya incluye Tk).

```powershell
git clone https://github.com/Nicolas230493/Impulso-Smart-POS-Tkinter.git
cd Impulso-Smart-POS-Tkinter
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

---

## Uso

### Modo escritorio (por defecto)

```bash
python launcher.py
```

El **primer arranque** prepara todo solo:

1. Crea la base `db.sqlite3` y aplica las migraciones (si ya hay datos, antes guarda una copia en `backups/`).
2. Siembra los medios de pago (Efectivo, Transferencia / QR, Tarjeta Débito, Tarjeta Crédito, Cuenta Corriente) y el cliente **Consumidor Final**.
3. Si no existe ningún usuario, crea **`admin` / `admin`**. Cambiá esa contraseña antes de usarlo en un comercio.
4. Crea el respaldo diario.

### Modo servidor web (Django)

```bash
python launcher.py --web
```

Abre `http://127.0.0.1:8000`. Usa la misma base y los mismos usuarios que el escritorio.

---

## Atajos de teclado del mostrador (pantalla Ventas)

| Tecla | Acción |
|---|---|
| `F2` | Ir al buscador (selecciona el texto) |
| `F4` | Ir al campo **Cant. / Kg** para cargar el peso |
| `Enter` | Agregar al carrito: código de barras / SKU exacto o resultado único (desde Cant./Kg agrega el primer resultado) |
| `F5` / `F12` | Cobro rápido en **Efectivo** |
| `F6` | **Pago mixto** |
| `F8` | **Historial / Devoluciones** (reimprimir ticket, devolver) |
| `Supr` | Quitar el último ítem del carrito |
| `Esc` | Vaciar el carrito (con confirmación) |

Flujo típico con lector de códigos: `F4` → `1,250` → escanear (el lector envía `Enter`) → `F5`.

---

## Pruebas y control de calidad

```bash
python prebuild_check.py            # dependencias, arquitectura, .spec, migraciones y ambas suites
python -W error desktop_tests.py    # capa de escritorio sobre una base temporal (cualquier advertencia es error)
python -W error manage.py test      # apps Django
python gui_smoke_test.py            # recorre la interfaz real (requiere pantalla)
```

Ninguna prueba toca la base real: todas usan bases temporales.

---

## Compilar el ejecutable (PyInstaller)

```bash
python prebuild_check.py                  # debe terminar en "OK" en todas las verificaciones
pyinstaller --noconfirm ImpulsoSmart.spec
```

El resultado queda en **`dist/ImpulsoSmart/`** (`ImpulsoSmart.exe` en Windows, `ImpulsoSmart` en Linux). Copiá esa carpeta completa a la PC del comercio: `.env`, la base y `backups/` se crean junto al ejecutable en el primer arranque, y `tickets/` con la primera venta. Con `ImpulsoSmart --web` el ejecutable levanta el panel web.

**Importante:**

- **PyInstaller no hace compilación cruzada:** para obtener el `.exe` hay que compilar **en Windows**, siguiendo los pasos de instalación de Windows.
- **Puesta en producción:**
  - Cambiá la contraseña de `admin` desde el panel web (`/admin`).
  - Creá un usuario por cajero: cada uno opera su propia caja.
  - Verificá que la carpeta `backups/` se esté generando.
  - Llevá periódicamente una copia a un pendrive con *Configuración → Exportar copia a carpeta / pendrive*.
