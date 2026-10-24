from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, File, Form, UploadFile
from sqlalchemy.orm import Session
from typing import List
from app.db.session import get_db
from app.models.models import Application, User, Document, ComplianceAssessment, ComplianceRule, AuditEvent, Institution, Finding, FindingReview, DocumentConsistencyResult, ConsistencyRun
from app.schemas.applications import (
    ApplicationCreate,
    ApplicationUpdate,
    ApplicationOut,
    DocumentOut,
    DocumentProcessingOut,
    DocumentValidationPreviewOut,
    DocumentIntegrityPreviewOut,
    ConsistencyRunHistoryOut,
    FindingOut,
    FindingReviewCreate,
    FindingReviewOut,
    ApplicationChecklistOut,
)
from app.api.deps import get_current_user, RoleChecker
from app.models.enums import UserRole
from app.services.regulatory_validation import (
    load_registry,
    evaluate_rule_result,
    evaluate_preview_eligibility,
    build_preview_context,
    RegistryValidationError,
)
from app.services.document_processing import process_pdf, DocumentLimitError, DocumentProcessingError
from app.services.checklists import ChecklistConfigError, load_checklists, parse_unambiguous_date
from app.services.documents import store_pdf, DocumentStorageError, DocumentTooLargeError, InvalidPDFError
from app.services.consistency import ConsistencyService, ComparisonResult
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from fastapi.responses import FileResponse
from pypdf import PdfReader
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

def _get_authorized_application(
    application_id: int,
    db: Session,
    current_user: User,
) -> Application:
    application = db.query(Application).filter(Application.id == application_id).first()
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    if current_user.role == UserRole.ADMIN.value:
        return application
    if current_user.role == UserRole.INSTITUTION_USER.value:
        if current_user.institution_id is None or application.institution_id != current_user.institution_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
        return application
    if current_user.role == UserRole.REVIEWER.value:
        assigned = db.query(ComplianceAssessment.id).filter(
            ComplianceAssessment.application_id == application_id,
            ComplianceAssessment.reviewer_id == current_user.id,
        ).first()
        if assigned:
            return application
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this application")

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this application")


