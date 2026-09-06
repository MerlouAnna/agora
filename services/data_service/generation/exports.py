"""
How the source systems write a record down
==========================================
None of them agree. The SKU is whatever somebody typed into the ERP, the price is written
three ways depending on which export produced it, and a product the warehouse has never
registered simply has no row at all.

The catalogue file is clean, so this is where that disagreement now lives: a generation run
writes its rows the way the real exports write them, and the normalizer has something to do
on live data instead of only on a fixture. Everything here is driven by the run's own
generator, so the same seed produces the same mess.
"""

import random

UNREADABLE_PRICE = "N/A"
UNREADABLE_QUANTITY = "-"


def scatter(
    erp: list[dict], pricing: list[dict], stock: list[dict], rng: random.Random
) -> tuple[list[dict], list[dict], list[dict]]:
    """Rewrite clean rows the way the three systems would have exported them.

    Args:
        erp: Product rows, as the code built them.
        pricing: Price rows, one per product, the amount still a plain number.
        stock: Stock rows, one per warehouse a product is held in.
        rng: The run's generator, so the mess is reproducible from the seed.

    Returns:
        The same three lists, spelled the way the sources spell them.
    """
    return _erp(erp, rng), _pricing(pricing, rng), _stock(stock, rng)


def _erp(rows: list[dict], rng: random.Random) -> list[dict]:
    return [dict(row, item_code=_typed(row["item_code"], rng)) for row in rows]


def _typed(sku: str, rng: random.Random) -> str:
    """A SKU as somebody typed it: without the dash, with a space, with the field padded."""
    roll = rng.random()
    if roll < 0.12:
        return sku.replace("-", "").lower()
    if roll < 0.20:
        return "  " + sku
    if roll < 0.26:
        return sku.replace("-", " ")
    return sku


def _pricing(rows: list[dict], rng: random.Random) -> list[dict]:
    written = []

    for index, row in enumerate(rows):
        amount = float(row["list_price"])
        code = row["product_code"]
        written.append(
            dict(
                row,
                product_code=code + " " if rng.random() < 0.15 else code,
                list_price=UNREADABLE_PRICE
                if rng.random() < 0.03
                else _amount(amount, index),
            )
        )

    return written


def _amount(value: float, index: int) -> str:
    """The same number as the ERP writes it, as the shop writes it, as the export writes it."""
    if index % 3 == 0:
        return f"€ {value:.2f}".replace(".", ",")
    if index % 3 == 1:
        return f"{value:.2f}"
    return f"{value:.2f} EUR".replace(".", ",")


def _stock(rows: list[dict], rng: random.Random) -> list[dict]:
    written = []

    for row in rows:
        if rng.random() < 0.05:
            # The warehouse system has no record of this one, so its stock stays unknown.
            continue

        sku = row["sku"]
        written.append(
            dict(
                row,
                sku=sku.replace("-", " ") if rng.random() < 0.25 else sku,
                qty_available=UNREADABLE_QUANTITY
                if rng.random() < 0.03
                else row["qty_available"],
            )
        )

    return written
