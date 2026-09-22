"""Connection helper with optional transaction composition for API workflows."""
from contextlib import contextmanager
from contextvars import ContextVar

import psycopg2
from app.core.config import settings

_current = ContextVar('database_transaction', default=None)


class _BorrowedConnection:
    """Services may close/context-manage a borrowed connection, but only its
    transaction owner may commit. Exceptions propagate to that owner."""
    def __init__(self, connection):
        self.connection = connection

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def close(self):
        pass

    def commit(self):
        raise RuntimeError('Commit belongs to the outer transaction')


def get_connection():
    active = _current.get()
    return _BorrowedConnection(active) if active is not None else psycopg2.connect(settings.database_url)


@contextmanager
def transaction():
    """Compose existing service writes into one atomic domain/outbox commit.

    Use only for synchronous DB work; do not share the connection with threads.
    """
    if _current.get() is not None:
        yield _BorrowedConnection(_current.get())
        return
    conn = psycopg2.connect(settings.database_url)
    token = _current.set(conn)
    try:
        with conn:
            yield conn
    finally:
        _current.reset(token)
        conn.close()
