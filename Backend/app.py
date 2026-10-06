import logging
import os
import re
import shutil
import threading
import uuid
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Path, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

import config
from ingestion.figure_extractor import extract_figures
from ingestion.parser import parse_pdf
from ingestion.table_parser import extract_tables
from ingestion.uploader import upload_to_qdrant
from jobs import JobRegistry
from llm.generator import GenerationError, extract_citations, generate_answer
from models import (
    DOC_ID_PATTERN,
    AskRequest,
    AskResponse,
    StatusResponse,
    UploadResponse,
)
from retrieval.search import retrieve
from security import limit_ask, limit_upload, require_api_key
from storage.qdrant_client import (
    count_document_points,
    delete_document_points,
    get_client,
    setup_collection,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {"application/pdf"}
UPLOAD_CHUNK = 1024 * 1024

class NoContentError(Exception):
    """The PDF parsed fine but yielded no text, tables or figures."""


jobs = JobRegistry()
# Ingestion is CPU/RAM heavy (Camelot, CLIP); cap how many run at once.
_ingest_slots = threading.BoundedSemaphore(config.MAX_CONCURRENT_INGESTIONS)


# -------------------------------
# STARTUP
# -------------------------------
@asynccontextmanager
async def lifespan(_: FastAPI):
    config.validate_runtime_config()

    # Directories must exist before StaticFiles checks them (see mount below).
    os.makedirs(config.TEMP_DIR, exist_ok=True)
    os.makedirs(config.EXTRACTED_DIR, exist_ok=True)

    # Uploads orphaned by a crash/restart.
    for leftover in config.TEMP_DIR.glob("*.pdf"):
        leftover.unlink(missing_ok=True)

    await run_in_threadpool(setup_collection)
    logger.info("Qdrant ready")
    yield


app = FastAPI(
    title="VisRAG Backend",
    version="2.0",
    description="Multimodal RAG pipeline (text + tables + figures)",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key"],
)

# Extracted figures live under extracted/<uuid>/..., so URLs are unguessable.
os.makedirs(config.EXTRACTED_DIR, exist_ok=True)
app.mount("/extracted", StaticFiles(directory=config.EXTRACTED_DIR), name="extracted")


# -------------------------------
# HELPERS
# -------------------------------
def _sanitize_filename(filename: str) -> str:
    """Display-only: collapse to a safe basename (no directories / traversal)."""
    name = os.path.basename(filename or "").strip()
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name)
    return name.lstrip(".")


def _safe_remove(path) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        logger.warning("Could not remove temp file %s", path, exc_info=True)


def _run_ingestion(pdf_path: str, doc_id: str) -> None:
    """Background job: parse -> tables -> figures -> index. Always removes the
    temp PDF, and on failure also removes any partial output."""
    try:
        with _ingest_slots:
            jobs.update(doc_id, stage="parsing")
            blocks = parse_pdf(pdf_path)

            jobs.update(doc_id, stage="extracting")
            blocks.extend(extract_tables(pdf_path))
            blocks.extend(extract_figures(pdf_path, doc_id))

            if not blocks:
                raise NoContentError()

            jobs.update(doc_id, stage="indexing")
            upload_to_qdrant(blocks, doc_id)

        jobs.update(doc_id, status="ready", stage="complete", blocks=len(blocks))
        logger.info("Ingested %s: %d blocks", doc_id, len(blocks))
    except Exception as exc:
        logger.exception("Failed to process PDF %s", doc_id)
        _cleanup_document(doc_id)
        message = (
            "No extractable text, tables or figures were found. Scanned PDFs need OCR, which is not supported."
            if isinstance(exc, NoContentError)
            else "Failed to process the uploaded PDF."
        )
        jobs.update(doc_id, status="failed", stage="failed", error=message)
    finally:
        _safe_remove(pdf_path)


def _cleanup_document(doc_id: str) -> None:
    try:
        delete_document_points(doc_id)
    except Exception:
        logger.warning("Could not delete Qdrant points for %s", doc_id, exc_info=True)
    shutil.rmtree(config.EXTRACTED_DIR / doc_id, ignore_errors=True)


DocId = Path(pattern=DOC_ID_PATTERN)


# -------------------------------
# ROUTES
# -------------------------------
@app.get("/")
def home():
    return {"status": "VisRAG Backend Running"}


@app.get("/health")
async def health():
    try:
        await run_in_threadpool(get_client().get_collections)
        return {"status": "ok", "qdrant": True}
    except Exception:
        logger.warning("Health check: Qdrant unreachable", exc_info=True)
        return {"status": "degraded", "qdrant": False}


