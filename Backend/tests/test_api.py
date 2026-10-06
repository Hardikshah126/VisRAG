import time

import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient

import app as app_module
import config
from llm.generator import GenerationError

QUESTION = {"query": "How did revenue change?"}


def make_pdf(with_image=True) -> bytes:
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_textbox(
        fitz.Rect(50, 50, 550, 300), "Revenue grew strongly in every quarter of the year. " * 8, fontsize=11
    )
    page2 = doc.new_page()
    page2.insert_textbox(
        fitz.Rect(50, 50, 550, 200), "Figure one shows quarterly results by region. " * 4, fontsize=11
    )
    if with_image:
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 240, 180), False)
        pix.set_rect(pix.irect, (30, 120, 200))
        # noise so the PNG clears the minimum-bytes filter
        for x in range(0, 240, 3):
            for y in range(0, 180, 4):
                pix.set_pixel(x, y, ((x * 7) % 255, (y * 11) % 255, (x * y) % 255))
        page2.insert_image(fitz.Rect(50, 250, 350, 475), pixmap=pix)
    data = doc.tobytes()
    doc.close()
    return data


FAKE_TABLE = [
    {
        "type": "table",
        "page": 2,
        "caption": "Table 1 (page 2)",
        "table_data": [["Region", "Q1"], ["North", "120"]],
        "content": "Region | Q1\nNorth | 120",
    }
]


@pytest.fixture
def client(monkeypatch):
    # Camelot is exercised separately; keep the API tests fast and deterministic.
    monkeypatch.setattr(app_module, "extract_tables", lambda path: list(FAKE_TABLE))
    monkeypatch.setattr(
        app_module,
        "generate_answer",
        lambda query, context, history=None: "Revenue grew in every quarter [p. 1].",
    )
    app_module.jobs._jobs.clear()
    with TestClient(app_module.app) as c:
        yield c


def upload(client, data=None, name="report.pdf", content_type="application/pdf"):
    payload = make_pdf() if data is None else data
    return client.post("/upload", files={"file": (name, payload, content_type)})


