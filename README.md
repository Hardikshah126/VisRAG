# VisRAG — Multimodal RAG for PDFs

Upload a PDF, ask questions in plain language, and get answers with page
citations **plus the tables and figures behind them**.

- **Text** is chunked (sentence-aware, with overlap) and embedded with MiniLM.
- **Tables** are extracted with Camelot, filtered for false positives, and searched as text.
- **Figures** are extracted with PyMuPDF, de-duplicated, embedded with CLIP, and found with
  text→image search.
- **Answers** come from Gemini, grounded in the retrieved excerpts, citing `[p. N]`.

> This is a demo-grade project: see [Limitations](#limitations) before exposing it publicly.

## Architecture

```
React (Vite) ──HTTP──▶ FastAPI ──▶ Qdrant (named vectors: text 384-d, image 512-d)
                          │
                          ├─ background ingestion: PyMuPDF · Camelot · MiniLM · CLIP
                          └─ Gemini (answer generation)
```

1. `POST /upload` validates and stores the PDF, returns a server-generated `doc_id` (`202`).
2. Ingestion runs in the background; the UI polls `GET /status/{doc_id}`
   (`queued → parsing → extracting → indexing → complete`).
3. `POST /ask` retrieves text/tables (MiniLM) and figures (CLIP), prompts Gemini, and returns
   the answer, cited pages, and supporting visuals.

## Setup

Requires Python 3.11+, Node 18+, a [Qdrant](https://qdrant.tech) instance (Cloud free tier or
local Docker) and a [Gemini API key](https://aistudio.google.com/apikey).

### Backend

```bash
cd Backend
python -m venv venv
venv\Scripts\activate            # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env             # then fill in QDRANT_URL, QDRANT_API_KEY, GEMINI_API_KEY
uvicorn app:app --port 8000
```

The first run downloads the embedding models (MiniLM ~90 MB, CLIP ~600 MB).
`QDRANT_URL=:memory:` runs against an ephemeral in-process store, handy for trying it out.

### Frontend

```bash
cd Frontend
npm install
npm run dev                      # http://localhost:8080
```

The API URL defaults to `http://127.0.0.1:8000`; override with `VITE_API_URL`
(see `Frontend/.env.example`).

## API

| Method | Path | |
| --- | --- | --- |
| `POST` | `/upload` | multipart `file` → `202 {doc_id, filename, status}` |
| `GET` | `/status/{doc_id}` | `processing` / `ready` / `failed` + stage, error |
| `POST` | `/ask` | `{query, doc_id, history?}` → answer, citations, supporting visuals |
| `DELETE` | `/documents/{doc_id}` | removes the vectors and extracted figures |
| `GET` | `/health` | liveness + Qdrant reachability |

Interactive docs at `http://127.0.0.1:8000/docs`.

## Configuration

All backend settings are environment variables (see `Backend/.env.example`): service
credentials, `ALLOWED_ORIGINS` (CORS), optional `API_KEY`, per-IP rate limits, upload size,
and ingestion limits.

## Security model

- `doc_id` is an unguessable server-generated UUID that acts as a capability: whoever has it can
  query that document. Filenames never identify documents, so one upload can't overwrite another.
- CORS is limited to `ALLOWED_ORIGINS`; uploads are size-limited and validated by content, not
  just extension; per-IP rate limits apply to `/upload` and `/ask`.
- Optional `API_KEY` requires an `X-API-Key` header. Don't put it in a public browser bundle.
- Retrieved PDF text is passed to the model as delimited, untrusted data.

## Tests

```bash
cd Backend  && pip install -r requirements-dev.txt && pytest
cd Frontend && npm test
```

Backend tests run against an in-memory Qdrant with fake embedders and a fake LLM, plus real
Camelot.

## Limitations

- **No user accounts.** Access control is the unguessable `doc_id` (+ optional shared API key).
  Add real auth before multi-user use.
- **Single process.** The ingestion job registry and rate limiter are in-memory. After a restart
  in-flight jobs are lost (finished documents remain available via Qdrant).
- **No OCR.** Scanned PDFs are rejected with a clear message.
- **Documents are kept until deleted** (`DELETE /documents/{doc_id}`); there is no automatic expiry.
- **Upgrading from the earlier version:** vectors now live in a new collection
  (`visrag_multimodal_v2`). Remove the old one with
  `python delete_qdrant.py --collection visrag_multimodal`.
