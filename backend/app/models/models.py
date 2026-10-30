from datetime import datetime
from typing import Any, List, Optional
from sqlalchemy import String, ForeignKey, DateTime, Boolean, Integer, Text, Table, Column, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.db.base import Base

# --- Mixins ---

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

# --- Models ---

class Institution(Base, TimestampMixin):
    __tablename__ = "institutions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    # Relationships
    users: Mapped[List["User"]] = relationship("User", back_populates="institution")
    applications: Mapped[List["Application"]] = relationship("Application", back_populates="institution")

class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String(50)) # admin, reviewer, applicant
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    institution_id: Mapped[Optional[int]] = mapped_column(ForeignKey("institutions.id"), index=True, nullable=True)

    # Relationships
    institution: Mapped[Optional["Institution"]] = relationship("Institution", back_populates="users")
    comments: Mapped[List["ReviewComment"]] = relationship("ReviewComment", back_populates="author")
    assessments: Mapped[List["ComplianceAssessment"]] = relationship("ComplianceAssessment", back_populates="reviewer")
    assessment_reviews: Mapped[List["ComplianceAssessmentReview"]] = relationship("ComplianceAssessmentReview", back_populates="reviewer")
    finding_reviews: Mapped[List["FindingReview"]] = relationship("FindingReview", back_populates="reviewer")

class DocumentType(Base, TimestampMixin):
    __tablename__ = "document_types"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    family: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    supported_file_formats: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    supported_languages: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    application_categories: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    regulatory_rule_references: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    issuing_authority: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    verification_config: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    expiry_config: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    schema_versions: Mapped[List["DocumentSchemaVersion"]] = relationship(
        "DocumentSchemaVersion",
        back_populates="document_type",
        cascade="all, delete-orphan",
        order_by="DocumentSchemaVersion.created_at",
    )


class DocumentSchemaVersion(Base):
    __tablename__ = "document_schema_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_type_id",
            "schema_version",
            name="uq_document_schema_type_version",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_type_id: Mapped[str] = mapped_column(ForeignKey("document_types.id"), nullable=False, index=True)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    activated_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    document_type: Mapped["DocumentType"] = relationship(
        "DocumentType",
        back_populates="schema_versions",
    )


class Application(Base, TimestampMixin):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    reference: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    entity_name: Mapped[str] = mapped_column(String(255)) # Applicant or Institution name
    app_type: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), default="submitted")
    institution_id: Mapped[Optional[int]] = mapped_column(ForeignKey("institutions.id"), index=True, nullable=True)

    # Relationships
    institution: Mapped[Optional["Institution"]] = relationship("Institution", back_populates="applications")
    documents: Mapped[List["Document"]] = relationship("Document", back_populates="application", cascade="all, delete-orphan")
    findings: Mapped[List["Finding"]] = relationship("Finding", back_populates="application", cascade="all, delete-orphan")
    comments: Mapped[List["ReviewComment"]] = relationship("ReviewComment", back_populates="application", cascade="all, delete-orphan")
    assessments: Mapped[List["ComplianceAssessment"]] = relationship("ComplianceAssessment", back_populates="application", cascade="all, delete-orphan")

class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    doc_type: Mapped[str] = mapped_column(String(100))
    original_filename: Mapped[str] = mapped_column(String(512))
    storage_key: Mapped[str] = mapped_column(String(1024)) # Path/Key in S3
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    processing_status: Mapped[str] = mapped_column(String(50), default="pending")
    processing_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    predicted_doc_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    processed_doc_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    schema_version_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("document_schema_versions.id"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    application: Mapped["Application"] = relationship("Application", back_populates="documents")
    findings: Mapped[List["Finding"]] = relationship("Finding", back_populates="document")
    schema_version: Mapped[Optional["DocumentSchemaVersion"]] = relationship("DocumentSchemaVersion")
    type_corrections: Mapped[List["DocumentTypeCorrection"]] = relationship(
        "DocumentTypeCorrection",
        back_populates="document",
        order_by="DocumentTypeCorrection.created_at",
    )


class DocumentTypeCorrection(Base):
    __tablename__ = "document_type_corrections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)
    previous_document_type: Mapped[str] = mapped_column(String(100), nullable=False)
    corrected_document_type: Mapped[str] = mapped_column(ForeignKey("document_types.id"), nullable=False)
    original_prediction: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship("Document", back_populates="type_corrections")

class Finding(Base, TimestampMixin):
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    document_id: Mapped[Optional[int]] = mapped_column(ForeignKey("documents.id"), index=True, nullable=True)
    finding_type: Mapped[str] = mapped_column(String(100))
    severity: Mapped[str] = mapped_column(String(50)) # Low, Medium, High, Critical
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="open")

    # Relationships
    application: Mapped["Application"] = relationship("Application", back_populates="findings")
    document: Mapped[Optional["Document"]] = relationship("Document", back_populates="findings")
    reviews: Mapped[List["FindingReview"]] = relationship("FindingReview", back_populates="finding", cascade="all, delete-orphan")

class FindingReview(Base):
    """Append-only human review decisions for automated findings."""
    __tablename__ = "finding_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id"), index=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    outcome: Mapped[str] = mapped_column(String(50))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    finding: Mapped["Finding"] = relationship("Finding", back_populates="reviews")
    reviewer: Mapped["User"] = relationship("User", back_populates="finding_reviews")

