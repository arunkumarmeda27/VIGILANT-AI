from typing import Literal

from pydantic import BaseModel, Field, field_validator


class AIAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)

    @field_validator("question", mode="before")
    @classmethod
    def strip_question(cls, value):
        return value.strip() if isinstance(value, str) else value


class EvidenceCitation(BaseModel):
    source_document: str
    pdf_page: int | str
    printed_handbook_page: int | str
    chunk_id: str


class AIEvidence(BaseModel):
    text: str
    source_text: str
    evidence_type: str
    retrieval_score: float | None
    citation: EvidenceCitation


class AIWarning(BaseModel):
    code: str
    message: str
    citations: list[EvidenceCitation]


class AIAnswerResponse(BaseModel):
    question: str
    status: Literal["source_evidence_found", "insufficient_evidence"]
    answer: str
    evidence: list[AIEvidence]
    warnings: list[AIWarning]
