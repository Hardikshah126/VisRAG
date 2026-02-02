from pydantic import BaseModel
from typing import List, Optional


class AskRequest(BaseModel):
    query: str
    doc_id: str


class VisualEvidence(BaseModel):
    path: Optional[str] = None   # ✅ allow missing
    page: int
    caption: Optional[str] = None


class AskResponse(BaseModel):
    answer: str
    citations: List[int]
    supporting_visuals: List[VisualEvidence]
    doc_id: str
