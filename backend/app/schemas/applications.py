from pydantic import BaseModel, ConfigDict, Field
from typing import Literal, Optional
from datetime import datetime

class ApplicationBase(BaseModel):
    reference: str = Field(..., example="APP-2024-001", description="Unique application reference number")
    entity_name: str = Field(..., example="Acme Corp", description="Name of the applicant or institution")
    app_type: str = Field(..., example="Standard Regulatory", description="Type of application")
    status: Optional[str] = Field(None, example="submitted", description="Current status of the application")

class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reference: str = Field(..., min_length=1, max_length=100, description="Unique application reference number")
    entity_name: str = Field(..., min_length=1, max_length=255, description="Name of the applicant or institution")
    app_type: str = Field(..., min_length=1, max_length=100, description="Type of application")
    institution_id: Optional[int] = Field(None, gt=0, description="Institution selected by an administrator")

class ApplicationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    entity_name: Optional[str] = Field(None, min_length=1, max_length=255)
    app_type: Optional[str] = Field(None, min_length=1, max_length=100)
    status: Optional[str] = Field(None, min_length=1, max_length=50)

class ApplicationOut(ApplicationBase):
    id: int
    institution_id: Optional[int] = None
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


class ClassificationEvidenceOut(BaseModel):
    page: int
    signal: str
    excerpt: str
    document_type: Optional[str] = None


class DocumentClassificationOut(BaseModel):
    status: Literal["classified", "needs_review", "unavailable"]
    candidate_document_type: Optional[str]
    match_strength: Literal["strong", "possible", "none"]
    evidence: list[ClassificationEvidenceOut]
    explanation: str


class DocumentProcessingOut(BaseModel):
    document_id: int
    processing_status: str
    extraction_method: str
    pages_processed: int
    fields: dict[str, ExtractedFieldOut]
    classification: Optional[DocumentClassificationOut] = None
    warnings: list[str]
    processed_at: Optional[datetime] = None


class ValidationReviewOut(BaseModel):
    status: str
    reviewer: Optional[str]
    reviewed_at: Optional[datetime]
    notes: str


class ValidationDocumentFieldOut(BaseModel):
    value: Optional[str]
    page: Optional[int]
    evidence: Optional[str]
    confidence: Optional[float]
    status: str
    verification_status: Literal["unverified"] = "unverified"


class ValidationDocumentEvidenceOut(BaseModel):
    document_id: int
    processing_status: str
    extraction_method: str
    processed_at: Optional[datetime]
    fields: dict[str, ValidationDocumentFieldOut]
    warnings: list[str]


class ValidationRuleSourceOut(BaseModel):
    handbook_version: str
    source_path: str
    section: str
    printed_page: int
    pdf_page: int


class ValidationRuleEvidenceOut(BaseModel):
    rule_id: str
    clause_text: str
    source: ValidationRuleSourceOut


class ValidationRuleCandidateOut(BaseModel):
    rule_id: str
    document_type: str
    candidate_requirement: str
    known_scope: str
    source_mapping_review: ValidationReviewOut
    currentness_review: ValidationReviewOut
    applicability_review: ValidationReviewOut
    preview_approved: bool
    eligibility: Literal["unknown", "not_applicable", "eligible_for_preview"]
    evidence: ValidationRuleEvidenceOut


class ValidationCheckOut(BaseModel):
    rule_id: str
    status: Literal["unknown", "not_assessed"]
    reason: str


class DocumentValidationPreviewOut(BaseModel):
    application_id: int
    document_id: int
    application_scope_status: Literal["unknown"]
    overall_status: Literal["unknown", "not_assessed"]
    document_evidence: ValidationDocumentEvidenceOut
    candidate_rules: list[ValidationRuleCandidateOut]
    checks: list[ValidationCheckOut]
    limitations: list[str]
    warnings: list[str]


class InstitutionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)


