from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, File, Form, UploadFile, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.db.session import get_db
from app.models.models import Application, User, Document, ComplianceAssessment, ComplianceRule, AuditEvent, Institution, Finding, FindingReview, DocumentConsistencyResult, ConsistencyRun, ValidationRun, ImageEvidence
from app.models.models import DocumentSchemaVersion, DocumentType, DocumentTypeCorrection
from app.schemas.applications import (
    ApplicationCreate,
    ApplicationUpdate,
    ApplicationOut,
    DocumentOut,
    ImageEvidenceOut,
    DocumentProcessingOut,
    DocumentValidationPreviewOut,
    DocumentIntegrityPreviewOut,
    ConsistencyRunHistoryOut,
    FindingOut,
    FindingReviewCreate,
    FindingReviewOut,
    ApplicationChecklistOut,
    ApplicationValidationOut,
    ValidationRunHistoryOut,
)
from app.schemas.document_registry import DocumentTypeCorrectionCreate
from app.api.deps import get_current_user, RoleChecker
from app.models.enums import UserRole
from app.services.regulatory_validation import (
    load_registry,
    evaluate_rule_result,
    evaluate_preview_eligibility,
    build_preview_context,
    RegistryValidationError,
)
from app.services.document_processing import (
    FIELD_EXTRACTION_VERSION,
    process_pdf,
    DocumentLimitError,
    DocumentProcessingError,
)
from app.services.checklists import ChecklistConfigError, load_checklists, parse_unambiguous_date
from app.services.documents import store_pdf, DocumentStorageError, DocumentTooLargeError, InvalidPDFError
from app.services.image_evidence import (
    EvidenceImageStorageError,
    EvidenceImageTooLarge,
    InvalidEvidenceImage,
    store_and_assess_image,
)
from app.services.document_schema_validation import resolve_document_schema, validate_document_schema
from app.services.consistency import ConsistencyService, ComparisonResult
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
from fastapi.responses import FileResponse
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import update
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stored_file:
        for chunk in iter(lambda: stored_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    application = _get_authorized_application(application_id, db, current_user)
    return db.query(Document).filter(
        Document.application_id == application_id
    ).order_by(Document.created_at.desc()).all()


@router.post(
    "/{application_id}/image-evidence",
    response_model=ImageEvidenceOut,
    status_code=status.HTTP_201_CREATED,
)
def upload_image_evidence(
    application_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    application = _get_authorized_application(application_id, db, current_user)
    try:
        storage_key, filename, digest, file_size, analysis = store_and_assess_image(
            file.file,
            file.filename or "",
            file.content_type,
            settings.DOCUMENT_STORAGE_DIR,
        )
    except EvidenceImageTooLarge as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except InvalidEvidenceImage as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc
    except EvidenceImageStorageError as exc:
        logger.exception("Could not store image evidence")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not store image evidence",
        ) from exc

    image = ImageEvidence(
        application_id=application.id,
        uploader_id=current_user.id,
        storage_key=storage_key,
        original_filename=filename,
        content_type="image/png" if Path(filename).suffix.lower() == ".png" else "image/jpeg",
        sha256=digest,
        file_size=file_size,
        processing_status=analysis["status"],
        analysis_result=analysis,
    )
    db.add(image)
    audit_event = AuditEvent(
        user_id=current_user.id,
        action="image_evidence.quality_assessed",
        entity_type="image_evidence",
        entity_id="pending",
        audit_metadata=json.dumps({
            "application_id": application.id,
            "file_size": file_size,
            "processing_status": image.processing_status,
            "analysis_version": analysis["analysis_version"],
        }),
    )
    db.add(audit_event)
    try:
        db.flush()
        audit_event.entity_id = str(image.id)
        db.commit()
        db.refresh(image)
    except SQLAlchemyError as exc:
        db.rollback()
        try:
            (Path(settings.DOCUMENT_STORAGE_DIR) / "image-evidence" / storage_key).unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not remove image after persistence failure")
        logger.exception("Could not persist image evidence")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save image evidence results",
        ) from exc
    return image


