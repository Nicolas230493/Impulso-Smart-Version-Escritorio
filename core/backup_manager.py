"""Respaldos de la base SQLite: diario automático con rotación y copias manuales (ej. a un pendrive).

Usa la API de backup de sqlite3, segura en caliente aunque la app tenga conexiones abiertas.
Sin dependencias de Django: lo usan el escritorio (business_logic), la web (finance) y el arranque (bootstrap).
"""
import re
import sqlite3
from pathlib import Path

from core.timeutils import local_now

PREFIX = "impulso_smart"
KEEP = 15
NAME_RE = re.compile(rf"^{PREFIX}_(\d{{8}})_(\d{{6}})(?:_\d+)?\.sqlite3$")


def backups_dir(db_path):
    """Carpeta backups/ junto a la base (en el ejecutable: junto al .exe)."""
    return Path(db_path).parent / "backups"


def _is_file_db(db_path):
    path = str(db_path)
    return bool(path) and ":memory:" not in path and "mode=memory" not in path and Path(path).is_file()


def create_backup(db_path, dest_dir=None, prefix=PREFIX):
    """Copia consistente de la base como <prefix>_YYYYMMDD_HHMMSS.sqlite3 (hora del negocio). Devuelve la ruta."""
    if not _is_file_db(db_path) or Path(db_path).stat().st_size == 0:
        raise FileNotFoundError(f"No hay base de datos para respaldar en {db_path}.")
    dest_dir = Path(dest_dir) if dest_dir else backups_dir(db_path)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = local_now().strftime("%Y%m%d_%H%M%S")
    dest = dest_dir / f"{prefix}_{stamp}.sqlite3"
    n = 1
    while dest.exists():  # dos copias en el mismo segundo
        dest = dest_dir / f"{prefix}_{stamp}_{n}.sqlite3"
        n += 1
    src = sqlite3.connect(str(db_path))  # backup() solo lee del origen
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("La copia no pasó el control de integridad.")
    finally:
        dst.close()
        src.close()
    return dest


def list_backups(dest_dir):
    """Respaldos automáticos de la carpeta, del más nuevo al más viejo."""
    dest_dir = Path(dest_dir)
    if not dest_dir.is_dir():
        return []
    return sorted((p for p in dest_dir.iterdir() if NAME_RE.match(p.name)), key=lambda p: p.name, reverse=True)


def rotate_backups(dest_dir, keep=KEEP):
    """Conserva los `keep` respaldos más nuevos; borra el resto. Devuelve los borrados."""
    removed = list_backups(dest_dir)[keep:]
    for path in removed:
        path.unlink()
    return removed


def ensure_daily_backup(db_path, dest_dir=None, keep=KEEP):
    """Si todavía no hay respaldo de hoy, lo crea y aplica la rotación. Devuelve la ruta o None."""
    if not _is_file_db(db_path) or Path(db_path).stat().st_size == 0:
        return None  # base en memoria (tests) o instalación nueva sin datos
    dest_dir = Path(dest_dir) if dest_dir else backups_dir(db_path)
    today = local_now().strftime("%Y%m%d")
    if any(NAME_RE.match(p.name).group(1) == today for p in list_backups(dest_dir)):
        return None
    path = create_backup(db_path, dest_dir)
    rotate_backups(dest_dir, keep)
    return path
