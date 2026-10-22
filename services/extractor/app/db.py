from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import config

_pool: ConnectionPool | None = None


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(config.PG_DSN, min_size=1, max_size=4, kwargs={"autocommit": True, "row_factory": dict_row}, open=True)
    return _pool


def one(sql: str, params=()):
    with pool().connection() as c:
        return c.execute(sql, params).fetchone()


def execute(sql: str, params=()):
    with pool().connection() as c:
        c.execute(sql, params)


def settings() -> dict:
    with pool().connection() as c:
        return {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM settings").fetchall()}