@router.post("/{application_id}/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def upload_document(
    application_id: int,
    file: UploadFile = File(...),
    doc_type: str = Form("supporting_document", max_length=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    application = _get_authorized_application(application_id, db, current_user)
    try:
        stored_pdf = store_pdf(
            file.file,
            file.filename or "",
            settings.DOCUMENT_STORAGE_DIR,
            settings.DOCUMENT_MAX_SIZE_BYTES,
        )
    except DocumentTooLargeError:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Document exceeds the maximum allowed size")
    except InvalidPDFError:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Only valid PDF documents are supported")
    except DocumentStorageError:
        logger.exception("Could not store uploaded document")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not store document")

    document = Document(
        application_id=application.id,
        doc_type=doc_type,
        original_filename=stored_pdf.original_filename,
        storage_key=stored_pdf.storage_key,
        sha256=stored_pdf.sha256,
        file_size=stored_pdf.file_size,
        processing_status="pending",
    )
    try:
        db.add(document)
        db.flush()
        db.refresh(document)
        duplicate_matches = db.query(Document).filter(
            Document.application_id == application.id,
            Document.sha256 == document.sha256,
            Document.id != document.id,
        ).order_by(Document.id).all()
        db.add(
            AuditEvent(
                user_id=current_user.id,
                action="document.uploaded",
                entity_type="document",
                entity_id=str(document.id),
                audit_metadata=json.dumps(
                    {
                        "application_id": application.id,
                        "doc_type": document.doc_type,
                        "file_size": document.file_size,
                    }
                ),
            )
        )
        for match in duplicate_matches:
            description = (
                f"Document bytes exactly match document ID {match.id} in this application "
                "(SHA-256 comparison). This is an advisory duplicate indicator, not a fraud finding."
            )
            db.add(Finding(
                application_id=application.id,
                document_id=document.id,
                finding_type="Duplicate document",
                severity="Low",
                description=description,
                status="open",
            ))
            db.add(AuditEvent(
                user_id=current_user.id,
                action="document.duplicate_detected",
                entity_type="document",
                entity_id=str(document.id),
                audit_metadata=json.dumps({"application_id": application.id, "matched_document_id": match.id}),
            ))
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        try:
            (Path(settings.DOCUMENT_STORAGE_DIR) / stored_pdf.storage_key).unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not clean up the uploaded file after metadata persistence failed")
        logger.exception("Failed to persist uploaded document metadata")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not save document metadata")

    return document


@router.get("/{application_id}/documents", response_model=List[DocumentOut])
def list_documents(
    application_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_authorized_application(application_id, db, current_user)
    return db.query(Document).filter(
        Document.application_id == application_id
    ).order_by(Document.created_at.desc()).all()


@router.get("/{application_id}/documents/{document_id}/download")
def download_document(
    application_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_authorized_application(application_id, db, current_user)
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.application_id == application_id,
    ).first()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    storage_directory = Path(settings.DOCUMENT_STORAGE_DIR).resolve()
    storage_path = (storage_directory / document.storage_key).resolve()
    if storage_path.parent != storage_directory or not storage_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    return FileResponse(
        storage_path,
        media_type="application/pdf",
        filename=document.original_filename,
    )


@router.get(
    "/{application_id}/documents/{document_id}/integrity-preview",
    response_model=DocumentIntegrityPreviewOut,
)
def document_integrity_preview(
    application_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    application = _get_authorized_application(application_id, db, current_user)
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.application_id == application.id,
    ).first()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    duplicate_matches = []
    if document.sha256:
        duplicate_matches = (
            db.query(Document)
            .filter(
                Document.application_id == application.id,
                Document.sha256 == document.sha256,
                Document.id != document.id,
            )
            .order_by(Document.id)
            .all()
        )

    storage_directory = Path(settings.DOCUMENT_STORAGE_DIR).resolve()
    storage_path = (storage_directory / document.storage_key).resolve()
    page_count = None
    encrypted = None
    pdf_readable = False
    metadata_keys: list[str] = []
    if storage_path.parent == storage_directory and storage_path.is_file():
        try:
            reader = PdfReader(str(storage_path), strict=True)
            encrypted = reader.is_encrypted
            pdf_readable = True
            if not encrypted:
                page_count = len(reader.pages)
                metadata = reader.metadata
                if metadata:
                    metadata_keys = sorted(
                        str(key).lstrip("/")
                        for key in metadata.keys()
                        if str(key).lstrip("/")
                    )
        except (OSError, PdfReadError, ValueError):
            logger.info(
                "PDF structure could not be inspected for document_id=%s",
                document.id,
            )

    return {
        "application_id": application.id,
        "document_id": document.id,
        "sha256": document.sha256,
        "duplicate_file_check": {
            "status": (
                "unknown"
                if document.sha256 is None
                else "duplicate" if duplicate_matches else "no_duplicate"
            ),
            "explanation": (
                "A matching SHA-256 hash was found among documents attached to this application."
                if duplicate_matches
                else "No matching SHA-256 hash was found among documents attached to this application."
                if document.sha256
                else "A stored SHA-256 hash is unavailable."
            ),
            "matches": [
                {
                    "document_id": match.id,
                    "original_filename": match.original_filename,
                }
                for match in duplicate_matches
            ],
        },
        "pdf_structure_check": {
            "status": (
                "unknown" if not pdf_readable else "encrypted" if encrypted else "readable"
            ),
            "explanation": (
                "PDF structure could not be inspected."
                if not pdf_readable
                else "The PDF is encrypted; structural inspection was limited."
                if encrypted
                else f"The PDF parser read {page_count} page(s). Parser readability does not establish authenticity."
            ),
            "matches": [],
        },
        "metadata_check": {
            "status": (
                "unknown" if not pdf_readable or encrypted
                else "present" if metadata_keys
                else "not_available"
            ),
            "explanation": (
                f"PDF metadata fields are present: {', '.join(metadata_keys)}. Metadata is user-controlled and can be edited."
                if metadata_keys
                else "PDF metadata could not be inspected."
                if not pdf_readable or encrypted
                else "No PDF metadata fields were detected. This is not evidence of forgery."
            ),
            "matches": [],
        },
        "issuer_verification": "not_performed",
        "authenticity_status": "not_assessed",
        "limitations": [
            "Duplicate-file comparison is limited to documents attached to this application.",
            "A matching hash identifies identical file bytes; it does not establish whether a document is genuine.",
            "PDF metadata and parser readability are user-controlled/heuristic signals, not authenticity evidence.",
            "No external issuer verification, fraud determination, or compliance decision was performed.",
        ],
    }


@router.post(
    "/{application_id}/documents/{document_id}/integrity-check",
    response_model=DocumentIntegrityPreviewOut,
)
def persist_document_integrity_check(
    application_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    preview = document_integrity_preview(application_id, document_id, db, current_user)
    if preview["pdf_structure_check"]["status"] == "unknown":
        description = "PDF structural inspection could not read the stored file. This is a processing warning and does not establish tampering or fraud."
        exists = db.query(Finding.id).filter(
            Finding.application_id == application_id,
            Finding.document_id == document_id,
            Finding.finding_type == "Document inspection warning",
            Finding.description == description,
            Finding.status == "open",
        ).first()
        if not exists:
            db.add(Finding(
                application_id=application_id,
                document_id=document_id,
                finding_type="Document inspection warning",
                severity="Medium",
                description=description,
                status="open",
            ))
    db.add(AuditEvent(
        user_id=current_user.id,
        action="document.integrity_checked",
        entity_type="document",
        entity_id=str(document_id),
        audit_metadata=json.dumps({"application_id": application_id, "pdf_structure": preview["pdf_structure_check"]["status"], "duplicate_check": preview["duplicate_file_check"]["status"]}),
    ))
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not save integrity check results")
    return preview


@router.post(
    "/{application_id}/documents/{document_id}/process",
    response_model=DocumentProcessingOut,
)
def process_document(
    application_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_authorized_application(application_id, db, current_user)
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.application_id == application_id,
    ).first()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if document.processing_status in {"completed", "ocr_unavailable"} and document.processing_result:
        return DocumentProcessingOut(
            document_id=document.id,
            processed_at=document.processed_at,
            **document.processing_result,
        )

    claim = db.execute(
        update(Document)
        .where(
            Document.id == document_id,
            Document.processing_status.in_(("pending", "failed")),
        )
        .values(processing_status="processing", processing_result=None)
        .execution_options(synchronize_session=False)
    )
    if claim.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document processing is already in progress",
        )
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not start document processing")

    storage_directory = Path(settings.DOCUMENT_STORAGE_DIR).resolve()
    storage_path = (storage_directory / document.storage_key).resolve()
    if storage_path.parent != storage_directory or not storage_path.is_file():
        document.processing_status = "failed"
        db.add(
            AuditEvent(
                user_id=current_user.id,
                action="document.processing_failed",
                entity_type="document",
                entity_id=str(document.id),
                audit_metadata=json.dumps({"reason": "stored_file_unavailable"}),
            )
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    try:
        result = process_pdf(
            storage_path,
            max_file_size=settings.DOCUMENT_MAX_SIZE_BYTES,
            max_pages=settings.DOCUMENT_PROCESSING_MAX_PAGES,
            max_seconds=settings.DOCUMENT_PROCESSING_MAX_SECONDS,
            max_text_chars=settings.DOCUMENT_PROCESSING_MAX_TEXT_CHARS,
            ocr_page_timeout=settings.DOCUMENT_OCR_PAGE_TIMEOUT_SECONDS,
            tesseract_cmd=settings.TESSERACT_CMD,
        )
    except DocumentLimitError as exc:
        error_status = status.HTTP_422_UNPROCESSABLE_ENTITY
        error_detail = str(exc)
    except DocumentProcessingError as exc:
        error_status = status.HTTP_422_UNPROCESSABLE_ENTITY
        error_detail = str(exc)
    else:
        document.processing_status = result["processing_status"]
        document.processing_result = result
        document.processed_at = datetime.now(timezone.utc)
        db.add(
            AuditEvent(
                user_id=current_user.id,
                action="document.processed",
                entity_type="document",
                entity_id=str(document.id),
                audit_metadata=json.dumps(
                {
                    "processing_status": result["processing_status"],
                    "extraction_method": result["extraction_method"],
                    "pages_processed": result["pages_processed"],
                }
                ),
            )
        )
        try:
            db.commit()
        except SQLAlchemyError:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not save document processing results")
        return DocumentProcessingOut(
            document_id=document.id,
            processed_at=document.processed_at,
            **result,
        )

    document.processing_status = "failed"
    document.processing_result = {
        "processing_status": "failed",
        "extraction_method": "none",
        "pages_processed": 0,
        "fields": {},
        "warnings": [error_detail],
    }
    document.processed_at = datetime.now(timezone.utc)
    db.add(
            AuditEvent(
                user_id=current_user.id,
                action="document.processing_failed",
                entity_type="document",
                entity_id=str(document.id),
                audit_metadata=json.dumps({"processing_status": "failed"}),
            )
        )
    try:
        db.commit()
    except SQLAlchemyError:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not save document processing status")
    raise HTTPException(status_code=error_status, detail=error_detail)


@router.post(
    "/{application_id}/documents/{document_id}/validate",
    response_model=DocumentValidationPreviewOut,
)
def validate_document(
    application_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    application = _get_authorized_application(application_id, db, current_user)
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.application_id == application.id,
    ).first()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if document.processing_status != "completed" or not document.processing_result:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document must complete processing before validation preview",
        )

    try:
        rules = load_registry()
    except RegistryValidationError as exc:
        logger.exception("Could not load fire-safety preview registry")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Validation preview is temporarily unavailable",
        ) from exc

    stored_result = document.processing_result
    raw_fields = stored_result.get("fields", {})
    if not isinstance(raw_fields, dict) or any(
        not isinstance(name, str) or not isinstance(field, dict)
        for name, field in raw_fields.items()
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stored document processing results are unavailable",
        )
    fields = {
        name: {**field, "verification_status": "unverified"}
        for name, field in raw_fields.items()
    }
    extraction_method = stored_result.get("extraction_method", "unknown")
    warnings = stored_result.get("warnings", [])
    if not isinstance(extraction_method, str) or not isinstance(warnings, list) or not all(
        isinstance(warning, str) for warning in warnings
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stored document processing results are unavailable",
        )
    document_evidence = {
        "document_id": document.id,
        "processing_status": document.processing_status,
        "extraction_method": extraction_method,
        "processed_at": document.processed_at,
        "fields": fields,
        "warnings": warnings,
    }

    application_scope = None
    contexts = [
        build_preview_context(rule, application_scope, document_evidence)
        for rule in rules
    ]
    candidates = []
    checks = []
    for context in contexts:
        candidate = context["candidate_rule"]
        rule_evidence = context["rule_evidence"]
        candidates.append(
            {
                "rule_id": candidate["rule_id"],
                "document_type": candidate["document_type"],
                "candidate_requirement": candidate["candidate_requirement"],
                "known_scope": candidate["scope"]["known_scope"],
                "source_mapping_review": candidate["source_mapping_review"],
                "currentness_review": candidate["currentness_review"],
                "applicability_review": candidate["applicability_review"],
                "preview_approved": candidate["preview_approved"],
                "eligibility": context["eligibility"],
                "evidence": rule_evidence,
            }
        )
        checks.append(
            {
                "rule_id": candidate["rule_id"],
                "status": context["evaluation_status"],
                "reason": context["check_reason"],
            }
        )

    overall_status = (
        "not_assessed"
        if any(item["status"] == "not_assessed" for item in checks)
        else "unknown"
    )
    return {
        "application_id": application.id,
        "document_id": document.id,
        "application_scope_status": "unknown",
        "overall_status": overall_status,
        "document_evidence": document_evidence,
        "candidate_rules": candidates,
        "checks": checks,
        "limitations": [
            "Application scope is unknown because the existing model has no reviewed structured scope facts; free-form app_type is not used.",
            "Extracted fields, including OCR output, are unverified evidence.",
            "A preview result does not determine document authenticity, fraud, or institutional compliance.",
            "No certificate validity duration or expiry policy is inferred.",
        ],
        "warnings": list(warnings),
    }


@router.post("/{application_id}/validate-all", status_code=status.HTTP_200_OK)
def validate_application_all(
    application_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    application = _get_authorized_application(application_id, db, current_user)

    try:
        rules_registry = load_registry()
    except RegistryValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Regulatory registry unavailable: {str(exc)}"
        )

    documents = db.query(Document).filter(
        Document.application_id == application.id,
        Document.processing_status == "completed"
    ).all()

    if not documents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No processed documents available for validation"
        )

    results = []
    findings_to_create = []
    docs_by_type = {doc.doc_type: doc for doc in documents}
    # Application scope mapping
    # In a real system, this would be derived from Application.app_type.
    # For the demonstration, we map specific app_types to categories.
    app_type_to_category = {
        "Standard Regulatory": "Standard",
        "Technical Institution": "Technical",
        "Medical College": "Medical",
    }

    category = app_type_to_category.get(application.app_type)
    if not category:
        application_scope = None
    else:
        application_scope = {"institution_category": category}

    for rule in rules_registry:
        eligibility = evaluate_preview_eligibility(rule, application_scope)

        if eligibility == "not_applicable":
            res = {
                "rule_id": rule["rule_id"],
                "status": "Not-Applicable",
                "explanation": "The application scope does not match this rule.",
                "evidence": None
            }
            results.append(res)
            continue

        if eligibility == "unknown":
            res = {
                "rule_id": rule["rule_id"],
                "status": "Not evaluated",
                "explanation": "Application scope or required evidence is unavailable.",
                "evidence": None
            }
            results.append(res)
            continue

        doc = docs_by_type.get(rule["document_type"])
        if not doc:
            res = {
                "rule_id": rule["rule_id"],
                "status": "Fail",
                "explanation": f"Required document of type '{rule['document_type']}' is missing.",
                "evidence": None
            }
            results.append(res)
            findings_to_create.append({
                "finding_type": "Missing Document",
                "severity": "High",
                "description": f"Missing required document: {rule['document_type']}",
                "document_id": None
            })
            continue

        doc_evidence = {
            "document_id": doc.id,
            "fields": doc.processing_result.get("fields", {}) if doc.processing_result else {}
        }
        eval_result = evaluate_rule_result(rule, doc_evidence)

        status_map = {
            "Pass": "Compliant",
            "Fail": "Non-Compliant",
            "Needs review": "Partial",
            "Not evaluated": "Not-Applicable"
        }

        final_status = status_map.get(eval_result["status"], "Non-Compliant")

        res = {
            "rule_id": rule["rule_id"],
            "status": final_status,
            "explanation": eval_result["explanation"],
            "evidence": eval_result["evidence"]
        }
        results.append(res)

        if eval_result["status"] == "Fail":
            findings_to_create.append({
                "finding_type": "Regulatory Violation",
                "severity": "High",
                "description": eval_result["explanation"],
                "document_id": doc.id
            })
        elif eval_result["status"] == "Needs review":
            findings_to_create.append({
                "finding_type": "Verification Required",
                "severity": "Medium",
                "description": eval_result["explanation"],
                "document_id": doc.id
            })

    for r in results:
        db_rule = db.query(ComplianceRule).filter(ComplianceRule.rule_code == r["rule_id"]).first()
        if not db_rule:
            db_rule = ComplianceRule(
                rule_code=r["rule_id"],
                title=f"Rule {r['rule_id']}",
                description="Synthetic rule from registry",
                category="Fire Safety",
                is_active=True
            )
            db.add(db_rule)
            db.flush()

        assessment = ComplianceAssessment(
            application_id=application.id,
            rule_id=db_rule.id,
            status=r["status"],
            explanation=r["explanation"],
            reviewer_id=None
        )
        db.add(assessment)

    for f in findings_to_create:
        finding = Finding(
            application_id=application.id,
            document_id=f["document_id"],
            finding_type=f["finding_type"],
            severity=f["severity"],
            description=f["description"],
            status="open"
        )
        db.add(finding)

    db.add(AuditEvent(
        user_id=current_user.id,
        action="application.validate_all",
        entity_type="application",
        entity_id=str(application.id),
        audit_metadata=json.dumps({"rules_evaluated": len(results), "findings_created": len(findings_to_create)})
    ))

    db.commit()

    return {
        "application_id": application.id,
        "results": results,
        "findings_count": len(findings_to_create),
        "status": "completed"
    }

@router.post("/{application_id}/validate-consistency", status_code=status.HTTP_200_OK)
def validate_application_consistency(
    application_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    application = _get_authorized_application(application_id, db, current_user)

    documents = db.query(Document).filter(
        Document.application_id == application.id,
        Document.processing_status == "completed"
    ).all()

    if len(documents) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Consistency validation requires at least two processed documents."
        )

    consistency_svc = ConsistencyService()
    results_to_persist = []

    # Compare documents in pairs to check consistency across the application
    # For a real system, we might have specific pairings (e.g., Certificate vs. Application Form)
    for i in range(len(documents)):
        for j in range(i + 1, len(documents)):
            doc1 = documents[i]
            doc2 = documents[j]

            fields1 = doc1.processing_result.get("fields", {}) if doc1.processing_result else {}
            fields2 = doc2.processing_result.get("fields", {}) if doc2.processing_result else {}

            for field_name in consistency_svc.comparable_fields:
                val1 = fields1.get(field_name)
                val2 = fields2.get(field_name)

                comparison = consistency_svc.compare_fields(
                    field_name, val1, doc1.id, val2, doc2.id
                )

                # We only persist results that aren't "NOT_APPLICABLE"
                if comparison.category != "NOT_APPLICABLE":
                    results_to_persist.append(comparison)

    try:
        run = ConsistencyRun(
            application_id=application.id,
            user_id=current_user.id,
            status="completed",
            comparisons_count=len(results_to_persist),
        )
        db.add(run)
        db.flush()

        for res in results_to_persist:
            db_res = DocumentConsistencyResult(
                run=run,
                application_id=application.id,
                field=res.field,
                category=res.category,
                val1=res.val1,
                val2=res.val2,
                norm1=res.norm1,
                norm2=res.norm2,
                doc1_id=res.doc1_id,
                doc2_id=res.doc2_id,
                explanation=res.explanation,
                human_review_recommended=res.human_review_recommended
            )
            db.add(db_res)

        db.add(AuditEvent(
            user_id=current_user.id,
            action="application.validate_consistency",
            entity_type="application",
            entity_id=str(application.id),
            audit_metadata=json.dumps({"comparisons_performed": len(results_to_persist)})
        ))

        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Failed to persist consistency validation")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Consistency validation could not be saved.",
        ) from exc

    return {
        "application_id": application.id,
        "run_id": run.id,
        "consistency_results_count": len(results_to_persist),
        "status": "completed"
    }


