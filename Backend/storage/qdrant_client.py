import logging
from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    VectorParams,
)

import config

logger = logging.getLogger(__name__)

COLLECTION_NAME = config.COLLECTION_NAME


@lru_cache(maxsize=1)
def get_client() -> QdrantClient:
    """Lazily build the client. Refuses to run without QDRANT_URL — the
    qdrant-client default would otherwise quietly point at localhost.
    QDRANT_URL=:memory: uses an ephemeral in-process store (dev / tests)."""
    if not config.QDRANT_URL:
        raise RuntimeError("QDRANT_URL is not set.")
    if config.QDRANT_URL == ":memory:":
        return QdrantClient(":memory:")
    return QdrantClient(url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY)


def _doc_filter(doc_id: str) -> Filter:
    return Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))])


def setup_collection() -> None:
    """Ensure the collection (with separate text and image vector spaces) and
    its payload indexes exist."""
    client = get_client()
    existing = {c.name for c in client.get_collections().collections}

    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={
                config.TEXT_VECTOR: VectorParams(size=config.TEXT_DIM, distance=Distance.COSINE),
                config.IMAGE_VECTOR: VectorParams(size=config.IMAGE_DIM, distance=Distance.COSINE),
            },
        )
        logger.info("Qdrant collection '%s' created", COLLECTION_NAME)
    else:
        vectors = client.get_collection(COLLECTION_NAME).config.params.vectors
        if not isinstance(vectors, dict) or {config.TEXT_VECTOR, config.IMAGE_VECTOR} - set(vectors):
            raise RuntimeError(
                f"Collection '{COLLECTION_NAME}' exists with an incompatible vector layout. "
                "Delete it (python delete_qdrant.py) or set QDRANT_COLLECTION to a new name."
            )
        logger.info("Collection '%s' already exists", COLLECTION_NAME)

    # Index creation is idempotent in Qdrant.
    for field, schema in (("doc_id", "keyword"), ("page", "integer"), ("type", "keyword")):
        client.create_payload_index(
            collection_name=COLLECTION_NAME, field_name=field, field_schema=schema
        )


def count_document_points(doc_id: str) -> int:
    return get_client().count(
        collection_name=COLLECTION_NAME, count_filter=_doc_filter(doc_id), exact=True
    ).count


def delete_document_points(doc_id: str) -> None:
    get_client().delete(
        collection_name=COLLECTION_NAME, points_selector=_doc_filter(doc_id)
    )
