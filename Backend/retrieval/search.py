import logging
import re
from dataclasses import dataclass, field
from typing import List

from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

import config
from ingestion.embedder import embed_clip_text, embed_text
from storage.qdrant_client import COLLECTION_NAME, get_client

logger = logging.getLogger(__name__)

_PAGE_QUERY = re.compile(r"\bpage\s+(\d+)\b", re.IGNORECASE)


@dataclass
class RetrievalResult:
    context: str = ""
    visuals: List[dict] = field(default_factory=list)
    pages: List[int] = field(default_factory=list)  # every page that contributed


def _conditions(doc_id: str, block_types, page=None):
    conds = [
        FieldCondition(key="doc_id", match=MatchValue(value=doc_id)),
        FieldCondition(key="type", match=MatchAny(any=list(block_types))),
    ]
    if page is not None:
        conds.append(FieldCondition(key="page", match=MatchValue(value=page)))
    return conds


def _image_visual(point) -> dict | None:
    payload = point.payload or {}
    file_path = payload.get("file_path")
    if not file_path or not (config.EXTRACTED_DIR / file_path).is_file():
        return None
    return {
        "id": str(point.id),
        "type": "image",
        # Relative to the API origin; the frontend knows where the API lives.
        "src": f"/extracted/{file_path}",
        "caption": payload.get("caption", "Extracted Figure"),
        "page": payload.get("page", -1),
    }


def retrieve(query: str, doc_id: str, top_k: int | None = None) -> RetrievalResult:
    """
    Multimodal retrieval for one document.

    - Text and tables: MiniLM vector search over the "text" vector space.
    - Figures: CLIP text->image search over the "image" vector space, plus
      figures sitting on the pages the text hits came from.
    - "explain page 5"-style queries are restricted to that page.
    """
    top_k = top_k or config.TOP_K_TEXT
    client = get_client()

    match = _PAGE_QUERY.search(query)
    page_number = int(match.group(1)) if match and int(match.group(1)) >= 1 else None

    # -- text + tables -----------------------------------------------------------
    hits = client.query_points(
        collection_name=COLLECTION_NAME,
        query=embed_text(query),
        using=config.TEXT_VECTOR,
        limit=top_k,
        query_filter=Filter(must=_conditions(doc_id, ["text", "table"], page_number)),
        with_payload=True,
    ).points

    context_chunks: List[str] = []
    visuals: List[dict] = []
    pages: set = set()
    table_count = 0

    for hit in hits:
        payload = hit.payload or {}
        page = payload.get("page", -1)
        pages.add(page)

        if payload.get("type") == "table":
            caption = payload.get("caption", "Extracted Table")
            context_chunks.append(f"[Page {page}] {caption}\n{payload.get('content', '')}")
            if table_count < config.MAX_VISUAL_TABLES:
                table_count += 1
                visuals.append(
                    {
                        "id": str(hit.id),
                        "type": "table",
                        "caption": caption,
                        "page": page,
                        "tableData": payload.get("table_data", []),
                    }
                )
        else:
            context_chunks.append(f"[Page {page}]\n{payload.get('content', '')}")

    # -- figures -------------------------------------------------------------------
    image_visuals: List[dict] = []
    seen_ids: set = set()

    def add_image(point):
        visual = _image_visual(point)
        if visual and visual["id"] not in seen_ids and len(image_visuals) < config.MAX_VISUAL_IMAGES:
            seen_ids.add(visual["id"])
            image_visuals.append(visual)

    try:
        image_hits = client.query_points(
            collection_name=COLLECTION_NAME,
            query=embed_clip_text(query),
            using=config.IMAGE_VECTOR,
            limit=config.TOP_K_IMAGES,
            query_filter=Filter(must=_conditions(doc_id, ["image"], page_number)),
            with_payload=True,
        ).points
        for point in image_hits:
            add_image(point)
    except Exception:
        # Image search is a bonus; never let it take down a text answer.
        logger.warning("CLIP image search failed; falling back to page-linked figures", exc_info=True)

    for page in sorted(p for p in pages if p != -1):
        page_images, _ = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=Filter(must=_conditions(doc_id, ["image"], page)),
            limit=2,
            with_payload=True,
        )
        for point in page_images:
            add_image(point)

    for visual in image_visuals:
        pages.add(visual["page"])
    visuals.extend(image_visuals)

    return RetrievalResult(
        context="\n\n".join(context_chunks),
        visuals=visuals,
        pages=sorted(p for p in pages if p != -1),
    )
