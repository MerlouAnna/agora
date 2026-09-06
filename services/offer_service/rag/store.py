"""
Vector store
============
The two Chroma collections and the rules that hold for both: cosine distance, and no
embedding function of their own.

A collection built without an embedding function cannot quietly embed anything — it
accepts vectors and refuses to invent them, which is what keeps `embeddings.py` the only
route to a model.
"""

import logging
from pathlib import Path

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.collection_configuration import CreateCollectionConfiguration
from chromadb.errors import NotFoundError

logger = logging.getLogger(__name__)

CHROMA_PATH = Path(__file__).resolve().parents[3] / "data" / "chroma"

PRODUCTS = "products"
POLICIES = "policies"

CONFIGURATION: CreateCollectionConfiguration = {"hnsw": {"space": "cosine"}}

_client = None


def client() -> ClientAPI:
    """The persistent client, opened once per process."""
    global _client

    if _client is None:
        CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        logger.info("opening the vector store at %s", CHROMA_PATH)
        _client = chromadb.PersistentClient(path=str(CHROMA_PATH))

    return _client


def collection(name: str):
    """One collection, created on first use.

    `embedding_function=None` has to be passed as an argument. Declaring it inside the
    configuration instead looks tidier and does the opposite: the collection falls back
    to Chroma's own model, downloads it, and fills the store with vectors from a model
    nobody chose.
    """
    return client().get_or_create_collection(
        name, configuration=CONFIGURATION, embedding_function=None
    )


def replace(name: str):
    """The same collection, emptied first.

    Indexing rebuilds rather than updates: a card whose product was deleted from the
    catalogue would otherwise stay searchable forever, and nothing here is expensive
    enough to justify working out the difference.
    """
    try:
        client().delete_collection(name)
    except NotFoundError:
        logger.info("no %s collection to replace", name)

    return collection(name)


def counts() -> dict[str, int]:
    """How many documents each collection holds. A collection never built reads as zero."""
    built = {existing.name for existing in client().list_collections()}
    return {
        name: collection(name).count() if name in built else 0
        for name in (PRODUCTS, POLICIES)
    }
