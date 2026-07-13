"""Thin psycopg2 connection helper shared by services and the Celery worker."""

import psycopg2

from app.core.config import settings


def get_connection():
    """Opens a new psycopg2 connection to the configured database.

    Callers own the connection lifecycle (commit/close). Kept deliberately
    simple — a pool can slot in behind this function later without touching
    call sites.
    """
    return psycopg2.connect(settings.database_url)
