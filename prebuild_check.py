"""Verificación previa al empaquetado (PyInstaller). Uso: python prebuild_check.py [--skip-tests]

Comprueba dependencias, arquitectura (GUI desacoplada de la base), punto de entrada del .spec,
consistencia de migraciones y corre las dos suites de tests. Sale con código 1 si algo falla.
"""
import ast
import importlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# módulo a importar -> paquete de requirements.txt (None = viene con Python / del sistema)
DEPENDENCIES = {
    "django": "Django", "reportlab": "reportlab", "widget_tweaks": "django-widget-tweaks", "dotenv": "python-dotenv",
    "pandas": "pandas", "openpyxl": "openpyxl", "waitress": "waitress", "sqlalchemy": "SQLAlchemy",
    "customtkinter": "customtkinter", "packaging": "packaging", "PIL": "pillow", "barcode": "python-barcode",
    "tzdata": "tzdata", "tkinter": None, "PyInstaller": "pyinstaller",
}

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"[{'OK ' if ok else 'ERR'}] {name}" + (f" — {detail}" if detail else ""))


def check_dependencies():
    for module, package in DEPENDENCIES.items():
        try:
            importlib.import_module(module)
            check(f"dependencia {module}", True)
        except Exception as e:
            # Si falta una dependencia transitiva (ej. customtkinter sin tkinter), sugerir esa
            missing = getattr(e, "name", None)
            if missing and missing != module and missing in DEPENDENCIES:
                package = DEPENDENCIES[missing]
            hint = f"pip install {package}" if package else "instalar soporte Tk del sistema (ej. sudo apt install python3-tk)"
            check(f"dependencia {module}", False, f"{e.__class__.__name__}: {e} → {hint}")


def check_gui_decoupled():
    source = (ROOT / "gui_main.py").read_text(encoding="utf-8")
    offenders = [f"línea {i}" for i, line in enumerate(source.splitlines(), 1)
                 if re.search(r"\bdb_manager\b|get_session\s*\(", line)]
    check("gui_main.py sin db_manager ni get_session()", not offenders, ", ".join(offenders))


def check_entry_point():
    """Los nombres que el script del .spec importa de módulos locales deben existir (sin importar la GUI)."""
    spec = (ROOT / "ImpulsoSmart.spec").read_text(encoding="utf-8")
    scripts = re.findall(r"Analysis\(\s*\[([^\]]*)\]", spec)
    for script in re.findall(r"'([^']+\.py)'", scripts[0] if scripts else ""):
        path = ROOT / script
        if not path.exists():
            check(f"entry point {script}", False, "no existe")
            continue
        problems = []
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module and (ROOT / f"{node.module}.py").exists():
                module_tree = ast.parse((ROOT / f"{node.module}.py").read_text(encoding="utf-8"))
                defined = {n.name for n in module_tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef))}
                defined |= {t.id for n in module_tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
                defined |= {(a.asname or a.name).split('.')[0] for n in module_tree.body
                            if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
                problems += [f"{node.module}.{a.name}" for a in node.names if a.name not in defined]
        check(f"entry point {script}: imports locales resuelven", not problems,
              f"no existen: {', '.join(problems)}" if problems else "")


def check_spec_modules():
    """Los módulos compartidos de core/ (y los services de las apps) deben figurar en hiddenimports del .spec."""
    spec = (ROOT / "ImpulsoSmart.spec").read_text(encoding="utf-8")
    skip = {"__init__", "admin", "apps", "models", "views", "urls", "tests"}
    modules = [f"core.{p.stem}" for p in (ROOT / "core").glob("*.py") if p.stem not in skip]
    modules += [f"{p.parent.name}.{p.stem}" for p in ROOT.glob("*/services.py")]
    missing = [m for m in sorted(modules) if f"'{m}'" not in spec]
    check("módulos compartidos declarados en ImpulsoSmart.spec", not missing, ", ".join(missing))


def check_spec_datas():
    """Cada carpeta/archivo de datos del .spec debe existir y estar versionado (en un clon limpio
    una carpeta vacía no existe y PyInstaller falla: pasó con static/ y media/)."""
    spec = (ROOT / "ImpulsoSmart.spec").read_text(encoding="utf-8")
    block = spec.split("added_files = [", 1)[1].split("]", 1)[0]
    problems = []
    for src in re.findall(r"\(\s*'([^']+)'\s*,", block):
        if not (ROOT / src).exists():
            problems.append(f"{src} (no existe)")
        elif (ROOT / ".git").exists():
            tracked = subprocess.run(["git", "ls-files", "--", src], cwd=ROOT, capture_output=True, text=True).stdout.strip()
            if not tracked:
                problems.append(f"{src} (sin archivos versionados)")
    check("datos del .spec presentes en un clon limpio", not problems, ", ".join(problems))


def check_gitignore():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    missing = [p for p in ("db.sqlite3", "*.sqlite3", "backups/", "tickets/", ".env", "build/", "dist/") if p not in ignored]
    check(".gitignore excluye base, respaldos y tickets", not missing, ", ".join(missing))


SOURCE_FILES = ["launcher.py", "login_gui.py", "gui_main.py", "business_logic.py", "db_manager.py", "ticket_printer.py",
                "report_export.py", "whatsapp_utils.py", "manage.py", "ImpulsoSmart.spec", "requirements.txt", "logo.ico",
                "desktop_tests.py", "prebuild_check.py", "gui_smoke_test.py", "README.md"]


def check_sources_not_ignored():
    """Ningún archivo fuente (ni migraciones ni core/) puede quedar excluido por .gitignore (pasó con *.spec)."""
    if not (ROOT / ".git").exists():
        check("fuentes no ignoradas por git", True, "sin repositorio git: control omitido")
        return
    paths = SOURCE_FILES + [str(p.relative_to(ROOT)) for p in ROOT.glob("*/migrations/*.py")]
    paths += [str(p.relative_to(ROOT)) for p in (ROOT / "core").glob("*.py")]
    proc = subprocess.run(["git", "check-ignore", "--stdin"], cwd=ROOT, input="\n".join(paths), capture_output=True, text=True)
    ignored = proc.stdout.split()
    check("fuentes no ignoradas por git", not ignored, ", ".join(ignored))


def run(name, args):
    proc = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True)
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-3:]
    check(name, proc.returncode == 0, " | ".join(tail) if proc.returncode else "")


if __name__ == "__main__":
    check_dependencies()
    check_gui_decoupled()
    check_entry_point()
    check_spec_modules()
    check_gitignore()
    check_sources_not_ignored()
    check_spec_datas()
    run("manage.py check (sin advertencias)", ["manage.py", "check", "--fail-level", "WARNING"])
    run("migraciones al día (makemigrations --check)", ["manage.py", "makemigrations", "--check", "--dry-run"])
    if "--skip-tests" not in sys.argv:
        run("desktop_tests.py", ["desktop_tests.py"])
        run("manage.py test", ["manage.py", "test", "core", "products", "sales", "finance", "customers"])
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} verificaciones OK")
    sys.exit(1 if failed else 0)
