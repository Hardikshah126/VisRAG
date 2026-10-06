import hashlib
import re
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import config  # noqa: E402

# Point file storage at throwaway dirs *before* app.py is imported, because it
# mounts StaticFiles on config.EXTRACTED_DIR at import time.
_scratch = Path(tempfile.mkdtemp(prefix="visrag-tests-"))
config.TEMP_DIR = _scratch / "temp"
config.EXTRACTED_DIR = _scratch / "extracted"
config.QDRANT_URL = ":memory:"
config.GEMINI_API_KEY = "test-key"
config.API_KEY = None
config.RATE_LIMIT_UPLOAD_PER_MIN = 0
config.RATE_LIMIT_ASK_PER_MIN = 0


def fake_text_vector(text: str):
    """Deterministic bag-of-words vector: texts sharing words score higher."""
    vec = [0.0] * config.TEXT_DIM
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % config.TEXT_DIM] += 1.0
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


def fake_image_vector(seed: str):
    vec = [0.0] * config.IMAGE_DIM
    vec[int(hashlib.md5(seed.encode()).hexdigest(), 16) % config.IMAGE_DIM] = 1.0
    return vec


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """Fresh in-memory Qdrant + fake embedders for every test."""
    import ingestion.uploader as uploader
    import retrieval.search as search
    import storage.qdrant_client as qc
    from security import limiter

    monkeypatch.setattr(config, "API_KEY", None)
    monkeypatch.setattr(config, "RATE_LIMIT_UPLOAD_PER_MIN", 0)
    monkeypatch.setattr(config, "RATE_LIMIT_ASK_PER_MIN", 0)
    qc.get_client.cache_clear()
    limiter.reset()

    monkeypatch.setattr(uploader, "embed_texts", lambda texts: [fake_text_vector(t) for t in texts])
    monkeypatch.setattr(
        uploader, "embed_images", lambda paths: [fake_image_vector(Path(p).name) for p in paths]
    )
    monkeypatch.setattr(search, "embed_text", fake_text_vector)
    # Query "chart" lands on whichever fake image vector the test registers.
    monkeypatch.setattr(search, "embed_clip_text", lambda q: fake_image_vector("figure1_page2.png"))
    yield
    qc.get_client.cache_clear()