@router.get("/{application_id}/consistency-runs", response_model=ConsistencyRunHistoryOut)
def list_consistency_runs(
    application_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_authorized_application(application_id, db, current_user)
    runs = (
        db.query(ConsistencyRun)
        .filter(ConsistencyRun.application_id == application_id)
        .order_by(ConsistencyRun.created_at.desc(), ConsistencyRun.id.desc())
        .all()
    )
    return {
        "items": [
            {
                "id": run.id,
                "application_id": run.application_id,
                "status": run.status,
                "comparisons_count": run.comparisons_count,
                "created_at": run.created_at,
                "results": [
                    {
                        "id": result.id,
                        "run_id": result.run_id,
                        "application_id": result.application_id,
                        "field": result.field,
                        "category": result.category,
                        "val1": result.val1,
                        "val2": result.val2,
                        "explanation": result.explanation,
                        "human_review_recommended": result.human_review_recommended,
                        "doc1_id": result.doc1_id,
                        "doc1_filename": result.doc1.original_filename,
                        "doc2_id": result.doc2_id,
                        "doc2_filename": result.doc2.original_filename,
                    }
                    for result in run.results
                ],
            }
            for run in runs
        ]
    }


@router.get("/{application_id}/findings", response_model=List[FindingOut])
def list_application_findings(
    application_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_authorized_application(application_id, db, current_user)
    findings = (
        db.query(Finding)
        .filter(Finding.application_id == application_id)
        .order_by(Finding.created_at.desc(), Finding.id.desc())
        .all()
    )
    return [
        {
            "id": finding.id,
            "application_id": finding.application_id,
            "document_id": finding.document_id,
            "finding_type": finding.finding_type,
            "severity": finding.severity,
            "description": finding.description,
            "status": finding.status,
            "created_at": finding.created_at,
            "reviews": [
                {
                    "id": review.id,
                    "finding_id": review.finding_id,
                    "reviewer_id": review.reviewer_id,
                    "reviewer_name": review.reviewer.full_name,
                    "outcome": review.outcome,
                    "note": review.note,
                    "created_at": review.created_at,
                }
                for review in db.query(FindingReview).filter(FindingReview.finding_id == finding.id).order_by(FindingReview.created_at, FindingReview.id).all()
            ],
        }
        for finding in findings
    ]


@router.post("/{application_id}/validate-checklist", response_model=ApplicationChecklistOut)
def validate_application_checklist(
    application_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    application = _get_authorized_application(application_id, db, current_user)
    try:
        checklist_by_category = load_checklists()
    except ChecklistConfigError as exc:
        logger.exception("Could not load synthetic application checklist configuration")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application checklist configuration is unavailable",
        ) from exc

    # This versioned configuration is synthetic demo content, not official AICTE policy.
    requirements = checklist_by_category.get(application.app_type)
    if requirements is None:
        raise HTTPException(status_code=422, detail="No synthetic checklist is configured for this application category")

    documents = db.query(Document).filter(Document.application_id == application.id).all()
    by_type: dict[str, list[Document]] = {}
    for document in documents:
        by_type.setdefault(document.doc_type, []).append(document)
    items = []
    findings_created = 0
    for doc_type, requirement in requirements.items():
        required_fields = requirement["required_fields"]
        expiry_field = requirement.get("expiry_field")
        matches = by_type.get(doc_type, [])
        missing_fields: list[str] = []
        linked_document = matches[-1] if matches else None
        if not matches:
            check_status = "missing_document"
            explanation = f"No document of type '{doc_type}' is attached to this application."
        elif any(document.processing_status == "pending" or document.processing_status == "processing" for document in matches):
            check_status = "processing_pending"
            explanation = "A matching document is attached but processing is pending; required extracted fields cannot yet be checked."
        elif all(document.processing_status in {"failed", "ocr_unavailable"} for document in matches):
            check_status = "processing_failed"
            explanation = "Matching document(s) are attached, but processing failed or OCR was unavailable; completeness could not be assessed."
        else:
            completed = [document for document in matches if document.processing_status == "completed"]
            processing_result = completed[-1].processing_result if completed and completed[-1].processing_result else {}
            fields = processing_result.get("fields", {})
            missing_fields = [name for name in required_fields if not isinstance(fields.get(name), dict) or not fields[name].get("value")]
            if missing_fields:
                check_status = "incomplete_fields"
                explanation = "Required fields were not extracted: " + ", ".join(missing_fields) + ". Extraction can miss information; reviewer inspection is required."
                linked_document = completed[-1]
            else:
                linked_document = completed[-1]
                expiry_value = fields.get(expiry_field, {}).get("value") if expiry_field else None
                if expiry_field and expiry_value:
                    extraction_method = processing_result.get("extraction_method")
                    expiry_confidence = fields[expiry_field].get("confidence")
                    parsed_expiry = parse_unambiguous_date(str(expiry_value))
                    low_confidence_ocr = (
                        extraction_method in {"ocr", "mixed"}
                        and (not isinstance(expiry_confidence, (int, float)) or expiry_confidence < 0.8)
                    )
                    if parsed_expiry is None or low_confidence_ocr:
                        check_status = "expiry_unverified"
                        explanation = (
                            f"The extracted {expiry_field} value '{expiry_value}' could not be interpreted "
                            "reliably. Confirm the date from the source document; no expiry conclusion was made."
                        )
                    elif parsed_expiry < datetime.now(timezone.utc).date():
                        check_status = "expired_document"
                        explanation = (
                            f"The extracted {expiry_field} value is {parsed_expiry.isoformat()}, which is before "
                            "today. This is an advisory date check, not a legal determination. A reviewer must confirm the source and applicability."
                        )
                    else:
                        check_status = "received"
                        explanation = "The configured fields were extracted and the expiry date is not before today; values remain unverified."
                else:
                    check_status = "received"
                    explanation = "A processed document is attached and the configured required fields were extracted; values remain unverified."
        if check_status != "received":
            description = f"Synthetic checklist requirement '{doc_type}' is {check_status}. {explanation}"
            exists = db.query(Finding.id).filter(
                Finding.application_id == application.id,
                Finding.document_id == (linked_document.id if linked_document else None),
                Finding.finding_type == "Checklist completeness",
                Finding.description == description,
                Finding.status == "open",
            ).first()
            if not exists:
                db.add(Finding(
                    application_id=application.id,
                    document_id=linked_document.id if linked_document else None,
                    finding_type=("Checklist expiry review" if check_status in {"expired_document", "expiry_unverified"} else "Checklist completeness"),
                    severity="Medium" if check_status in {"processing_pending", "processing_failed", "expired_document", "expiry_unverified"} else "High",
                    description=description,
                    status="open",
                ))
                findings_created += 1
        items.append({
            "document_type": doc_type,
            "status": check_status,
            "document_ids": [document.id for document in matches],
            "missing_fields": missing_fields,
            "explanation": explanation,
        })
    db.add(AuditEvent(
        user_id=current_user.id,
        action="application.checklist_validated",
        entity_type="application",
        entity_id=str(application.id),
        audit_metadata=json.dumps({"category": application.app_type, "findings_created": findings_created}),
    ))
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not save checklist findings")
    return {"application_id": application.id, "category": application.app_type, "source": "synthetic_demo", "items": items}


@router.post("/{application_id}/findings/{finding_id}/reviews", response_model=FindingReviewOut, status_code=status.HTTP_201_CREATED)
def review_application_finding(
    application_id: int,
    finding_id: int,
    review_in: FindingReviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.REVIEWER.value:
        raise HTTPException(status_code=403, detail="Only assigned reviewers can record finding decisions")
    application = _get_authorized_application(application_id, db, current_user)
    finding = db.query(Finding).filter(
        Finding.id == finding_id,
        Finding.application_id == application.id,
    ).first()
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    review = FindingReview(
        finding_id=finding.id,
        reviewer_id=current_user.id,
        outcome=review_in.outcome,
        note=review_in.note,
    )
    db.add(review)
    db.add(AuditEvent(
        user_id=current_user.id,
        action="finding.review_recorded",
        entity_type="finding",
        entity_id=str(finding.id),
        audit_metadata=json.dumps({"application_id": application.id, "outcome": review_in.outcome}),
    ))
    try:
        db.commit()
        db.refresh(review)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not save reviewer decision")
    return {"id": review.id, "finding_id": finding.id, "outcome": review.outcome, "reviewer_id": current_user.id, "reviewer_name": current_user.full_name, "note": review.note, "created_at": review.created_at}

@router.post("/", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
def create_application(
    application_in: ApplicationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in {
        UserRole.INSTITUTION_USER.value,
        UserRole.ADMIN.value,
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only institution users and administrators can create applications",
        )

    if current_user.role == UserRole.INSTITUTION_USER and current_user.institution_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must be assigned to an institution to create an application"
        )

    if current_user.role == UserRole.ADMIN.value and application_in.institution_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Administrators must select an institution for the application",
        )
    if current_user.role == UserRole.INSTITUTION_USER.value and application_in.institution_id is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Institution users cannot select an institution",
        )
    selected_institution_id = (
        application_in.institution_id
        if current_user.role == UserRole.ADMIN.value
        else current_user.institution_id
    )
    if selected_institution_id is not None and db.query(Institution.id).filter(
        Institution.id == selected_institution_id
    ).first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Institution not found",
        )

    # Check if reference already exists
    existing = db.query(Application).filter(Application.reference == application_in.reference).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Application with this reference already exists"
        )

    new_app = Application(
        reference=application_in.reference,
        entity_name=application_in.entity_name,
        app_type=application_in.app_type,
        status="submitted",
        institution_id=selected_institution_id,
    )
    db.add(new_app)
    try:
        db.flush()
        db.add(
            AuditEvent(
                user_id=current_user.id,
                action="application.created",
                entity_type="application",
                entity_id=str(new_app.id),
                audit_metadata=json.dumps({"reference": new_app.reference}),
            )
        )
        db.commit()
        db.refresh(new_app)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Application with this reference already exists",
        ) from None
    return new_app


