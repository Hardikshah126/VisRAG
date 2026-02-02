from fastapi import FastAPI, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

import shutil
import os

from ingestion.parser import parse_pdf
from ingestion.uploader import upload_to_qdrant

from ingestion.table_parser import extract_tables
from ingestion.figure_extractor import extract_figures

from retrieval.search import retrieve
from llm.generator import generate_answer
from storage.qdrant_client import setup_collection, client, COLLECTION_NAME





from models import AskRequest, AskResponse


# -------------------------------
# ✅ FASTAPI APP
# -------------------------------
app = FastAPI(
    title="VisRAG Backend",
    version="1.0",
    description="Multimodal Agentic RAG Pipeline (Text + Tables + Figures)"
)

# ✅ Allow frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Serve extracted visuals
app.mount("/extracted", StaticFiles(directory="extracted"), name="extracted")


# -------------------------------
# ✅ STARTUP EVENT
# -------------------------------
@app.on_event("startup")
def startup():
    print("\n🔥 FastAPI startup...")
    setup_collection()
    print("✅ Qdrant ready!\n")


# -------------------------------
# ✅ ROOT
# -------------------------------
@app.get("/")
def home():
    return {"status": "VisRAG Backend Running ✅"}


# -------------------------------
# ✅ UPLOAD ENDPOINT
# -------------------------------
@app.post("/upload")
async def upload_pdf(file: UploadFile):

    os.makedirs("temp", exist_ok=True)

    doc_id = file.filename
    pdf_path = f"temp/{doc_id}"

    with open(pdf_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    print("\n✅ PDF Uploaded:", doc_id)

    # ✅ Extract Blocks
    blocks = parse_pdf(pdf_path)

    # ✅ Tables
    blocks.extend(extract_tables(pdf_path))

    # ✅ Figures
    blocks.extend(extract_figures(pdf_path))

    print("✅ Total Extracted Blocks =", len(blocks))

    # ✅ Upload Properly
    upload_to_qdrant(blocks, doc_id)
    count = client.count(collection_name=COLLECTION_NAME, exact=True)
    print("✅ POINTS AFTER UPLOAD =", count.count)
 

    return {
        "status": "uploaded",
        "doc_id": doc_id,
        "blocks": len(blocks)
    }




# -------------------------------
# ✅ ASK ENDPOINT
# -------------------------------
@app.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest):

    print("\n🔥 ASK REQUEST RECEIVED:")
    print("QUERY =", request.query)
    print("DOC_ID =", request.doc_id)

    query = request.query
    doc_id = request.doc_id

    # ✅ DEBUG: Check Qdrant contains points
    total_points = client.count(
        collection_name=COLLECTION_NAME,
        exact=True
    )

    print("✅ TOTAL POINTS IN QDRANT =", total_points.count)

    # -------------------------------
    # ✅ Retrieve evidence
    # -------------------------------
    context, visuals, citations = retrieve(query, doc_id)

    print("✅ Retrieved Context Length =", len(context))
    print("✅ Retrieved Visuals =", len(visuals))
    print("✅ Citations =", citations)

    # -------------------------------
    # ✅ If nothing found
    # -------------------------------
    if not context and not visuals:
        return AskResponse(
            answer="❌ No relevant information found.",
            citations=[],
            supporting_visuals=[],
            doc_id=doc_id
        )

    # -------------------------------
    # ✅ Gemini grounded answer
    # -------------------------------
    answer = generate_answer(query, context, citations)

    return AskResponse(
        answer=answer,
        citations=citations,
        supporting_visuals=visuals,
        doc_id=doc_id
    )

