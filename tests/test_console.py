import pytest

from services.data_service import console


@pytest.mark.parametrize(
    "sql",
    [
        "delete from products",
        "select 1; drop table products",
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


def test_the_connection_itself_refuses_to_write():
    """The reader is the first guard, not the only one."""
    with console._connect() as db:
        with pytest.raises(Exception, match="readonly|read-only"):
            db.execute("delete from products")
