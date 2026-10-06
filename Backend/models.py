from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field

# doc_ids are server-generated uuid4 hex strings. They double as an unguessable
# capability token: knowing the id is what grants access to a document.
DOC_ID_PATTERN = r"^[0-9a-f]{32}$"


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    doc_id: str = Field(pattern=DOC_ID_PATTERN)
    history: List[ChatTurn] = Field(default_factory=list, max_length=10)


class VisualEvidence(BaseModel):
    id: str
    type: Literal["image", "table"]
    page: int
    caption: Optional[str] = None
    # Relative to the API origin, e.g. "/extracted/<doc_id>/figure1_page3.png"
    src: Optional[str] = None
    tableData: Optional[List[List[Any]]] = None


class AskResponse(BaseModel):
    answer: str
    citations: List[int]
    supporting_visuals: List[VisualEvidence]
    doc_id: str


class UploadResponse(BaseModel):
    doc_id: str
    filename: str
    status: Literal["processing"] = "processing"


class StatusResponse(BaseModel):
    doc_id: str
    filename: Optional[str] = None
    status: Literal["processing", "ready", "failed"]
    stage: Optional[str] = None
    blocks: Optional[int] = None
    error: Optional[str] = None
