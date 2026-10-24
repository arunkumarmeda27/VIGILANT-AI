from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class ApplicationBase(BaseModel):
    reference: str = Field(..., example="APP-2024-001", description="Unique application reference number")
    entity_name: str = Field(..., example="Acme Corp", description="Name of the applicant or institution")
    app_type: str = Field(..., example="Standard Regulatory", description="Type of application")
    status: Optional[str] = Field(None, example="submitted", description="Current status of the application")

class ApplicationCreate(ApplicationBase):
    pass

class ApplicationUpdate(BaseModel):
    entity_name: Optional[str] = None
    app_type: Optional[str] = None
    status: Optional[str] = None

class ApplicationOut(ApplicationBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class DocumentOut(BaseModel):
    id: int
    application_id: int
    doc_type: str
    original_filename: str
    processing_status: str
    sha256: Optional[str]
    file_size: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True

class ExtractedFieldOut(BaseModel):
    value: Optional[str]
    page: Optional[int]
    evidence: Optional[str]
    confidence: Optional[float]
    status: str

class DocumentProcessingOut(BaseModel):
    document_id: int
    processing_status: str
    extraction_method: str
    pages_processed: int
    fields: dict[str, ExtractedFieldOut]
    warnings: list[str]
    processed_at: Optional[datetime] = None
