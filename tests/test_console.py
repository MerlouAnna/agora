import sqlite3

import pytest

from services.data_service import console


@pytest.mark.parametrize(
    "sql",
    [
        "delete from products",
        "update prices set amount = 0",
        "attach database 'other.db' as other",
        "pragma table_info(products)",
        "   ",
    ],
)
def test_only_a_select_gets_through(sql):
    with pytest.raises(ValueError):
        console._read(sql)


def test_a_select_survives_untouched():
    sql = "select sku from products where category = 'POWER'"

    assert console._read(f"  {sql} ;  ") == sql


def test_a_word_inside_the_query_is_not_a_verb():
    """DROP in a literal and REPLACE as a function are still an honest SELECT."""
    found = console.run(
        "select replace(sku, '-', '') as code from products"
        " where description like '%drop%' or sku like '%;%' or sku = 'PWR-1000'"
    )

    assert found["columns"] == ["code"]
    assert found["rows"] == [["PWR1000"]]


def test_one_enormous_value_cannot_be_asked_for():
    """MAX_ROWS bounds how many values come back, not how large one of them is."""
    with pytest.raises(sqlite3.Error):
        console.run("select zeroblob(500000000)")


def test_the_connection_itself_refuses_to_write():
    """The reader is the first guard, not the only one."""
    with console._connect() as db:
        with pytest.raises(Exception, match="readonly|read-only"):
            db.execute("delete from products")


@pytest.mark.parametrize(
    "sql",
    [
        "select 1; drop table products",
        "with x as (select 1) insert into products (sku) values ('X')",
    ],
)
def test_what_gets_past_the_reader_is_stopped_by_sqlite(sql):
    with pytest.raises(sqlite3.Error):
        console.run(sql)