@app.post(
    "/upload",
    response_model=UploadResponse,
    status_code=202,
    dependencies=[Depends(require_api_key), Depends(limit_upload)],
)
async def upload_pdf(file: UploadFile, background_tasks: BackgroundTasks):
    """Accepts the PDF and returns immediately; ingestion runs in the
    background. Poll GET /status/{doc_id} until it is "ready"."""
    filename = _sanitize_filename(file.filename)

    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")
    if file.content_type and file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    # The id is server-generated: filenames can't collide, overwrite someone
    # else's document, or be used to guess/enumerate documents.
    doc_id = uuid.uuid4().hex
    pdf_path = config.TEMP_DIR / f"{doc_id}.pdf"

    size = 0
    try:
        with open(pdf_path, "wb") as buffer:
            while chunk := await file.read(UPLOAD_CHUNK):
                if size == 0 and b"%PDF-" not in chunk[:1024]:
                    raise HTTPException(status_code=400, detail="File is not a valid PDF.")
                size += len(chunk)
                if size > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large (max {config.MAX_UPLOAD_BYTES // (1024 * 1024)}MB).",
                    )
                buffer.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="File is empty.")
    except HTTPException:
        _safe_remove(pdf_path)
        raise
    except OSError:
        _safe_remove(pdf_path)
        logger.exception("Failed to save uploaded file")
        raise HTTPException(status_code=500, detail="Failed to save uploaded file.")

    jobs.create(doc_id, filename)
    background_tasks.add_task(_run_ingestion, str(pdf_path), doc_id)
    logger.info("PDF accepted: %s (%s, %d bytes)", doc_id, filename, size)

    return UploadResponse(doc_id=doc_id, filename=filename)


@app.get("/status/{doc_id}", response_model=StatusResponse, dependencies=[Depends(require_api_key)])
async def document_status(doc_id: str = DocId):
    job = jobs.get(doc_id)
    if job:
        return StatusResponse(
            doc_id=doc_id,
            filename=job.filename,
            status=job.status,
            stage=job.stage,
            blocks=job.blocks,
            error=job.error,
        )

    # Not in memory (e.g. server restarted): ready iff Qdrant holds its points.
    if await run_in_threadpool(count_document_points, doc_id) > 0:
        return StatusResponse(doc_id=doc_id, status="ready", stage="complete")
    raise HTTPException(status_code=404, detail="Document not found.")


@app.delete("/documents/{doc_id}", status_code=204, dependencies=[Depends(require_api_key)])
async def delete_document(doc_id: str = DocId):
    job = jobs.get(doc_id)
    if job and job.status == "processing":
        raise HTTPException(status_code=409, detail="Document is still being processed.")
    await run_in_threadpool(_cleanup_document, doc_id)
    jobs.remove(doc_id)


@app.post(
    "/ask",
    response_model=AskResponse,
    dependencies=[Depends(require_api_key), Depends(limit_ask)],
)
async def ask(request: AskRequest):
    doc_id = request.doc_id
    logger.info("Ask request: doc_id=%s query_len=%d", doc_id, len(request.query))

    job = jobs.get(doc_id)
    if job and job.status == "processing":
        raise HTTPException(status_code=409, detail="Document is still being processed.")
    if job and job.status == "failed":
        raise HTTPException(status_code=409, detail=job.error or "Document processing failed.")

    try:
        result = await run_in_threadpool(retrieve, request.query, doc_id)
    except Exception:
        logger.exception("Retrieval failed for doc_id=%s", doc_id)
        raise HTTPException(status_code=500, detail="Failed to retrieve context from the document.")

    if not result.context and not result.visuals:
        if await run_in_threadpool(count_document_points, doc_id) == 0:
            raise HTTPException(status_code=404, detail="Document not found.")
        return AskResponse(
            answer="No relevant information found.",
            citations=[],
            supporting_visuals=[],
            doc_id=doc_id,
        )

    try:
        answer = await run_in_threadpool(generate_answer, request.query, result.context, request.history)
    except GenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception:
        logger.exception("Answer generation failed for doc_id=%s", doc_id)
        raise HTTPException(status_code=500, detail="Failed to generate an answer.")

    return AskResponse(
        answer=answer,
        citations=extract_citations(answer, result.pages),
        supporting_visuals=result.visuals,
        doc_id=doc_id,
    )
