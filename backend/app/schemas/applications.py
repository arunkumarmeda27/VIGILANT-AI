from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Literal, Optional
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
    predicted_doc_type: Optional[str] = None
    processed_doc_type: Optional[str] = None
    schema_version_id: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ImageEvidenceOut(BaseModel):
    id: int
    application_id: int
    validation_run_id: Optional[int]
    original_filename: str
    content_type: str
    sha256: str
    file_size: int
    processing_status: str
    analysis_result: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ExtractedFieldOut(BaseModel):
    value: Optional[str]
    raw_value: Optional[str] = None
    normalized_value: Any = None
    page: Optional[int]
    evidence: Optional[str]
    confidence: Optional[float]
    status: str
    method: Optional[str] = None
    extractor_version: Optional[str] = None
    coordinates: Optional[dict[str, float]] = None
    verification_status: Literal["unverified"] = "unverified"


class ClassificationEvidenceOut(BaseModel):
    page: int
    signal: str
    excerpt: str
    document_type: Optional[str] = None


class DocumentClassificationOut(BaseModel):
    status: Literal["classified", "needs_review", "unavailable"]
    candidate_document_type: Optional[str]
    candidate_alternatives: list[str] = Field(default_factory=list)
    heuristic_score: Optional[float] = None
    score_kind: str = "heuristic_match_ratio"
    registry_status: Optional[str] = None
    schema_version_id: Optional[int] = None
    match_strength: Literal["strong", "possible", "none"]
    classifier: Optional[str] = None
    classifier_version: Optional[str] = None
    abstention_reason: Optional[str] = None
    human_review_required: bool = True
    evidence: list[ClassificationEvidenceOut]
    explanation: str


class DocumentPageRegionOut(BaseModel):
    text: str
    coordinates: dict[str, float]
    coordinate_space: Literal["pdf_points", "rendered_page_pixels"]
    confidence: Optional[float] = None


class DocumentPageOut(BaseModel):
    page: int
    text: str
    method: Literal["text", "ocr", "mixed"]
    confidence: Optional[float] = None
    regions: list[DocumentPageRegionOut] = Field(default_factory=list)


class OCRMetadataOut(BaseModel):
    engine: Optional[str] = None
    engine_version: Optional[str] = None
    languages: list[str] = Field(default_factory=list)
    available: bool


class DocumentProcessingOut(BaseModel):
    document_id: int
    processing_status: str
    extraction_method: str
    pages_processed: int
    pages: list[DocumentPageOut] = Field(default_factory=list)
    ocr: OCRMetadataOut = Field(default_factory=lambda: OCRMetadataOut(available=False))
    processing_duration_ms: float = 0
    unreadable_pages: list[int] = Field(default_factory=list)
    blank_pages: list[int] = Field(default_factory=list)
    fields: dict[str, ExtractedFieldOut]
    classification: Optional[DocumentClassificationOut] = None
    schema_validation: Optional[dict[str, Any]] = None
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


class ApplicationValidationDocumentStageOut(BaseModel):
    document_id: int
    document_type: str
    processing_status: str
    status: Literal["completed", "partial", "pending", "failed", "unsupported", "unavailable"]
    reason: str
    schema_validation_status: Optional[str] = None
    schema_version_id: Optional[int] = None


class ApplicationValidationRuleResultOut(BaseModel):
    rule_id: str
    document_type: str
    status: Literal[
        "Partial",
        "Not evaluated",
        "Not-Applicable",
    ]
    reason_code: str
    explanation: str
    evidence: Optional[str] = None


class ApplicationValidationOut(BaseModel):
    application_id: int
    run_id: int
    execution_status: Literal["completed", "partial", "failed"]
    status: Literal["completed", "partial", "inconclusive"]
    evaluated_rules_count: int
    not_evaluated_rules_count: int
    not_applicable_rules_count: int
    document_stages: list[ApplicationValidationDocumentStageOut]
    stages: list[dict[str, Any]]
    results: list[dict[str, Any]]
    findings_count: int
    error_summary: Optional[str] = None


class ValidationRunOut(BaseModel):
    id: int
    application_id: int
    user_id: int
    started_at: datetime
    completed_at: Optional[datetime]
    execution_status: Literal["completed", "partial", "failed"]
    outcome: Literal["completed", "partial", "inconclusive"]
    stage_outcomes: list[dict[str, Any]]
    results: list[dict[str, Any]]
    error_summary: Optional[str]
    evaluated_rules_count: int
    not_evaluated_rules_count: int
    not_applicable_rules_count: int

    model_config = ConfigDict(from_attributes=True)


class ValidationRunHistoryOut(BaseModel):
    items: list[ValidationRunOut]


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


class StoredFileHashCheckOut(BaseModel):
    status: Literal["match", "mismatch", "unavailable", "not_available"]
    stored_sha256: Optional[str]
    current_sha256: Optional[str]
    explanation: str


class DocumentIntegrityPreviewOut(BaseModel):
    application_id: int
    document_id: int
    sha256: Optional[str]
    file_hash_check: StoredFileHashCheckOut
    duplicate_file_check: AuthenticityCheckOut
    pdf_structure_check: AuthenticityCheckOut
    metadata_check: AuthenticityCheckOut
    issuer_verification: Literal["not_performed"]
    authenticity_status: Literal["not_assessed"]
    limitations: list[str]


class ComplianceAssessmentReviewOut(BaseModel):
    id: int
    assessment_id: int
    reviewer_id: int
    reviewer_name: str
    outcome: Literal["evidence_accepted", "evidence_rejected", "information_requested", "further_investigation"]
    note: str
    created_at: datetime


class ComplianceAssessmentStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    review_status: Literal[
        "PENDING_REVIEW",
        "IN_REVIEW",
        "ADDITIONAL_INFORMATION_REQUIRED",
        "ESCALATED",
        "CLOSED",
    ]
    reason: Optional[str] = Field(default=None, max_length=2000)


class ComplianceAssessmentOut(BaseModel):
    id: int
    application_id: int
    assigned_reviewer_id: Optional[int]
    application_reference: str
    entity_name: str
    rule_code: str
    rule_title: str
    category: str
    status: str
    review_status: Literal[
        "PENDING_REVIEW",
        "IN_REVIEW",
        "ADDITIONAL_INFORMATION_REQUIRED",
        "ESCALATED",
        "CLOSED",
    ]
    explanation: str
    assessed_at: datetime
    reviewer_name: Optional[str]
    reviews: list[ComplianceAssessmentReviewOut] = Field(default_factory=list)


class ComplianceAssessmentPageOut(BaseModel):
    items: list[ComplianceAssessmentOut]
    total: int


class ComplianceAssessmentDetailOut(ComplianceAssessmentOut):
    application_status: str
    rule_description: str
    assigned_reviewer_id: Optional[int]
    document_evidence: list[dict[str, object]]
    review_status_history: list[dict[str, object]] = Field(default_factory=list)
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
