"""
Vector store
============
The two Chroma collections and the rules that hold for both: cosine distance, and no
embedding function of their own, so that `embeddings.py` stays the only route to a model.
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

    `embedding_function=None` has to be passed as an argument — declared inside the
    configuration it is ignored and Chroma falls back to a model of its own.
    """
    return client().get_or_create_collection(
        name, configuration=CONFIGURATION, embedding_function=None
    )


def replace(name: str):
    """The same collection, emptied first, so a withdrawn product cannot stay searchable."""
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
