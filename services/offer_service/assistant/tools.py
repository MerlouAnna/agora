"""
Assistant tools
===============
The three things the model may ask for, as plain functions, and the schema it is shown for
each. Nothing here decides anything: every result is a row of the catalogue or a section of
a business document, handed over as it is.
"""

import logging

from services.data_service.categories import Category
from services.offer_service.clients import catalog
from services.offer_service.rag import retriever

logger = logging.getLogger(__name__)

POLICY_SECTIONS = 4
PRODUCTS = 10

CATEGORIES = [one.value for one in Category]


def search_policies(question: str, subjects: tuple[str, ...] = ()) -> list[dict]:
    """The sections of the business documents that bear on a question about the terms.

    A datasheet section is about one product, so it comes back only when that product is
    one the conversation is about. The policies answer for everybody and always come back.
    """
    found, _ = retriever.search_policies(question, limit=POLICY_SECTIONS)
    return [
        {
            "document": one.metadata.get("document"),
            "title": one.metadata.get("title"),
            "section": one.metadata.get("section"),
            "text": one.text,
        }
        for one in found
        if one.metadata.get("kind") != "datasheet" or one.metadata.get("sku") in subjects
    ]


def product_stock(sku: str) -> dict | str:
    """Where one product is held and how much of it. A code the catalogue lacks says so.

    The sentence for a code that is not there is Greek, because it is read as it is.
    """
    code = sku.strip().upper()
    held = catalog.stock(code)
    if held is None:
        return f"Δεν υπάρχει προϊόν με κωδικό {code} στον κατάλογο"

    return held


def find_products(
    category: str, max_price: float | None = None, min_stock: int | None = None
) -> dict:
    """The first products of one category under a price and above a stock floor."""
    if category not in CATEGORIES:
        return {"error": f"category must be one of {', '.join(CATEGORIES)}"}

    rows = catalog.search(
        category=category, max_price=max_price, min_stock=min_stock, limit=PRODUCTS
    )
    return {
        "found": len(rows),
        "products": [
            {
                "sku": row["sku"],
                "description": row["description"],
                "price": row["price"],
                "stock_total": row["stock_total"],
            }
            for row in rows
        ],
    }


FUNCTIONS = {
    "search_policies": search_policies,
    "product_stock": product_stock,
    "find_products": find_products,
}

SCHEMAS = {
    "search_policies": {
        "description": (
            "Search the company's own documents — discount policy, delivery terms, warranty "
            "and returns, payment terms, and one datasheet per category — for the sections "
            "that answer a question. Use it for anything about terms, conditions, warranty, "
            "delivery, or what a datasheet says about a product."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question as asked, in Greek or English",
                }
            },
            "required": ["question"],
            "additionalProperties": False,
        },
    },
    "product_stock": {
        "description": "How many units of one product each warehouse holds, by product code.",
        "parameters": {
            "type": "object",
            "properties": {
                "sku": {"type": "string", "description": "The product code, like PSU-1018"}
            },
            "required": ["sku"],
            "additionalProperties": False,
        },
    },
    "find_products": {
        "description": (
            "List the products of one category, optionally under a list price and with at "
            "least so many units in stock across the warehouses. Returns up to ten, each "
            "with its price and total stock."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": CATEGORIES},
                "max_price": {"type": "number", "description": "Highest list price, in euro"},
                "min_stock": {
                    "type": "integer",
                    "description": (
                        "Lowest total stock across the warehouses. Set to 1 when the question "
                        "asks for products in stock: «με απόθεμα», «διαθέσιμα», «άμεσα "
                        "διαθέσιμα»"
                    ),
                },
            },
            "required": ["category"],
            "additionalProperties": False,
        },
    },
}


def run(name: str, arguments: dict, subjects: tuple[str, ...] = ()) -> dict | list | str:
    """One tool by name. A wrong name or argument is answered, not raised, so the model can fix it.

    `subjects` are the products the conversation is about, which the model does not choose
    and therefore does not pass.
    """
    function = FUNCTIONS.get(name)
    if function is None:
        return {"error": f"there is no tool called {name}"}

    if function is search_policies:
        arguments = arguments | {"subjects": subjects}

    try:
        return function(**arguments)
    except TypeError as exc:
        return {"error": f"{name} was called wrongly: {exc}"}