@router.get("/", response_model=List[ApplicationOut])
def list_applications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Application)

    if current_user.role == UserRole.INSTITUTION_USER:
        if current_user.institution_id is None:
            return [] # Or raise 403
        query = query.filter(Application.institution_id == current_user.institution_id)
    elif current_user.role == UserRole.REVIEWER:
        # Reviewers access based on assignments (ComplianceAssessment.reviewer_id)
        from app.models.models import ComplianceAssessment
        subquery = db.query(ComplianceAssessment.application_id).filter(
            ComplianceAssessment.reviewer_id == current_user.id
        )
        query = query.filter(Application.id.in_(subquery))
    elif current_user.role == UserRole.ADMIN:
        # Admin sees everything
        pass
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to list applications",
        )

    return query.order_by(Application.created_at.desc()).all()


@router.get("/{application_id}", response_model=ApplicationOut)
def get_application(
    application_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    app_obj = db.query(Application).filter(Application.id == application_id).first()
    if not app_obj:
        raise HTTPException(status_code=404, detail="Application not found")

    # Authorization
    if current_user.role == UserRole.INSTITUTION_USER:
        if app_obj.institution_id != current_user.institution_id:
            # Return 404 to avoid leaking existence of other institutions' apps
            raise HTTPException(status_code=404, detail="Application not found")
    elif current_user.role == UserRole.REVIEWER:
        from app.models.models import ComplianceAssessment
        assigned = db.query(ComplianceAssessment).filter(
            ComplianceAssessment.application_id == application_id,
            ComplianceAssessment.reviewer_id == current_user.id
        ).first()
        if not assigned:
            raise HTTPException(status_code=403, detail="Not authorized to review this application")
    elif current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this application",
        )

    return app_obj