@router.get(
    "/{application_id}/image-evidence",
    response_model=list[ImageEvidenceOut],
)
def list_image_evidence(
    application_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    application = _get_authorized_application(application_id, db, current_user)
    return (
        db.query(ImageEvidence)
        .filter(ImageEvidence.application_id == application.id)
        .order_by(ImageEvidence.created_at.desc(), ImageEvidence.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/{application_id}/image-evidence/{image_id}/file")
def download_image_evidence(
    application_id: int,
    image_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    application = _get_authorized_application(application_id, db, current_user)
    image = db.query(ImageEvidence).filter(
        ImageEvidence.id == image_id,
        ImageEvidence.application_id == application.id,
    ).first()
    if image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image evidence not found")
    image_directory = (Path(settings.DOCUMENT_STORAGE_DIR) / "image-evidence").resolve()
    path = (image_directory / image.storage_key).resolve()
    if path.parent != image_directory or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image evidence not found")
    return FileResponse(path, media_type=image.content_type, filename=image.original_filename)


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
    if not document.sha256:
        file_hash_check = {
            "status": "not_available",
            "stored_sha256": None,
            "current_sha256": None,
            "explanation": "No upload-time SHA-256 is available for comparison.",
        }
    elif storage_path.parent != storage_directory or not storage_path.is_file():
        file_hash_check = {
            "status": "unavailable",
            "stored_sha256": document.sha256,
            "current_sha256": None,
            "explanation": "The stored file is unavailable, so its current hash could not be checked.",
        }
    else:
        try:
            current_sha256 = _sha256_file(storage_path)
        except OSError:
            logger.exception(
                "Could not calculate stored-file hash for document_id=%s",
                document.id,
            )
            file_hash_check = {
                "status": "unavailable",
                "stored_sha256": document.sha256,
                "current_sha256": None,
                "explanation": "The stored file could not be read, so its current hash could not be checked.",
            }
        else:
            hash_matches = current_sha256.casefold() == document.sha256.casefold()
            file_hash_check = {
                "status": "match" if hash_matches else "mismatch",
                "stored_sha256": document.sha256,
                "current_sha256": current_sha256,
                "explanation": (
                    "The stored file bytes match the upload-time SHA-256."
                    if hash_matches
                    else "The stored file bytes differ from the upload-time SHA-256; this indicates a storage-integrity mismatch, not document fraud or authenticity."
                ),
            }
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
        "file_hash_check": file_hash_check,
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
            "The stored-file hash comparison checks whether current stored bytes match the upload-time hash; a mismatch does not establish fraud or issuer identity.",
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
        audit_metadata=json.dumps({
            "application_id": application_id,
            "pdf_structure": preview["pdf_structure_check"]["status"],
            "duplicate_check": preview["duplicate_file_check"]["status"],
            "file_hash_check": preview["file_hash_check"]["status"],
        }),
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
    application = _get_authorized_application(application_id, db, current_user)
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.application_id == application_id,
    ).first()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    stored_result = document.processing_result or {}
    schema_context, active_schema = resolve_document_schema(
        db, document.doc_type, document.original_filename, application.app_type
    )
    stored_schema = stored_result.get("schema_validation") or {}
    schema_result_is_current = (
        stored_schema.get("document_type_id") == document.doc_type
        and (
            stored_schema.get("schema_version_id") == schema_context.get("schema_version_id")
            if schema_context.get("status") == "ready"
            else stored_schema.get("status") == schema_context.get("status")
        )
    )
    extraction_result_is_current = (
        stored_result.get("field_extraction_version") == FIELD_EXTRACTION_VERSION
        and document.processed_doc_type == document.doc_type
        and schema_result_is_current
    )
    if document.processing_status == "completed" and extraction_result_is_current:
        return DocumentProcessingOut(
            document_id=document.id,
            processed_at=document.processed_at,
            **stored_result,
        )
    if (
        document.processing_status == "ocr_unavailable"
        and stored_result
        and stored_result.get("field_extraction_version") == FIELD_EXTRACTION_VERSION
    ):
        if document.processed_doc_type == document.doc_type and schema_result_is_current:
            return DocumentProcessingOut(
                document_id=document.id,
                processed_at=document.processed_at,
                **stored_result,
            )
        stored_result["schema_validation"] = validate_document_schema(
            schema_context,
            active_schema,
            stored_result.get("fields", {}),
            document.processing_status,
        )
        document.processing_result = stored_result
        document.processed_doc_type = document.doc_type
        document.schema_version_id = schema_context.get("schema_version_id")
        try:
            db.commit()
        except SQLAlchemyError as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not save document schema status",
            ) from exc
        return DocumentProcessingOut(
            document_id=document.id,
            processed_at=document.processed_at,
            **stored_result,
        )

    claim_query = update(Document).where(Document.id == document_id)
    if document.processing_status == "completed":
        # A completed result from before the current extraction version is refreshed
        # once on an explicit process request. Timestamp + status guard the claim
        # against concurrent retries without interpreting backend-specific JSON.
        claim_query = claim_query.where(
            Document.processing_status == "completed",
            Document.processed_at == document.processed_at,
        )
    else:
        claim_query = claim_query.where(
            Document.processing_status.in_(("pending", "failed", "partial"))
        )
    claim = db.execute(
        claim_query
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
        document.processing_result = {
            "processing_status": "failed",
            "extraction_method": "none",
            "pages_processed": 0,
            "fields": {},
            "schema_validation": validate_document_schema(
                schema_context, active_schema, {}, "failed"
            ),
            "warnings": ["Stored PDF is unavailable; document processing failed."],
        }
        document.processed_at = datetime.now(timezone.utc)
        document.processed_doc_type = document.doc_type
        document.schema_version_id = schema_context.get("schema_version_id")
        db.add(
            AuditEvent(
                user_id=current_user.id,
                action="document.processing_failed",
                entity_type="document",
                entity_id=str(document.id),
                audit_metadata=json.dumps({"reason": "stored_file_unavailable"}),
            )
        )
        try:
            db.commit()
        except SQLAlchemyError as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not save document processing failure",
            ) from exc
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    try:
        registered_document_types = []
        for registered_type in db.query(DocumentType).order_by(DocumentType.id).all():
            active_version = (
                db.query(DocumentSchemaVersion)
                .filter(
                    DocumentSchemaVersion.document_type_id == registered_type.id,
                    DocumentSchemaVersion.status == "active",
                )
                .order_by(
                    DocumentSchemaVersion.activated_at.desc(),
                    DocumentSchemaVersion.id.desc(),
                )
                .first()
            )
            registered_document_types.append({
                "id": registered_type.id,
                "display_name": registered_type.display_name,
                "aliases": registered_type.aliases or [],
                "status": registered_type.status,
                "active_schema_version_id": active_version.id if active_version else None,
            })
        result = process_pdf(
            storage_path,
            max_file_size=settings.DOCUMENT_MAX_SIZE_BYTES,
            max_pages=settings.DOCUMENT_PROCESSING_MAX_PAGES,
            max_seconds=settings.DOCUMENT_PROCESSING_MAX_SECONDS,
            max_text_chars=settings.DOCUMENT_PROCESSING_MAX_TEXT_CHARS,
            ocr_page_timeout=settings.DOCUMENT_OCR_PAGE_TIMEOUT_SECONDS,
            tesseract_cmd=settings.TESSERACT_CMD,
            registered_document_types=registered_document_types,
            schema_definition=active_schema.definition if active_schema else None,
        )
    except DocumentLimitError as exc:
        error_status = status.HTTP_422_UNPROCESSABLE_ENTITY
        error_detail = str(exc)
    except DocumentProcessingError as exc:
        error_status = status.HTTP_422_UNPROCESSABLE_ENTITY
        error_detail = str(exc)
    else:
        schema_validation = validate_document_schema(
            schema_context,
            active_schema,
            result.get("fields", {}),
            result["processing_status"],
        )
        result["schema_validation"] = schema_validation
        if schema_validation["status"] in {
            "unknown_type",
            "inactive_type",
            "unsupported_format",
            "unavailable",
        }:
            result["warnings"].append(schema_validation["reason"])
        elif schema_validation["status"] == "invalid":
            result["warnings"].append(
                "Extracted fields do not satisfy the active document schema; reviewer verification is required."
            )
        document.processing_status = result["processing_status"]
        document.processing_result = result
        document.processed_at = datetime.now(timezone.utc)
        document.predicted_doc_type = (
            (result.get("classification") or {}).get("candidate_document_type")
        )
        document.processed_doc_type = document.doc_type
        document.schema_version_id = schema_context.get("schema_version_id")
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
        "schema_validation": validate_document_schema(
            schema_context,
            active_schema,
            {},
            "failed",
        ),
        "warnings": [error_detail],
    }
    document.processed_at = datetime.now(timezone.utc)
    document.processed_doc_type = document.doc_type
    document.schema_version_id = schema_context.get("schema_version_id")
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


@router.get(
    "/{application_id}/documents/{document_id}/processing-result",
    response_model=DocumentProcessingOut,
)
def get_document_processing_result(
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
        raise HTTPException(status_code=404, detail="Document not found")
    if not document.processing_result:
        raise HTTPException(status_code=404, detail="No persisted processing result is available")
    return DocumentProcessingOut(
        document_id=document.id,
        processed_at=document.processed_at,
        **document.processing_result,
    )


@router.post("/{application_id}/documents/{document_id}/type-corrections")
def correct_document_type(
    application_id: int,
    document_id: int,
    payload: DocumentTypeCorrectionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in {UserRole.ADMIN.value, UserRole.REVIEWER.value}:
        raise HTTPException(status_code=403, detail="Only administrators and reviewers can correct document types")
    application = _get_authorized_application(application_id, db, current_user)
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.application_id == application_id,
    ).first()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    target_type = db.query(DocumentType).filter(
        DocumentType.id == payload.document_type_id,
    ).first()
    if target_type is None:
        raise HTTPException(status_code=404, detail="Document type not found in registry")
    if target_type.status != "active":
        raise HTTPException(status_code=409, detail="Only active document types can be selected")
    schema_context, _ = resolve_document_schema(
        db, target_type.id, document.original_filename, application.app_type
    )
    if schema_context["status"] != "ready":
        raise HTTPException(status_code=409, detail=schema_context["reason"])
    if document.doc_type == target_type.id:
        raise HTTPException(status_code=409, detail="Document already has this selected type")

    processing_result = document.processing_result or {}
    classification = processing_result.get("classification") or {}
    original_prediction = document.predicted_doc_type or classification.get("candidate_document_type")
    correction = DocumentTypeCorrection(
        document_id=document.id,
        previous_document_type=document.doc_type,
        corrected_document_type=target_type.id,
        original_prediction=original_prediction,
        reviewer_id=current_user.id,
        reason=payload.reason,
    )
    document.doc_type = target_type.id
    document.processing_status = "pending"
    document.processing_result = None
    document.processed_at = None
    document.processed_doc_type = None
    document.schema_version_id = None
    db.add(correction)
    db.add(AuditEvent(
        user_id=current_user.id,
        action="document.type_corrected",
        entity_type="document",
        entity_id=str(document.id),
        audit_metadata=json.dumps({
            "previous_document_type": correction.previous_document_type,
            "corrected_document_type": correction.corrected_document_type,
            "original_prediction": correction.original_prediction,
        }),
    ))
    try:
        db.commit()
        db.refresh(correction)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not save document type correction") from exc
    return {
        "id": correction.id,
        "document_id": correction.document_id,
        "previous_document_type": correction.previous_document_type,
        "corrected_document_type": correction.corrected_document_type,
        "original_prediction": correction.original_prediction,
        "reviewer_id": correction.reviewer_id,
        "reason": correction.reason,
        "created_at": correction.created_at,
        "processing_status": document.processing_status,
    }


@router.get("/{application_id}/documents/{document_id}/type-corrections")
def list_document_type_corrections(
    application_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in {UserRole.ADMIN.value, UserRole.REVIEWER.value}:
        raise HTTPException(status_code=403, detail="Only administrators and reviewers can view correction history")
    _get_authorized_application(application_id, db, current_user)
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.application_id == application_id,
    ).first()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    corrections = (
        db.query(DocumentTypeCorrection)
        .filter(DocumentTypeCorrection.document_id == document.id)
        .order_by(DocumentTypeCorrection.created_at, DocumentTypeCorrection.id)
        .all()
    )
    return [
        {
            "id": item.id,
            "document_id": item.document_id,
            "previous_document_type": item.previous_document_type,
            "corrected_document_type": item.corrected_document_type,
            "original_prediction": item.original_prediction,
            "reviewer_id": item.reviewer_id,
            "reason": item.reason,
            "created_at": item.created_at,
        }
        for item in corrections
    ]


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


@router.post(
    "/{application_id}/validate-all",
    response_model=ApplicationValidationOut,
    status_code=status.HTTP_200_OK,
)
def validate_application_all(
    application_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    application = _get_authorized_application(application_id, db, current_user)

    started_at = datetime.now(timezone.utc)
    stages: list[dict] = []
    results: list[dict] = []
    findings_to_create: list[dict] = []
    errors: list[str] = []
    consistency_comparisons: list[ComparisonResult] = []
    integrity_results: list[dict] = []
    registry_available = True

    try:
        rules_registry = load_registry()
        stages.append({
            "name": "regulatory_validation",
            "status": "completed",
            "reason": "Registry loaded; only approved rules with known applicability can be evaluated.",
            "result_count": 0,
        })
    except RegistryValidationError:
        logger.exception("Regulatory rule registry is unavailable")
        registry_available = False
        rules_registry = []
        errors.append("Regulatory rule registry is unavailable.")
        stages.append({
            "name": "regulatory_validation",
            "status": "unavailable",
            "reason": "Regulatory rule registry is unavailable.",
            "result_count": 0,
        })

    documents = (
        db.query(Document)
        .filter(Document.application_id == application.id)
        .order_by(Document.id)
        .all()
    )
    processing_attempts: list[dict] = []
    for document in documents:
        if document.processing_status != "pending":
            continue
        try:
            processed = process_document(
                application_id=application.id,
                document_id=document.id,
                db=db,
                current_user=current_user,
            )
            processing_attempts.append({
                "document_id": document.id,
                "status": processed.processing_status,
                "reason": "Document processing was run as part of application validation.",
            })
        except HTTPException as exc:
            if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
                errors.append(
                    f"Document processing could not be persisted for document {document.id}."
                )
                attempt_status = "failed"
            elif exc.status_code == status.HTTP_409_CONFLICT:
                attempt_status = "pending"
            else:
                attempt_status = "failed"
            processing_attempts.append({
                "document_id": document.id,
                "status": attempt_status,
                "http_status": exc.status_code,
                "reason": (
                    "Document processing is already in progress."
                    if attempt_status == "pending"
                    else "Document processing did not complete; see the document processing result."
                ),
            })
            db.rollback()

    documents = (
        db.query(Document)
        .filter(Document.application_id == application.id)
        .order_by(Document.id)
        .all()
    )
    if processing_attempts:
        attempt_statuses = {attempt["status"] for attempt in processing_attempts}
        orchestration_status = (
            "completed"
            if attempt_statuses == {"completed"}
            else "pending"
            if attempt_statuses == {"pending"}
            else "partial"
        )
        stages.append({
            "name": "document_processing_orchestration",
            "status": orchestration_status,
            "reason": (
                "All eligible documents were processed."
                if orchestration_status == "completed"
                else "One or more processing requests are still in progress."
                if orchestration_status == "pending"
                else "One or more document processing attempts did not complete."
            ),
            "result_count": len(processing_attempts),
            "documents": processing_attempts,
        })
    else:
        stages.append({
            "name": "document_processing_orchestration",
            "status": "skipped",
            "reason": "No pending documents required processing.",
            "result_count": 0,
            "documents": [],
        })

    supported_document_types = {rule["document_type"] for rule in rules_registry}
    documents_by_type: dict[str, list[Document]] = {}
    document_stages = []
    schema_validation_statuses = []
    schema_validation_results = []
    document_intelligence_results = []
    for doc in documents:
        documents_by_type.setdefault(doc.doc_type, []).append(doc)
        stored_schema_result = (
            doc.processing_result.get("schema_validation")
            if isinstance(doc.processing_result, dict)
            else None
        )
        if not isinstance(stored_schema_result, dict):
            stored_schema_result = {}
        schema_status = stored_schema_result.get("status", "not_evaluated")
        schema_validation_statuses.append(schema_status)
        schema_reason = stored_schema_result.get(
            "reason",
            "No persisted schema evaluation is available for this document.",
        )
        schema_validation_results.append({
            "type": "document_schema_validation",
            "document_id": doc.id,
            "document_type": doc.doc_type,
            "processing_status": doc.processing_status,
            "status": schema_status,
            "schema_version_id": stored_schema_result.get(
                "schema_version_id", doc.schema_version_id
            ),
            "schema_version": stored_schema_result.get("schema_version"),
            "registry_status": stored_schema_result.get("registry_status"),
            "reason": schema_reason,
            "fields": stored_schema_result.get("fields", []),
            "unlisted_extracted_fields": stored_schema_result.get(
                "unlisted_extracted_fields", []
            ),
            "human_review_required": stored_schema_result.get(
                "human_review_required", True
            ),
            "disclaimer": stored_schema_result.get(
                "disclaimer",
                "No schema result is available; no authenticity or compliance conclusion is made.",
            ),
        })
        processing_result = doc.processing_result if isinstance(doc.processing_result, dict) else {}
        classification = processing_result.get("classification")
        extracted_fields = processing_result.get("fields", {})
        document_intelligence_results.append({
            "type": "document_intelligence",
            "document_id": doc.id,
            "processing_status": doc.processing_status,
            "extraction_method": processing_result.get("extraction_method"),
            "field_extraction_version": processing_result.get("field_extraction_version"),
            "processing_duration_ms": processing_result.get("processing_duration_ms"),
            "ocr": processing_result.get("ocr"),
            "unreadable_pages": processing_result.get("unreadable_pages", []),
            "blank_pages": processing_result.get("blank_pages", []),
            "classification": classification,
            "fields": [
                {
                    "field_id": field_id,
                    "status": field.get("status"),
                    "raw_value": field.get("raw_value", field.get("value")),
                    "page": field.get("page"),
                    "evidence": field.get("evidence"),
                    "coordinates": field.get("coordinates"),
                    "confidence": field.get("confidence"),
                    "method": field.get("method"),
                    "extractor_version": field.get("extractor_version"),
                    "verification_status": "unverified",
                }
                for field_id, field in extracted_fields.items()
                if isinstance(field, dict)
            ],
            "warnings": processing_result.get("warnings", []),
        })
        if not registry_available:
            stage_status = "unavailable"
            reason = "Document rule support could not be determined because the registry is unavailable."
        elif doc.doc_type not in supported_document_types:
            stage_status = "unsupported"
            reason = "No registry rule supports this document type."
        elif doc.processing_status == "completed":
            stage_status = "completed"
            reason = "Document processing completed; extracted values remain unverified."
        elif doc.processing_status == "partial":
            stage_status = "partial"
            reason = "Some pages or extraction stages were incomplete; available values remain unverified."
        elif doc.processing_status in {"empty", "unreadable"}:
            stage_status = "failed"
            reason = "No reliable document text was extracted."
        elif doc.processing_status in {"pending", "processing"}:
            stage_status = "pending"
            reason = "Document processing has not completed."
        elif doc.processing_status == "failed":
            stage_status = "failed"
            reason = "Document processing failed; no validation was performed on this document."
        elif doc.processing_status == "ocr_unavailable":
            stage_status = "unavailable"
            reason = "OCR was unavailable; document validation could not be performed."
        else:
            stage_status = "unavailable"
            reason = "Document processing status is unknown; validation was not performed."
        document_stages.append(
            {
                "document_id": doc.id,
                "document_type": doc.doc_type,
                "processing_status": doc.processing_status,
                "status": stage_status,
                "reason": reason,
                "schema_validation_status": schema_status,
                "schema_version_id": stored_schema_result.get(
                    "schema_version_id", doc.schema_version_id
                ),
                "classification_status": (
                    classification.get("status")
                    if isinstance(classification, dict)
                    else "unavailable"
                ),
                "extraction_method": processing_result.get("extraction_method"),
            }
        )
    if not documents:
        document_stage_status = "skipped"
        document_stage_reason = "No documents are associated with this application."
    else:
        unsupported_or_blocked = any(
            item["status"] in {"unsupported", "pending", "failed", "unavailable", "partial"}
            for item in document_stages
        )
        document_stage_status = "partial" if unsupported_or_blocked else "completed"
        document_stage_reason = (
            "One or more documents could not be fully processed or supported."
            if unsupported_or_blocked
            else "All associated documents are processed and supported; extracted values remain unverified."
        )
    stages.append({
        "name": "document_processing",
        "status": document_stage_status,
        "reason": document_stage_reason,
        "result_count": len(document_stages),
        "documents": document_stages,
    })
    if not documents:
        classification_stage_status = "skipped"
        classification_stage_reason = "No documents are associated with this application."
    elif any(item["classification_status"] == "unavailable" for item in document_stages):
        classification_stage_status = "unavailable"
        classification_stage_reason = "Classification was unavailable for one or more documents."
    elif any(item["classification_status"] != "classified" for item in document_stages):
        classification_stage_status = "partial"
        classification_stage_reason = "One or more classifications abstained or require human review."
    else:
        classification_stage_status = "completed"
        classification_stage_reason = "Registry-backed type suggestions were generated; confirmation remains a human responsibility."
    stages.append({
        "name": "document_classification",
        "status": classification_stage_status,
        "reason": classification_stage_reason,
        "result_count": len(document_stages),
    })
    if not documents:
        schema_stage_status = "skipped"
        schema_stage_reason = "No documents are associated with this application."
    elif all(value == "not_evaluated" for value in schema_validation_statuses):
        schema_stage_status = "skipped"
        schema_stage_reason = "No persisted document-schema results are available; schema evaluation was not performed."
    elif all(value in {"valid", "invalid", "partial"} for value in schema_validation_statuses):
        schema_stage_status = "partial" if "partial" in schema_validation_statuses else "completed"
        schema_stage_reason = (
            "Some schema checks used partial extraction; all results require human review."
            if schema_stage_status == "partial"
            else "Active schemas were applied; results validate data shape only and require human review."
        )
    elif any(value in {"valid", "invalid"} for value in schema_validation_statuses):
        schema_stage_status = "partial"
        schema_stage_reason = "Some documents lack an applicable completed schema evaluation."
    elif all(value == "blocked" for value in schema_validation_statuses):
        schema_stage_status = "failed"
        schema_stage_reason = "Schema validation was blocked because document processing failed."
    elif all(value == "not_applicable" for value in schema_validation_statuses):
        schema_stage_status = "skipped"
        schema_stage_reason = "Registered schemas are not applicable to this application category."
    elif any(value in {"pending", "blocked"} for value in schema_validation_statuses):
        schema_stage_status = "partial"
        schema_stage_reason = "One or more schema evaluations are pending or blocked."
    elif any(value == "not_applicable" for value in schema_validation_statuses):
        schema_stage_status = "partial"
        schema_stage_reason = "One or more registered schemas are not applicable to this application category."
    elif any(value == "unavailable" for value in schema_validation_statuses):
        schema_stage_status = "unavailable"
        schema_stage_reason = "One or more active schema definitions are unavailable."
    else:
        schema_stage_status = "unsupported"
        schema_stage_reason = "No active applicable schema was available for one or more documents."
    stages.append({
        "name": "document_schema_validation",
        "status": schema_stage_status,
        "reason": schema_stage_reason,
        "result_count": len(document_stages),
    })

    integrity_result_count = 0
    integrity_failures = 0
    if not documents:
        stages.append({
            "name": "document_integrity",
            "status": "skipped",
            "reason": "No documents are associated with this application.",
            "result_count": 0,
        })
    else:
        for doc in documents:
            try:
                integrity = document_integrity_preview(
                    application.id,
                    doc.id,
                    db,
                    current_user,
                )
                duplicate_finding_ids = [
                    row[0]
                    for row in db.query(Finding.id).filter(
                        Finding.application_id == application.id,
                        Finding.document_id == doc.id,
                        Finding.finding_type == "Duplicate document",
                        Finding.status == "open",
                    ).all()
                ]
                integrity_results.append({
                    "type": "document_integrity",
                    "document_id": doc.id,
                    "filename": doc.original_filename,
                    "file_hash_check": integrity["file_hash_check"],
                    "duplicate_file_check": integrity["duplicate_file_check"],
                    "pdf_structure_check": integrity["pdf_structure_check"],
                    "metadata_check": integrity["metadata_check"],
                    "issuer_verification": integrity["issuer_verification"],
                    "authenticity_status": integrity["authenticity_status"],
                    "limitations": integrity["limitations"],
                    "finding_ids": duplicate_finding_ids,
                })
                integrity_result_count += 1
            except Exception:
                logger.exception(
                    "Document integrity preview failed for application_id=%s document_id=%s",
                    application.id,
                    doc.id,
                )
                integrity_failures += 1

        if integrity_failures:
            errors.append("Document integrity checks failed for one or more documents.")
            integrity_status = (
                "failed"
                if integrity_result_count == 0
                else "partial"
            )
            integrity_reason = (
                "Integrity checks failed for all associated documents."
                if integrity_result_count == 0
                else "Some integrity checks failed; available results are preserved."
            )
        else:
            integrity_status = "completed"
            integrity_reason = (
                "Existing duplicate, PDF-structure, and metadata checks ran. "
                "Issuer verification was not performed and authenticity was not assessed."
            )
        stages.append({
            "name": "document_integrity",
            "status": integrity_status,
            "reason": integrity_reason,
            "result_count": integrity_result_count,
        })

    # app_type is user-entered metadata, not verified institution or process
    # evidence. Applicability stays unknown until those facts are reviewed.
    application_scope = None

    try:
        for rule in rules_registry:
            document_type = rule["document_type"]
            rule_id = rule["rule_id"]
            if not rule.get("preview_approved", False):
                results.append({
                    "type": "regulatory_rule",
                    "rule_id": rule_id,
                    "document_type": document_type,
                    "status": "Not evaluated",
                    "reason_code": "rule_unapproved",
                    "explanation": "Candidate rule is not approved for evaluation; no rule assessment was performed.",
                    "evidence": None,
                    "evidence_refs": [],
                })
                continue

            eligibility = evaluate_preview_eligibility(rule, application_scope)
            if eligibility == "not_applicable":
                results.append({
                    "type": "regulatory_rule",
                    "rule_id": rule_id,
                    "document_type": document_type,
                    "status": "Not-Applicable",
                    "reason_code": "not_applicable",
                    "explanation": "The application scope does not match this rule.",
                    "evidence": None,
                    "evidence_refs": [],
                })
                continue
            if eligibility == "unknown":
                results.append({
                    "type": "regulatory_rule",
                    "rule_id": rule_id,
                    "document_type": document_type,
                    "status": "Not evaluated",
                    "reason_code": "applicability_unknown",
                    "explanation": "Application scope or required evidence is unavailable.",
                    "evidence": None,
                    "evidence_refs": [],
                })
                continue

            matching_documents = documents_by_type.get(document_type, [])
            completed_documents = [
                doc for doc in matching_documents if doc.processing_status == "completed"
            ]
            if not completed_documents:
                if any(doc.processing_status in {"pending", "processing"} for doc in matching_documents):
                    reason_code = "document_pending"
                    explanation = f"Document type '{document_type}' is present but processing is pending."
                elif any(doc.processing_status == "failed" for doc in matching_documents):
                    reason_code = "document_failed"
                    explanation = f"Document type '{document_type}' is present but processing failed."
                elif any(doc.processing_status == "ocr_unavailable" for doc in matching_documents):
                    reason_code = "document_unavailable"
                    explanation = f"Document type '{document_type}' is present but OCR is unavailable."
                else:
                    reason_code = "document_missing"
                    explanation = f"No processed document of type '{document_type}' is available."
                results.append({
                    "type": "regulatory_rule",
                    "rule_id": rule_id,
                    "document_type": document_type,
                    "status": "Not evaluated",
                    "reason_code": reason_code,
                    "explanation": explanation,
                    "evidence": None,
                    "evidence_refs": [],
                })
                continue

            doc = completed_documents[-1]
            doc_evidence = {
                "document_id": doc.id,
                "fields": doc.processing_result.get("fields", {}) if doc.processing_result else {},
            }
            eval_result = evaluate_rule_result(rule, doc_evidence)
            evaluation_status = eval_result["status"]
            if evaluation_status in {"Pass", "Fail", "Needs review"}:
                final_status = "Partial"
                explanation = (
                    "A non-authoritative field check returned a signal that requires "
                    "human review; it does not establish regulatory compliance, "
                    "non-compliance, or document authenticity."
                )
                reason_code = "review_required"
            elif evaluation_status == "Not evaluated":
                final_status = "Not evaluated"
                explanation = eval_result["explanation"]
                reason_code = (
                    "unsupported_rule"
                    if "No evaluator is implemented" in explanation
                    else "insufficient_evidence"
                )
            elif evaluation_status == "Not-Applicable":
                final_status = "Not-Applicable"
                explanation = eval_result["explanation"]
                reason_code = "not_applicable"
            else:
                final_status = "Not evaluated"
                explanation = "The evaluator returned an unsupported result; no validation conclusion was made."
                reason_code = "unsupported_result"

            fields = doc_evidence["fields"]
            relevant_fields = {
                "FS-001": {"certificate_number"},
                "FS-002": {"expiry_date"},
            }.get(rule_id, set())
            if eval_result.get("evidence"):
                relevant_fields.update(
                    field_name
                    for field_name, field_value in fields.items()
                    if isinstance(field_value, dict)
                    and field_value.get("evidence") == eval_result["evidence"]
                )
            result = {
                "type": "regulatory_rule",
                "rule_id": rule_id,
                "document_type": document_type,
                "status": final_status,
                "reason_code": reason_code,
                "explanation": explanation,
                "evidence": eval_result.get("evidence"),
                "evidence_refs": _validation_evidence_references(doc, relevant_fields),
            }
            results.append(result)
            if evaluation_status in {"Pass", "Fail", "Needs review"}:
                findings_to_create.append({
                    "finding_type": "Verification Required",
                    "severity": "Medium",
                    "description": explanation,
                    "document_id": doc.id,
                })
        stages[0]["result_count"] = len(results)
    except Exception:
        logger.exception("Regulatory validation stage failed")
        errors.append("Regulatory validation stage failed.")
        stages[0]["status"] = "failed"
        stages[0]["reason"] = "Rule evaluation failed; see server logs for diagnostic details."
        recorded_rule_ids = {
            result["rule_id"]
            for result in results
            if result.get("type") == "regulatory_rule"
        }
        for rule in rules_registry:
            if rule["rule_id"] in recorded_rule_ids:
                continue
            results.append({
                "type": "regulatory_rule",
                "rule_id": rule["rule_id"],
                "document_type": rule["document_type"],
                "status": "Not evaluated",
                "reason_code": "evaluation_stage_failed",
                "explanation": "Rule evaluation stopped after a stage error; this rule was not evaluated.",
                "evidence": None,
                "evidence_refs": [],
            })

    stages[0]["result_count"] = sum(
        result.get("type") == "regulatory_rule" for result in results
    )
    results.extend(integrity_results)
    registry_by_id = {rule["rule_id"]: rule for rule in rules_registry}
    for result in results:
        if result.get("type") != "regulatory_rule":
            continue
        rule = registry_by_id.get(result["rule_id"], {})
        rule_digest = hashlib.sha256(
            json.dumps(
                rule,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest() if rule else None
        result["rule_reference"] = {
            "rule_id": result["rule_id"],
            "definition_sha256": rule_digest,
            "preview_status": (
                "approved_for_preview"
                if rule.get("preview_approved", False)
                else "not_approved_for_preview"
            ),
        }
        source_reference = {
            key: rule[key]
            for key in ("handbook_version", "source_path", "section", "printed_page", "pdf_page")
            if rule.get(key) is not None
        }
        result["candidate_requirement"] = rule.get("candidate_requirement")
        result["preview_approved"] = rule.get("preview_approved", False)
        result["source_reference"] = source_reference or None

    checklist_result: Optional[dict] = None
    try:
        checklist_items, checklist_findings = _evaluate_application_checklist(application, db)
        checklist_result = {
            "source": "synthetic_demo",
            "items": [
                {
                    **item,
                    "evidence_refs": [
                        reference
                        for document_id in item["document_ids"]
                        for document in documents
                        if document.id == document_id
                        for reference in _validation_evidence_references(document)
                    ],
                }
                for item in checklist_items
            ],
        }
        results.append({
            "type": "application_checklist",
            "source": "synthetic_demo",
            **checklist_result,
        })
        findings_to_create.extend(checklist_findings)
        stages.append({
            "name": "application_checklist",
            "status": "completed",
            "reason": "Synthetic checklist executed; it is not an official regulatory determination.",
            "result_count": len(checklist_items),
        })
    except HTTPException as exc:
        checklist_status = "unsupported" if exc.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY else "unavailable"
        errors.append(f"Application checklist stage {checklist_status}.")
        stages.append({
            "name": "application_checklist",
            "status": checklist_status,
            "reason": "Synthetic checklist could not be evaluated for this application.",
            "result_count": 0,
        })
    except Exception:
        logger.exception("Application checklist stage failed")
        errors.append("Application checklist stage failed.")
        stages.append({
            "name": "application_checklist",
            "status": "failed",
            "reason": "Checklist execution failed; see server logs for diagnostic details.",
            "result_count": 0,
        })

    completed_documents = [doc for doc in documents if doc.processing_status == "completed"]
    if len(completed_documents) < 2:
        stages.append({
            "name": "cross_document_consistency",
            "status": "skipped",
            "reason": "At least two processed documents are required for comparison.",
            "result_count": 0,
        })
    else:
        try:
            consistency_service = ConsistencyService()
            for index, doc1 in enumerate(completed_documents):
                fields1 = doc1.processing_result.get("fields", {}) if doc1.processing_result else {}
                for doc2 in completed_documents[index + 1:]:
                    fields2 = doc2.processing_result.get("fields", {}) if doc2.processing_result else {}
                    for field_name in consistency_service.comparable_fields:
                        comparison = consistency_service.compare_fields(
                            field_name,
                            fields1.get(field_name),
                            doc1.id,
                            fields2.get(field_name),
                            doc2.id,
                        )
                        if comparison.category != "NOT_APPLICABLE":
                            consistency_comparisons.append(comparison)
                            results.append({
                                "type": "consistency",
                                "field": comparison.field,
                                "category": comparison.category,
                                "document_ids": [comparison.doc1_id, comparison.doc2_id],
                                "values": [comparison.val1, comparison.val2],
                                "explanation": comparison.explanation,
                                "human_review_recommended": comparison.human_review_recommended,
                                "evidence_refs": [
                                    *_validation_evidence_references(doc1, {comparison.field}),
                                    *_validation_evidence_references(doc2, {comparison.field}),
                                ],
                            })
            stages.append({
                "name": "cross_document_consistency",
                "status": "completed",
                "reason": "Existing cross-document comparisons were executed on extracted values only.",
                "result_count": len(consistency_comparisons),
            })
        except Exception:
            logger.exception("Cross-document consistency stage failed")
            errors.append("Cross-document consistency stage failed.")
            consistency_comparisons = []
            stages.append({
                "name": "cross_document_consistency",
                "status": "failed",
                "reason": "Consistency execution failed; see server logs for diagnostic details.",
                "result_count": 0,
            })

    image_evidence_rows = (
        db.query(ImageEvidence)
        .filter(
            ImageEvidence.application_id == application.id,
            ImageEvidence.validation_run_id.is_(None),
        )
        .order_by(ImageEvidence.id)
        .all()
    )
    if image_evidence_rows:
        image_results = [
            {
                "type": "infrastructure_image_quality",
                "image_evidence_id": item.id,
                "filename": item.original_filename,
                "sha256": item.sha256,
                "processing_status": item.processing_status,
                "analysis": item.analysis_result,
                "evidence_status": "stored",
                "human_review_required": True,
                "limitation": (
                    "This deterministic quality assessment does not identify infrastructure "
                    "objects, determine regulatory compliance, or authenticate the image."
                ),
            }
            for item in image_evidence_rows
        ]
        results.extend(image_results)
        quality_limited = any(
            item.processing_status == "quality_limited" for item in image_evidence_rows
        )
        stages.append({
            "name": "infrastructure_image_quality",
            "status": "partial" if quality_limited else "completed",
            "reason": (
                "Image-quality signals are available; all images require human review and no object detection or compliance decision was performed."
            ),
            "result_count": len(image_evidence_rows),
        })
    else:
        stages.append({
            "name": "infrastructure_image_quality",
            "status": "skipped",
            "reason": "No unlinked image evidence was available for this validation run.",
            "result_count": 0,
        })
    results.extend(document_intelligence_results)
    results.extend(schema_validation_results)
    evaluated_rules_count = sum(
        result["reason_code"] in {"evaluated", "review_required"}
        for result in results
        if result.get("type") == "regulatory_rule"
    )
    not_applicable_rules_count = sum(
        result["status"] == "Not-Applicable"
        for result in results
        if result.get("type") == "regulatory_rule"
    )
    not_evaluated_rules_count = sum(
        result["status"] == "Not evaluated"
        for result in results
        if result.get("type") == "regulatory_rule"
    )
    validation_status = (
        "inconclusive"
        if evaluated_rules_count == 0
        else "partial"
        if not_evaluated_rules_count > 0
        or any(
            result["status"] == "Partial"
            for result in results
            if result.get("type") == "regulatory_rule"
        )
        or any(
            stage["status"] in {"partial", "failed", "unavailable", "unsupported"}
            for stage in stages
        )
        else "completed"
    )

    execution_status = (
        "partial"
        if errors or any(stage["status"] in {"partial", "failed", "unavailable", "unsupported"} for stage in stages)
        else "completed"
    )
    run = ValidationRun(
        application_id=application.id,
        user_id=current_user.id,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
        execution_status=execution_status,
        outcome=validation_status,
        stage_outcomes=stages,
        results=results,
        error_summary=" ".join(errors) or None,
        evaluated_rules_count=evaluated_rules_count,
        not_evaluated_rules_count=not_evaluated_rules_count,
        not_applicable_rules_count=not_applicable_rules_count,
    )
    db.add(run)

    findings_created = 0
    persisted_findings: list[Finding] = []
    try:
        db.flush()
        for image_evidence in image_evidence_rows:
            image_evidence.validation_run_id = run.id
        for result in results:
            if result.get("type") != "regulatory_rule":
                continue
            rule_id = result["rule_id"]
            db_rule = db.query(ComplianceRule).filter(ComplianceRule.rule_code == rule_id).first()
            if not db_rule:
                db_rule = ComplianceRule(
                    rule_code=rule_id,
                    title=f"Rule {rule_id}",
                    description="Registry candidate; no authoritative rule text is stored in this assessment.",
                    category="Unclassified",
                    is_active=True,
                )
                db.add(db_rule)
                db.flush()

            existing_snapshot = db.query(ComplianceAssessment).filter(
                ComplianceAssessment.application_id == application.id,
                ComplianceAssessment.rule_id == db_rule.id,
                ComplianceAssessment.status == result["status"],
                ComplianceAssessment.explanation == result["explanation"],
            ).first()
            if existing_snapshot is None:
                existing_snapshot = ComplianceAssessment(
                    application_id=application.id,
                    rule_id=db_rule.id,
                    status=result["status"],
                    explanation=result["explanation"],
                    reviewer_id=None,
                )
                db.add(existing_snapshot)
                db.flush()
            run.assessments.append(existing_snapshot)

        if len(completed_documents) >= 2 and any(
            stage["name"] == "cross_document_consistency" and stage["status"] == "completed"
            for stage in stages
        ):
            consistency_run = ConsistencyRun(
                application_id=application.id,
                user_id=current_user.id,
                validation_run_id=run.id,
                status="completed",
                comparisons_count=len(consistency_comparisons),
            )
            db.add(consistency_run)
            db.flush()
            for comparison in consistency_comparisons:
                db.add(DocumentConsistencyResult(
                    run=consistency_run,
                    application_id=application.id,
                    field=comparison.field,
                    category=comparison.category,
                    val1=comparison.val1,
                    val2=comparison.val2,
                    norm1=comparison.norm1,
                    norm2=comparison.norm2,
                    doc1_id=comparison.doc1_id,
                    doc2_id=comparison.doc2_id,
                    explanation=comparison.explanation,
                    human_review_recommended=comparison.human_review_recommended,
                ))

        for candidate in findings_to_create:
            finding = db.query(Finding).filter(
                Finding.application_id == application.id,
                Finding.document_id == candidate.get("document_id"),
                Finding.finding_type == candidate["finding_type"],
                Finding.description == candidate["description"],
                Finding.status == "open",
            ).first()
            if finding is None:
                finding = Finding(
                    application_id=application.id,
                    document_id=candidate.get("document_id"),
                    finding_type=candidate["finding_type"],
                    severity=candidate["severity"],
                    description=candidate["description"],
                    status="open",
                )
                db.add(finding)
                db.flush()
                findings_created += 1
            persisted_findings.append(finding)

        existing_finding_ids = {
            finding.id for finding in persisted_findings
        }
        for result in results:
            if result.get("type") != "document_integrity":
                continue
            existing_finding_ids.update(result.get("finding_ids", []))

        findings_by_id = {
            finding.id: finding
            for finding in persisted_findings
        }
        if existing_finding_ids:
            findings_by_id.update({
                finding.id: finding
                for finding in db.query(Finding).filter(
                    Finding.id.in_(existing_finding_ids),
                    Finding.application_id == application.id,
                ).all()
            })
        for finding in findings_by_id.values():
            document = next(
                (doc for doc in documents if doc.id == finding.document_id),
                None,
            )
            results.append({
                "type": "finding",
                "finding_id": finding.id,
                "finding_type": finding.finding_type,
                "severity": finding.severity,
                "status": finding.status,
                "document_id": finding.document_id,
                "description": finding.description,
                "evidence_refs": (
                    _validation_evidence_references(document)
                    if document is not None
                    else []
                ),
            })

        run.results = [*results]
        flag_modified(run, "results")
        db.flush()

        db.add(AuditEvent(
            user_id=current_user.id,
            action="application.validate_all",
            entity_type="application",
            entity_id=str(application.id),
            audit_metadata=json.dumps(
                {
                    "validation_run_id": run.id,
                    "execution_status": execution_status,
                    "validation_status": validation_status,
                    "rules_evaluated": evaluated_rules_count,
                    "rules_not_evaluated": not_evaluated_rules_count,
                    "rules_not_applicable": not_applicable_rules_count,
                    "findings_created": findings_created,
                    "document_stages": document_stages,
                    "stage_outcomes": stages,
                }
            ),
        ))

        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Failed to persist application validation results")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Application validation results could not be saved.",
        ) from exc

    return {
        "application_id": application.id,
        "run_id": run.id,
        "execution_status": execution_status,
        "status": validation_status,
        "evaluated_rules_count": evaluated_rules_count,
        "not_evaluated_rules_count": not_evaluated_rules_count,
        "not_applicable_rules_count": not_applicable_rules_count,
        "document_stages": document_stages,
        "stages": stages,
        "results": results,
        "findings_count": findings_created,
        "error_summary": run.error_summary,
    }


def _validation_evidence_references(
    document: Document,
    field_names: Optional[set[str]] = None,
) -> list[dict]:
    processing_result = document.processing_result or {}
    fields = processing_result.get("fields", {})
    if not isinstance(fields, dict):
        return []
    ocr_result = processing_result.get("ocr")
    ocr_provenance = None
    if isinstance(ocr_result, dict):
        ocr_provenance = {
            key: ocr_result[key]
            for key in ("engine", "engine_version", "languages", "status")
            if ocr_result.get(key) is not None
        }
    processing_provenance = {
        "document_sha256": document.sha256,
        "document_type": document.processed_doc_type or document.doc_type,
        "processing_status": document.processing_status,
        "processed_at": document.processed_at.isoformat() if document.processed_at else None,
        "schema_version_id": document.schema_version_id,
        "extraction_method": processing_result.get("extraction_method"),
        "field_extraction_version": processing_result.get("field_extraction_version"),
        "ocr": ocr_provenance,
    }
    references = []
    for field_name, field_value in fields.items():
        if field_names is not None and field_name not in field_names:
            continue
        if not isinstance(field_value, dict):
            continue
        excerpt = field_value.get("evidence")
        page = field_value.get("page")
        reference = {
            "document_id": document.id,
            "filename": document.original_filename,
            "field": field_name,
            "verification_status": "unverified",
            "evidence_status": "available" if excerpt is not None or page is not None else "unavailable",
            "processing_provenance": processing_provenance,
        }
        if page is not None:
            reference["page"] = page
        if excerpt is not None:
            reference["excerpt"] = excerpt
        references.append(reference)
    return references


@router.get("/{application_id}/validation-runs", response_model=ValidationRunHistoryOut)
def list_application_validation_runs(
    application_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_authorized_application(application_id, db, current_user)
    runs = (
        db.query(ValidationRun)
        .filter(ValidationRun.application_id == application_id)
        .order_by(ValidationRun.started_at.desc(), ValidationRun.id.desc())
        .all()
    )
    return {"items": runs}


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


def _evaluate_application_checklist(application: Application, db: Session):
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

    documents = db.query(Document).filter(
        Document.application_id == application.id
    ).order_by(Document.id).all()
    by_type: dict[str, list[Document]] = {}
    for document in documents:
        by_type.setdefault(document.doc_type, []).append(document)
    items = []
    finding_candidates = []
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
            finding_type = (
                "Checklist expiry review"
                if check_status in {"expired_document", "expiry_unverified"}
                else "Checklist completeness"
            )
            finding_candidates.append({
                "application_id": application.id,
                "document_id": linked_document.id if linked_document else None,
                "finding_type": finding_type,
                "severity": "Medium" if check_status in {"processing_pending", "processing_failed", "expired_document", "expiry_unverified"} else "High",
                "description": description,
                "status": "open",
            })
        items.append({
            "document_type": doc_type,
            "status": check_status,
            "document_ids": [document.id for document in matches],
            "missing_fields": missing_fields,
            "explanation": explanation,
        })
    return items, finding_candidates


@router.get("/{application_id}/checklist", response_model=ApplicationChecklistOut)
def get_application_checklist(
    application_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    application = _get_authorized_application(application_id, db, current_user)
    items, _finding_candidates = _evaluate_application_checklist(application, db)
    return {
        "application_id": application.id,
        "category": application.app_type,
        "source": "synthetic_demo",
        "items": items,
    }


@router.post("/{application_id}/validate-checklist", response_model=ApplicationChecklistOut)
def validate_application_checklist(
    application_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    application = _get_authorized_application(application_id, db, current_user)
    items, finding_candidates = _evaluate_application_checklist(application, db)
    findings_created = 0
    for candidate in finding_candidates:
        exists = db.query(Finding.id).filter(
            Finding.application_id == candidate["application_id"],
            Finding.document_id == candidate["document_id"],
            Finding.finding_type == candidate["finding_type"],
            Finding.description == candidate["description"],
            Finding.status == "open",
        ).first()
        if not exists:
            db.add(Finding(**candidate))
            findings_created += 1
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
    update_data = application_in.model_dump(exclude_unset=True)
    if "status" in update_data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Application status changes are not supported by this endpoint",
        )
    changed_data = {
        field: value
        for field, value in update_data.items()
        if getattr(app_obj, field) != value
    }
    for field, value in changed_data.items():
        setattr(app_obj, field, value)

    if changed_data:
        db.add(
            AuditEvent(
                user_id=current_user.id,
                action="application.updated",
                entity_type="application",
                entity_id=str(app_obj.id),
                audit_metadata=json.dumps({"changed_fields": sorted(changed_data)}),
            )
        )
    db.commit()
    db.refresh(app_obj)
    return app_obj
