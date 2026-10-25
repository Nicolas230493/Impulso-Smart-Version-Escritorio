"""Zona horaria del negocio: una sola fuente para Django (settings.TIME_ZONE) y la app de escritorio.

La base guarda fechas en UTC sin offset (convención de Django con USE_TZ=True en SQLite);
se convierte a la hora del negocio solo para mostrar o para interpretar fechas que ingresa el usuario.
Sin dependencias de Django: se importa desde settings.py.
"""
import datetime
import os
from zoneinfo import ZoneInfo

BUSINESS_TIME_ZONE = os.getenv('TIME_ZONE', 'America/Argentina/Buenos_Aires')
BUSINESS_TZ = ZoneInfo(BUSINESS_TIME_ZONE)
UTC = datetime.timezone.utc


def utc_now():
    """Instante actual como UTC naive (lo que se guarda en la base)."""
    return datetime.datetime.now(UTC).replace(tzinfo=None)


def local_now():
    """Hora actual del negocio (naive), para mostrar o como valor por defecto en la UI."""
    return datetime.datetime.now(BUSINESS_TZ).replace(tzinfo=None)


def to_local(dt):
    """UTC guardado en la base -> hora del negocio (naive) para mostrar."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(BUSINESS_TZ).replace(tzinfo=None)


def local_to_utc(dt):
    """Hora del negocio ingresada por el usuario (naive) -> UTC naive para consultar la base."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BUSINESS_TZ)
    return dt.astimezone(UTC).replace(tzinfo=None)


def local_day_bounds(day):
    """[00:00:00, 23:59:59.999999] de un día del negocio, en UTC naive."""
    start = datetime.datetime.combine(day, datetime.time.min)
    end = datetime.datetime.combine(day, datetime.time.max)
    return local_to_utc(start), local_to_utc(end)
