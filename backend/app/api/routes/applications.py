import logging
from pathlib import Path
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import update
from sqlalchemy.orm import Session
from typing import List
from sqlalchemy.exc import SQLAlchemyError
from app.core.config import settings
from app.db.session import get_db
from app.models.models import Application, ComplianceAssessment, Document, User
from app.schemas.applications import (
    ApplicationCreate,
    ApplicationUpdate,
    ApplicationOut,
    DocumentOut,
    DocumentProcessingOut,
)
from app.api.deps import get_current_user, RoleChecker
from app.models.enums import UserRole
from app.services.documents import (
    DocumentStorageError,
    DocumentTooLargeError,
    InvalidPDFError,
    store_pdf,
)
from app.services.document_processing import (
    DocumentLimitError,
    DocumentProcessingError,
    process_pdf,
)

router = APIRouter()
logger = logging.getLogger(__name__)


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
        logger.exception("Could not claim document for processing")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not start document processing")

    storage_directory = Path(settings.DOCUMENT_STORAGE_DIR).resolve()
    storage_path = (storage_directory / document.storage_key).resolve()
    if storage_path.parent != storage_directory or not storage_path.is_file():
        document.processing_status = "failed"
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
        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            logger.exception("Could not persist document processing results")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not save document processing results",
            )
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
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Could not persist failed document processing status")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save document processing status",
        )
    raise HTTPException(status_code=error_status, detail=error_detail)


@router.post("/", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
def create_application(
    application_in: ApplicationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Authorization: Only INSTITUTION_USER and ADMIN can create apps
    if current_user.role == UserRole.INSTITUTION_USER and current_user.institution_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must be assigned to an institution to create an application"
        )

    # Check if reference already exists
    existing = db.query(Application).filter(Application.reference == application_in.reference).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Application with this reference already exists"
        )

    # Ownership derivation: Derive institution_id from authenticated user
    institution_id = None
    if current_user.role == UserRole.INSTITUTION_USER:
        institution_id = current_user.institution_id
    elif current_user.role == UserRole.ADMIN:
        # Admin can specify an institution if provided in ApplicationCreate
        # (though ApplicationCreate currently doesn't have it, if it did we'd check it here)
        # For now, we treat admin-created apps as system-owned (NULL) or linked if we add the field
        pass

    new_app = Application(
        reference=application_in.reference,
        entity_name=application_in.entity_name,
        app_type=application_in.app_type,
        status=application_in.status or "submitted",
        institution_id=institution_id
    )

    db.add(new_app)
    db.commit()
    db.refresh(new_app)
    return new_app

@router.get("/", response_model=List[ApplicationOut])
def list_applications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = db.query(Application)

    if current_user.role == UserRole.INSTITUTION_USER:
        if current_user.institution_id is None:
            return [] # Or raise 403
        # Strict isolation: Only apps belonging to the user's institution
        query = query.filter(Application.institution_id == current_user.institution_id)
    elif current_user.role == UserRole.REVIEWER:
        # Reviewers access based on assignments (ComplianceAssessment.reviewer_id)
        # To keep it simple and a standard query, we filter by applications that have
        # an assessment assigned to this reviewer.
        from app.models.models import ComplianceAssessment
        subquery = db.query(ComplianceAssessment.application_id).filter(
            ComplianceAssessment.reviewer_id == current_user.id
        )
        query = query.filter(Application.id.in_(subquery))
    elif current_user.role == UserRole.ADMIN:
        # Admin sees everything
        pass

    return query.order_by(Application.created_at.desc()).all()

@router.get("/{application_id}", response_model=ApplicationOut)
def get_application(
    application_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
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

    return app_obj

@router.patch("/{application_id}", response_model=ApplicationOut)
def update_application(
    application_id: int,
    application_in: ApplicationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    app_obj = db.query(Application).filter(Application.id == application_id).first()
    if not app_obj:
        raise HTTPException(status_code=404, detail="Application not found")

    # Authorization
    if current_user.role == UserRole.INSTITUTION_USER:
        if app_obj.institution_id != current_user.institution_id:
            raise HTTPException(status_code=404, detail="Application not found")
    elif current_user.role == UserRole.REVIEWER:
        from app.models.models import ComplianceAssessment
        assigned = db.query(ComplianceAssessment).filter(
            ComplianceAssessment.application_id == application_id,
            ComplianceAssessment.reviewer_id == current_user.id
        ).first()
        if not assigned:
            raise HTTPException(status_code=403, detail="Not authorized to update this application")

    update_data = application_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(app_obj, field, value)

    db.commit()
    db.refresh(app_obj)
    return app_obj
