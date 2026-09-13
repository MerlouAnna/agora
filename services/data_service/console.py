"""
SQL console
===========
Read-only access to the catalogue, for the questions the API does not answer.

Three things stand between a request and the database: the statement has to open as a
SELECT, the connection is one SQLite itself opened read-only, and SQLite is told to
authorize reads and nothing else while the statement runs. What comes back is bounded
twice, by the number of rows and by the size of a single value.

Nothing here goes through SQLAlchemy: the point is to run the caller's own SQL.
"""

import sqlite3
import time
from contextlib import closing

from services.data_service.database import DB_PATH

MAX_ROWS = 500
MAX_VALUE_BYTES = 100_000
TIMEOUT_SECONDS = 5

ALLOWED = (
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_RECURSIVE,
)

EXAMPLES = [
    "select category, count(*) as products from products group by category order by 2 desc",
    (
        "select p.sku, p.brand, pr.amount from products p"
        " join prices pr on pr.sku = p.sku order by pr.amount desc limit 10"
    ),
    "select key, count(*) as used from product_specs group by key order by 2 desc",
    "select warehouse, count(*) as skus, sum(quantity) as units from stock group by warehouse",
    "select sku from products where sku not in (select sku from stock)",
    (
        "select p.sku, s.value_num as watt from products p join product_specs s on s.sku = p.sku"
        " where s.key = 'watt' and s.value_num >= 1500 order by 2 desc"
    ),
]


def tables() -> list[dict]:
    """Every table, its columns, what it points at, and how many rows it holds."""
    with closing(_connect()) as db:
        found = []

        for (name,) in db.execute(
            "select name from sqlite_master where type = 'table'"
            " and name not like 'sqlite_%' order by name"
        ).fetchall():
            columns = [
                {
                    "name": row[1],
                    "type": row[2] or "TEXT",
                    "nullable": not row[3],
                    "primary_key": bool(row[5]),
                }
                for row in db.execute(f'pragma table_info("{name}")').fetchall()
            ]
            references = {
                row[3]: f"{row[2]}.{row[4]}"
                for row in db.execute(f'pragma foreign_key_list("{name}")').fetchall()
            }
            rows = db.execute(f'select count(*) from "{name}"').fetchone()[0]

            found.append(
                {
                    "name": name,
                    "rows": rows,
                    "columns": columns,
                    "references": references,
                }
            )

        return found


def run(sql: str, limit: int = 100) -> dict:
    """Run one SELECT and hand back what it found.

    Args:
        sql: The caller's statement, refused unless it is a single SELECT.
        limit: How many rows to return. The query itself is left alone and the rows are
            simply not read past this, which is more reliable than rewriting somebody
            else's SQL.

    Returns:
        The column names, the rows, how long it took, and whether there were more.

    Raises:
        ValueError: The statement is not something we are willing to run.
    """
    statement = _read(sql)
    limit = max(1, min(limit, MAX_ROWS))
    started = time.monotonic()

    with closing(_connect()) as db:
        deadline = started + TIMEOUT_SECONDS
        db.set_progress_handler(lambda: time.monotonic() > deadline, 2000)
        db.set_authorizer(_reads_only)

        cursor = db.execute(statement)
        columns = [column[0] for column in cursor.description or []]
        rows = cursor.fetchmany(limit + 1)

    more = len(rows) > limit
    return {
        "columns": columns,
        "rows": [[_plain(value) for value in row] for row in rows[:limit]],
        "row_count": min(len(rows), limit),
        "truncated": more,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


def _read(sql: str) -> str:
    """What we are willing to run, and why we are not willing to run the rest."""
    statement = sql.strip().rstrip(";").strip()

    if not statement:
        raise ValueError("there is no statement here")

    if not statement.lower().startswith(("select", "with")):
        raise ValueError("only SELECT is allowed, and WITH when it ends in one")

    return statement


def _reads_only(action, *_):
    """What SQLite is allowed to do while the caller's statement runs."""
    return sqlite3.SQLITE_OK if action in ALLOWED else sqlite3.SQLITE_DENY


def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise ValueError("there is no catalogue database yet — run the ingestion first")

    db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    # A row limit bounds how many values come back, not how large one of them is.
    db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_VALUE_BYTES)
    return db


def _plain(value):
    """Whatever SQLite handed back, in something JSON can carry."""
    return f"<{len(value)} bytes>" if isinstance(value, bytes) else value
