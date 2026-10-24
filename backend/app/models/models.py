from datetime import datetime
from typing import List, Optional
from sqlalchemy import String, ForeignKey, DateTime, Boolean, Integer, Text, Table, Column, JSON
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    application: Mapped["Application"] = relationship("Application", back_populates="documents")
    findings: Mapped[List["Finding"]] = relationship("Finding", back_populates="document")

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
    explanation: Mapped[str] = mapped_column(Text)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)

    # Relationships
    application: Mapped["Application"] = relationship("Application", back_populates="assessments")
    rule: Mapped["ComplianceRule"] = relationship("ComplianceRule", back_populates="assessments")
    reviewer: Mapped[Optional["User"]] = relationship("User", back_populates="assessments")

class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(255))
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(100))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    audit_metadata: Mapped[Optional[str]] = mapped_column(Text) # JSON string of metadata

class ConsistencyRun(Base, TimestampMixin):
    __tablename__ = "consistency_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="completed") # completed, failed
    comparisons_count: Mapped[int] = mapped_column(Integer, default=0)

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
