"""Embedding models. Text/tables use MiniLM (384-d); images and image-search
queries use CLIP (512-d). Both live in separate vector spaces in Qdrant, so a
text query is matched against images with CLIP's *text* encoder — never with
the MiniLM vector. Heavy imports and model loads are lazy and thread-safe."""

import logging
import threading
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)

TEXT_MODEL_NAME = "all-MiniLM-L6-v2"
CLIP_MODEL_NAME = "openai/clip-vit-base-patch32"

_lock = threading.Lock()
_text_model = None
_clip = None  # (model, processor)


def _get_text_model():
    global _text_model
    if _text_model is None:
        with _lock:
            if _text_model is None:
                from sentence_transformers import SentenceTransformer

                logger.info("Loading text model %s...", TEXT_MODEL_NAME)
                _text_model = SentenceTransformer(TEXT_MODEL_NAME)
    return _text_model


def _get_clip():
    global _clip
    if _clip is None:
        with _lock:
            if _clip is None:
                from transformers import CLIPModel, CLIPProcessor

                logger.info("Loading CLIP...")
                model = CLIPModel.from_pretrained(CLIP_MODEL_NAME).eval()
                processor = CLIPProcessor.from_pretrained(CLIP_MODEL_NAME)
                _clip = (model, processor)
                logger.info("CLIP loaded")
    return _clip


def embed_texts(texts: Sequence[str]) -> List[List[float]]:
    """Batch-embed texts (384-d, L2-normalised)."""
    if not texts:
        return []
    vectors = _get_text_model().encode(
        list(texts), batch_size=32, normalize_embeddings=True, show_progress_bar=False
    )
    return vectors.tolist()


def embed_text(text: str) -> List[float]:
    return embed_texts([text])[0]


def embed_clip_text(text: str) -> List[float]:
    """Embed a query with CLIP's text tower for text->image search (512-d)."""
    import torch

    model, processor = _get_clip()
    inputs = processor(text=[text], return_tensors="pt", padding=True, truncation=True, max_length=77)
    with torch.no_grad():
        # Tower + projection instead of get_text_features(): that helper returns a
        # tensor on transformers 4.x but a ModelOutput on 5.x. This works on both.
        pooled = model.text_model(**inputs).pooler_output
        features = model.text_projection(pooled)
    features = features / features.norm(dim=-1, keepdim=True)
    return features[0].tolist()


def embed_images(image_paths: Sequence[str], batch_size: int = 16) -> List[Optional[List[float]]]:
    """Embed images with CLIP (512-d). An unreadable image yields None rather
    than failing the whole document."""
    import torch
    from PIL import Image

    model, processor = _get_clip()
    results: List[Optional[List[float]]] = []

    for start in range(0, len(image_paths), batch_size):
        batch_paths = image_paths[start : start + batch_size]
        images, ok = [], []
        for path in batch_paths:
            try:
                with Image.open(path) as img:
                    images.append(img.convert("RGB"))
                ok.append(True)
            except Exception:
                logger.warning("Could not read image %s", path, exc_info=True)
                ok.append(False)

        vectors: List[List[float]] = []
        if images:
            inputs = processor(images=images, return_tensors="pt")
            with torch.no_grad():
                pooled = model.vision_model(pixel_values=inputs["pixel_values"]).pooler_output
                features = model.visual_projection(pooled)
            features = features / features.norm(dim=-1, keepdim=True)
            vectors = features.tolist()

        it = iter(vectors)
        results.extend(next(it) if good else None for good in ok)

    return results
