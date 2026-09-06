"""
SQL console
===========
Read-only access to the catalogue, for the questions the API does not answer.

Two things stand between a request and the database, because one of them is not enough.
The statement is read first and refused unless it is a single SELECT; then it runs on a
connection SQLite itself opened read-only, so a statement that talks its way past the
reader still cannot write. Keyword checks alone are a habit of being outsmarted.

Nothing here goes through SQLAlchemy: the point is to run the caller's own SQL.
"""

import logging
import re
import sqlite3
import time

from services.data_service.database import DB_PATH

logger = logging.getLogger(__name__)

MAX_ROWS = 500
TIMEOUT_SECONDS = 5

FORBIDDEN = (
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "replace",
    "attach",
    "detach",
    "pragma",
    "vacuum",
    "reindex",
    "begin",
    "commit",
    "rollback",
)

EXAMPLES = [
    "select category, count(*) as products from products group by category order by 2 desc",
    "select p.sku, p.brand, pr.amount from products p"
    " join prices pr on pr.sku = p.sku order by pr.amount desc limit 10",
    "select key, count(*) as used from product_specs group by key order by 2 desc",
    "select warehouse, count(*) as skus, sum(quantity) as units from stock group by warehouse",
    "select sku from products where sku not in (select sku from stock)",
    "select p.sku, s.value_num as watt from products p join product_specs s on s.sku = p.sku"
    " where s.key = 'watt' and s.value_num >= 1500 order by 2 desc",
]


def tables() -> list[dict]:
    """Every table, its columns, what it points at, and how many rows it holds."""
    with _connect() as db:
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

    with _connect() as db:
        deadline = started + TIMEOUT_SECONDS
        db.set_progress_handler(lambda: time.monotonic() > deadline, 2000)

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

    if ";" in statement:
        raise ValueError("one statement at a time")

    lowered = statement.lower()
    if not lowered.startswith(("select", "with")):
        raise ValueError("only SELECT is allowed, and WITH when it ends in one")

    for word in FORBIDDEN:
        if re.search(rf"\b{word}\b", lowered):
            raise ValueError(f"{word.upper()} is not allowed here")

    return statement


def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise ValueError("there is no catalogue database yet — run the ingestion first")

    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def _plain(value):
    """Whatever SQLite handed back, in something JSON can carry."""
    return f"<{len(value)} bytes>" if isinstance(value, bytes) else value
