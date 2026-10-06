"""Central configuration. Everything tunable comes from environment variables
(optionally loaded from Backend/.env) so nothing is hardcoded in the modules."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# Absolute paths: the server no longer has to be started from Backend/.
TEMP_DIR = BASE_DIR / "temp"
EXTRACTED_DIR = BASE_DIR / "extracted"


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _list(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


# --- External services -------------------------------------------------------
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# --- Vector storage ----------------------------------------------------------
# v2 uses named vectors (separate text / image spaces). The old single-vector
# "visrag_multimodal" collection is incompatible and can be dropped with
# `python delete_qdrant.py --collection visrag_multimodal`.
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "visrag_multimodal_v2")
TEXT_VECTOR = "text"
IMAGE_VECTOR = "image"
TEXT_DIM = 384  # all-MiniLM-L6-v2
IMAGE_DIM = 512  # CLIP ViT-B/32

# --- Security ----------------------------------------------------------------
# Optional shared secret. When set, every API call must send `X-API-Key`.
API_KEY = os.getenv("API_KEY") or None
ALLOWED_ORIGINS = _list(
    "ALLOWED_ORIGINS",
    "http://localhost:8080,http://127.0.0.1:8080,http://localhost:5173,http://127.0.0.1:5173",
)
# Requests per minute per client IP. 0 disables the limit.
RATE_LIMIT_UPLOAD_PER_MIN = _int("RATE_LIMIT_UPLOAD_PER_MIN", 5)
RATE_LIMIT_ASK_PER_MIN = _int("RATE_LIMIT_ASK_PER_MIN", 30)

# --- Ingestion limits --------------------------------------------------------
MAX_UPLOAD_BYTES = _int("MAX_UPLOAD_MB", 25) * 1024 * 1024
MAX_CONCURRENT_INGESTIONS = _int("MAX_CONCURRENT_INGESTIONS", 2)
MAX_TABLE_PAGES = _int("MAX_TABLE_PAGES", 100)  # Camelot is slow; cap the pages scanned
MAX_FIGURES = _int("MAX_FIGURES", 200)
MIN_FIGURE_PX = _int("MIN_FIGURE_PX", 100)  # skip icons / bullets / rules
MIN_FIGURE_BYTES = _int("MIN_FIGURE_BYTES", 2048)

# --- Retrieval ---------------------------------------------------------------
TOP_K_TEXT = _int("TOP_K_TEXT", 8)
TOP_K_IMAGES = _int("TOP_K_IMAGES", 3)
MAX_VISUAL_IMAGES = _int("MAX_VISUAL_IMAGES", 6)
MAX_VISUAL_TABLES = _int("MAX_VISUAL_TABLES", 4)


def validate_runtime_config() -> None:
    """Fail fast at startup instead of on the first request (or, for Qdrant,
    by silently falling back to localhost)."""
    missing = [
        name
        for name, value in (
            ("QDRANT_URL", QDRANT_URL),
            ("GEMINI_API_KEY", GEMINI_API_KEY),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Missing required environment variable(s): "
            + ", ".join(missing)
            + ". Copy Backend/.env.example to Backend/.env and fill them in."
        )