def wait_done(client, doc_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/status/{doc_id}").json()
        if body["status"] != "processing":
            return body
        time.sleep(0.05)
    raise AssertionError("ingestion did not finish")


def ready_doc(client) -> str:
    doc_id = upload(client).json()["doc_id"]
    assert wait_done(client, doc_id)["status"] == "ready"
    return doc_id


# ---- happy path ------------------------------------------------------------
def test_full_flow_upload_ask_delete(client):
    res = upload(client)
    assert res.status_code == 202
    body = res.json()
    doc_id = body["doc_id"]
    assert len(doc_id) == 32 and body["filename"] == "report.pdf" and body["status"] == "processing"

    status = wait_done(client, doc_id)
    assert status["status"] == "ready" and status["blocks"] >= 3
    assert not list(config.TEMP_DIR.glob("*.pdf")), "temp PDF must be removed after ingestion"

    ask = client.post("/ask", json={**QUESTION, "doc_id": doc_id})
    assert ask.status_code == 200
    data = ask.json()
    assert data["answer"].startswith("Revenue grew") and data["citations"] == [1]
    assert {v["type"] for v in data["supporting_visuals"]} == {"table", "image"}

    image = next(v for v in data["supporting_visuals"] if v["type"] == "image")
    assert image["src"].startswith(f"/extracted/{doc_id}/")  # relative: no hardcoded host
    assert client.get(image["src"]).status_code == 200

    assert client.delete(f"/documents/{doc_id}").status_code == 204
    assert client.get(f"/status/{doc_id}").status_code == 404
    assert client.get(image["src"]).status_code == 404
    assert client.post("/ask", json={**QUESTION, "doc_id": doc_id}).status_code == 404


def test_same_filename_gets_independent_documents(client):
    a, b = ready_doc(client), ready_doc(client)
    assert a != b
    client.delete(f"/documents/{a}")
    assert client.get(f"/status/{b}").json()["status"] == "ready"  # b untouched


def test_page_specific_question_only_returns_that_page(client, monkeypatch):
    seen = {}

    def spy(query, context, history=None):
        seen["context"] = context
        return "ok"

    monkeypatch.setattr(app_module, "generate_answer", spy)
    doc_id = ready_doc(client)
    client.post("/ask", json={"query": "explain page 2", "doc_id": doc_id})
    assert "[Page 2]" in seen["context"] and "[Page 1]" not in seen["context"]


def test_history_is_passed_to_the_model(client, monkeypatch):
    seen = {}

    def spy(query, context, history=None):
        seen["history"] = history
        return "ok"

    monkeypatch.setattr(app_module, "generate_answer", spy)
    doc_id = ready_doc(client)
    client.post(
        "/ask", json={**QUESTION, "doc_id": doc_id, "history": [{"role": "user", "content": "earlier"}]}
    )
    assert seen["history"][0].content == "earlier"


# ---- upload validation -------------------------------------------------------
def test_rejects_non_pdf_extension(client):
    assert upload(client, b"hello", name="notes.txt", content_type="text/plain").status_code == 400


def test_rejects_wrong_content_type(client):
    assert upload(client, make_pdf(), content_type="image/png").status_code == 400


def test_rejects_fake_pdf_by_magic_bytes(client):
    res = upload(client, b"this is not a pdf at all")
    assert res.status_code == 400 and "valid PDF" in res.json()["detail"]
    assert not list(config.TEMP_DIR.glob("*.pdf"))


def test_rejects_empty_file(client):
    assert upload(client, b"").status_code == 400


def test_rejects_oversize_and_cleans_up(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 1000)
    assert upload(client, make_pdf()).status_code == 413
    assert not list(config.TEMP_DIR.glob("*.pdf"))


def test_filename_path_traversal_is_neutralised(client):
    res = upload(client, name="../../etc/evil.pdf")
    assert res.status_code == 202
    assert "/" not in res.json()["filename"] and "\\" not in res.json()["filename"]


# ---- ingestion failures ------------------------------------------------------
def test_pdf_with_no_content_fails_with_helpful_message(client, monkeypatch):
    monkeypatch.setattr(app_module, "extract_tables", lambda path: [])
    doc = fitz.open()
    doc.new_page()
    doc_id = upload(client, doc.tobytes()).json()["doc_id"]
    status = wait_done(client, doc_id)
    assert status["status"] == "failed" and "OCR" in status["error"]
    assert client.post("/ask", json={**QUESTION, "doc_id": doc_id}).status_code == 409
    assert not list(config.TEMP_DIR.glob("*.pdf"))


def test_crash_during_ingestion_cleans_up_everything(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("embedding exploded")

    monkeypatch.setattr(app_module, "upload_to_qdrant", boom)
    doc_id = upload(client).json()["doc_id"]
    status = wait_done(client, doc_id)
    assert status["status"] == "failed" and "embedding exploded" not in status["error"]  # no internals leaked
    assert not (config.EXTRACTED_DIR / doc_id).exists()
    assert not list(config.TEMP_DIR.glob("*.pdf"))


# ---- /ask validation + errors ------------------------------------------------
def test_ask_rejects_bad_doc_id_and_query(client):
    assert client.post("/ask", json={**QUESTION, "doc_id": "report.pdf"}).status_code == 422
    assert client.post("/ask", json={"query": "x" * 2001, "doc_id": "a" * 32}).status_code == 422
    assert client.post("/ask", json={"query": "", "doc_id": "a" * 32}).status_code == 422
    assert client.get("/status/not-a-uuid").status_code == 422


def test_ask_while_processing_returns_409(client):
    app_module.jobs.create("b" * 32, "x.pdf")
    assert client.post("/ask", json={**QUESTION, "doc_id": "b" * 32}).status_code == 409


def test_generation_error_is_a_502_with_message(client, monkeypatch):
    def fail(*a, **k):
        raise GenerationError("The model returned no answer (the response may have been blocked).")

    monkeypatch.setattr(app_module, "generate_answer", fail)
    doc_id = ready_doc(client)
    res = client.post("/ask", json={**QUESTION, "doc_id": doc_id})
    assert res.status_code == 502 and "blocked" in res.json()["detail"]


# ---- security ----------------------------------------------------------------
def test_api_key_required_when_configured(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "s3cret")
    assert upload(client).status_code == 401
    assert client.post("/ask", json={**QUESTION, "doc_id": "a" * 32}).status_code == 401
    assert client.get("/status/" + "a" * 32).status_code == 401
    ok = client.post(
        "/upload",
        files={"file": ("r.pdf", make_pdf(), "application/pdf")},
        headers={"X-API-Key": "s3cret"},
    )
    assert ok.status_code == 202
    assert client.get("/status/" + "a" * 32, headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/health").status_code == 200  # health stays open


def test_rate_limits_apply(client, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_UPLOAD_PER_MIN", 2)
    assert upload(client).status_code == 202
    assert upload(client).status_code == 202
    assert upload(client).status_code == 429


def test_cors_only_allows_configured_origins(client):
    allowed = config.ALLOWED_ORIGINS[0]
    ok = client.options("/ask", headers={"Origin": allowed, "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == allowed
    evil = client.options(
        "/ask", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in evil.headers


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "qdrant": True}


def test_startup_fails_fast_without_config(monkeypatch):
    monkeypatch.setattr(config, "QDRANT_URL", None)
    with pytest.raises(RuntimeError, match="QDRANT_URL"):
        with TestClient(app_module.app):
            pass