@router.patch("/{application_id}", response_model=ApplicationOut)
def update_application(
    application_id: int,
    application_in: ApplicationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in {
        UserRole.INSTITUTION_USER.value,
        UserRole.REVIEWER.value,
        UserRole.ADMIN.value,
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update applications",
        )

    app_obj = db.query(Application).filter(Application.id == application_id).first()
    if not app_obj:
        raise HTTPException(status_code=404, detail="Application not found")

    # Authorization
    if current_user.role == UserRole.INSTITUTION_USER:
        if current_user.institution_id is None or app_obj.institution_id != current_user.institution_id:
            raise HTTPException(status_code=404, detail="Application not found")
    elif current_user.role == UserRole.REVIEWER:
        L_assessment = db.query(ComplianceAssessment).filter(
            ComplianceAssessment.application_id == application_id,
            ComplianceAssessment.reviewer_id == current_user.id
        ).first()
        if not L_assessment:
            raise HTTPException(status_code=403, detail="Not authorized to update this application")

    update_data = application_in.model_dump(exclude_unset=True)
    if current_user.role == UserRole.INSTITUTION_USER.value and "status" in update_data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Institution users cannot change application status",
        )
    if current_user.role == UserRole.REVIEWER.value and set(update_data) - {"status"}:
        raise HTTPException(
            status_code=status.HTTP_403_L_FORBIDDEN, detail="Reviewers can update application status only")
    for field, value in update_data.items():
        setattr(app_obj, field, value)

    if update_data:
        db.add(
            AuditEvent(
                user_id=current_user.id,
                action="application.updated",
                entity_type="application",
                entity_id=str(app_obj.id),
                audit_metadata=json.dumps({"changed_fields": sorted(update_data)}),
            )
        )
    db.commit()
    db.refresh(app_obj)
    return app_obj