class ReviewComment(Base):
    __tablename__ = "review_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    comment_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    application: Mapped["Application"] = relationship("Application", back_populates="comments")
    author: Mapped["User"] = relationship("User", back_populates="comments")

class ComplianceRule(Base, TimestampMixin):
    __tablename__ = "compliance_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    rule_code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    assessments: Mapped[List["ComplianceAssessment"]] = relationship("ComplianceAssessment", back_populates="rule")

class ComplianceAssessment(Base):
    __tablename__ = "compliance_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("compliance_rules.id"), index=True)
    status: Mapped[str] = mapped_column(String(50)) # Compliant, Non-Compliant, Partial, Not-Applicable
    review_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="PENDING_REVIEW",
        server_default="PENDING_REVIEW",
    )
    explanation: Mapped[str] = mapped_column(Text)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)

    # Relationships
    application: Mapped["Application"] = relationship("Application", back_populates="assessments")
    rule: Mapped["ComplianceRule"] = relationship("ComplianceRule", back_populates="assessments")
    reviewer: Mapped[Optional["User"]] = relationship("User", back_populates="assessments")
    reviews: Mapped[List["ComplianceAssessmentReview"]] = relationship(
        "ComplianceAssessmentReview", back_populates="assessment", cascade="all, delete-orphan"
    )
    review_status_history: Mapped[List["ComplianceAssessmentStatusHistory"]] = relationship(
        "ComplianceAssessmentStatusHistory",
        back_populates="assessment",
        cascade="all, delete-orphan",
        order_by="ComplianceAssessmentStatusHistory.created_at",
    )


class ComplianceAssessmentStatusHistory(Base):
    __tablename__ = "compliance_assessment_status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("compliance_assessments.id"),
        nullable=False,
        index=True,
    )
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    from_status: Mapped[str] = mapped_column(String(50), nullable=False)
    to_status: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    assessment: Mapped["ComplianceAssessment"] = relationship(
        "ComplianceAssessment",
        back_populates="review_status_history",
    )

class ComplianceAssessmentReview(Base):
    """Append-only human review decisions; they do not change automated results."""
    __tablename__ = "compliance_assessment_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("compliance_assessments.id"), index=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    outcome: Mapped[str] = mapped_column(String(50))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    assessment: Mapped["ComplianceAssessment"] = relationship("ComplianceAssessment", back_populates="reviews")
    reviewer: Mapped["User"] = relationship("User", back_populates="assessment_reviews")

class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(255))
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(100))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    audit_metadata: Mapped[Optional[str]] = mapped_column(Text) # JSON string of metadata

class ValidationRun(Base):
    __tablename__ = "validation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_status: Mapped[str] = mapped_column(String(50))
    outcome: Mapped[str] = mapped_column(String(50))
    stage_outcomes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    error_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evaluated_rules_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    not_evaluated_rules_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    not_applicable_rules_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    application: Mapped["Application"] = relationship("Application")
    user: Mapped["User"] = relationship("User")
    assessments: Mapped[List["ComplianceAssessment"]] = relationship(
        "ComplianceAssessment",
        secondary="validation_run_assessments",
    )


class ImageEvidence(Base):
    __tablename__ = "image_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    uploader_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    validation_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("validation_runs.id"),
        nullable=True,
        index=True,
    )
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    processing_status: Mapped[str] = mapped_column(String(50), nullable=False)
    analysis_result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    application: Mapped["Application"] = relationship("Application")
    uploader: Mapped["User"] = relationship("User")
    validation_run: Mapped[Optional["ValidationRun"]] = relationship("ValidationRun")


validation_run_assessments = Table(
    "validation_run_assessments",
    Base.metadata,
    Column("validation_run_id", ForeignKey("validation_runs.id"), primary_key=True),
    Column("assessment_id", ForeignKey("compliance_assessments.id"), primary_key=True),
)

class ConsistencyRun(Base, TimestampMixin):
    __tablename__ = "consistency_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    validation_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("validation_runs.id"), index=True, nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(50), default="completed", server_default="completed"
    ) # completed, failed
    comparisons_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )

    application: Mapped["Application"] = relationship("Application")
    results: Mapped[List["DocumentConsistencyResult"]] = relationship("DocumentConsistencyResult", back_populates="run", cascade="all, delete-orphan")

class DocumentConsistencyResult(Base, TimestampMixin):
    __tablename__ = "document_consistency_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("consistency_runs.id"), index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    field: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(50))
    val1: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    val2: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    norm1: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    norm2: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    doc1_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    doc2_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    explanation: Mapped[str] = mapped_column(Text)
    human_review_recommended: Mapped[bool] = mapped_column(Boolean, default=False)

    run: Mapped["ConsistencyRun"] = relationship("ConsistencyRun", back_populates="results")
    application: Mapped["Application"] = relationship("Application")
    doc1: Mapped["Document"] = relationship("Document", foreign_keys="[DocumentConsistencyResult.doc1_id]")
    doc2: Mapped["Document"] = relationship("Document", foreign_keys="[DocumentConsistencyResult.doc2_id]")
