import logging
import uuid
from typing import List

from qdrant_client.models import PointStruct

import config
from ingestion.embedder import embed_images, embed_texts
from storage.qdrant_client import COLLECTION_NAME, delete_document_points, get_client

logger = logging.getLogger(__name__)

UPSERT_BATCH = 64


def upload_to_qdrant(blocks, doc_id: str) -> int:
    """
    Embed and store text, table and image blocks for one document.

    Text and tables go in the "text" vector space (MiniLM); images go in the
    "image" space (CLIP). Embedding is batched. Returns the number of points
    stored.
    """
    logger.info("Uploading '%s' into Qdrant collection = %s", doc_id, COLLECTION_NAME)

    # Idempotent: clears any partial earlier attempt for this doc_id.
    delete_document_points(doc_id)

    text_blocks = [b for b in blocks if b["type"] in ("text", "table")]
    image_blocks = [b for b in blocks if b["type"] == "image" and b.get("file_path")]

    points: List[PointStruct] = []

    # -- text + tables -------------------------------------------------------
    vectors = embed_texts([b["content"] for b in text_blocks])
    for block, vector in zip(text_blocks, vectors):
        payload = {
            "doc_id": doc_id,
            "type": block["type"],
            "page": block["page"],
            "content": block["content"],
        }
        if block["type"] == "table":
            payload["caption"] = block.get("caption", "Extracted Table")
            payload["table_data"] = block.get("table_data", [])
        points.append(
            PointStruct(id=str(uuid.uuid4()), vector={config.TEXT_VECTOR: vector}, payload=payload)
        )

    # -- images ----------------------------------------------------------------
    paths = [str(config.EXTRACTED_DIR / b["file_path"]) for b in image_blocks]
    for block, vector in zip(image_blocks, embed_images(paths)):
        if vector is None:
            continue
        points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector={config.IMAGE_VECTOR: vector},
                payload={
                    "doc_id": doc_id,
                    "type": "image",
                    "page": block["page"],
                    "caption": block.get("caption", "Extracted Figure"),
                    "file_path": block["file_path"],
                },
            )
        )

    client = get_client()
    for start in range(0, len(points), UPSERT_BATCH):
        client.upsert(collection_name=COLLECTION_NAME, points=points[start : start + UPSERT_BATCH])

    logger.info("Uploaded %d multimodal points successfully", len(points))
    return len(points)