class InstitutionOut(BaseModel):
    id: int
    name: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AuditEventOut(BaseModel):
    id: int
    user_id: Optional[int]
    actor_name: Optional[str]
    action: str
    entity_type: str
    entity_id: str
    timestamp: datetime
    metadata: dict[str, object]


class AuditEventPageOut(BaseModel):
    items: list[AuditEventOut]
    limit: int
    offset: int
    total: int


class DuplicateFileMatchOut(BaseModel):
    document_id: int
    original_filename: str


class AuthenticityCheckOut(BaseModel):
    status: str
    explanation: str
    matches: list[DuplicateFileMatchOut] = Field(default_factory=list)


class DocumentIntegrityPreviewOut(BaseModel):
    application_id: int
    document_id: int
    sha256: Optional[str]
    duplicate_file_check: AuthenticityCheckOut
    pdf_structure_check: AuthenticityCheckOut
    metadata_check: AuthenticityCheckOut
    issuer_verification: Literal["not_performed"]
    authenticity_status: Literal["not_assessed"]
    limitations: list[str]


class ComplianceAssessmentOut(BaseModel):
    id: int
    application_id: int
    application_reference: str
    entity_name: str
    rule_code: str
    rule_title: str
    category: str
    status: str
    explanation: str
    assessed_at: datetime
    reviewer_name: Optional[str]


class ComplianceAssessmentPageOut(BaseModel):
    items: list[ComplianceAssessmentOut]
    total: int


class ComplianceAssessmentReviewOut(BaseModel):
    id: int
    assessment_id: int
    reviewer_id: int
    reviewer_name: str
    outcome: Literal["evidence_accepted", "evidence_rejected", "information_requested", "further_investigation"]
    note: str
    created_at: datetime


class ComplianceAssessmentDetailOut(ComplianceAssessmentOut):
    application_status: str
    rule_description: str
    assigned_reviewer_id: Optional[int]
    document_evidence: list[dict[str, object]]
    reviews: list[ComplianceAssessmentReviewOut]


class ComplianceAssessmentReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    outcome: Literal["evidence_accepted", "evidence_rejected", "information_requested", "further_investigation"]
    note: str = Field(default="", max_length=2000)


class ComplianceAssessmentAssignmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer_id: int = Field(..., gt=0)


class ConsistencyResultOut(BaseModel):
    id: int
    run_id: int
    application_id: int
    field: str
    category: str
    val1: Optional[str]
    val2: Optional[str]
    explanation: str
    human_review_recommended: bool
    doc1_id: int
    doc1_filename: str
    doc2_id: int
    doc2_filename: str


class ConsistencyRunOut(BaseModel):
    id: int
    application_id: int
    status: str
    comparisons_count: int
    created_at: datetime
    results: list[ConsistencyResultOut]


class ConsistencyRunHistoryOut(BaseModel):
    items: list[ConsistencyRunOut]


class FindingReviewOut(BaseModel):
    id: int
    finding_id: int
    reviewer_id: int
    reviewer_name: str
    outcome: Literal["confirmed_issue", "false_positive", "needs_further_review"]
    note: str
    created_at: datetime


class FindingOut(BaseModel):
    id: int
    application_id: int
    document_id: Optional[int]
    finding_type: str
    severity: str
    description: str
    status: str
    created_at: datetime
    reviews: list[FindingReviewOut] = Field(default_factory=list)

    class Config:
        from_attributes = True


class FindingReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    outcome: Literal["confirmed_issue", "false_positive", "needs_further_review"]
    note: str = Field(default="", max_length=2000)


class ChecklistItemOut(BaseModel):
    document_type: str
    status: Literal[
        "missing_document",
        "processing_pending",
        "processing_failed",
        "incomplete_fields",
        "expired_document",
        "expiry_unverified",
        "received",
    ]
    document_ids: list[int] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    explanation: str


class ApplicationChecklistOut(BaseModel):
    application_id: int
    category: str
    source: Literal["synthetic_demo"] = "synthetic_demo"
    items: list[ChecklistItemOut]
