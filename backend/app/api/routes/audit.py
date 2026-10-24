import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.models import Application, AuditEvent, ComplianceAssessment, Document, User
from app.schemas.applications import AuditEventOut, AuditEventPageOut


router = APIRouter()
logger = logging.getLogger(__name__)
_SAFE_METADATA_KEYS = {
    "reference",
    "changed_fields",
    "application_id",
    "doc_type",
    "file_size",
    "processing_status",
    "extraction_method",
    "pages_processed",
    "reason",
    "name",
    "assessment_id",
    "review_id",
    "reviewer_id",
    "previous_reviewer_id",
    "outcome",
    "findings_created",
    "rules_evaluated",
}


def _safe_metadata(raw: str | None) -> dict[str, object]:
    if raw is None:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Ignoring malformed audit metadata")
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        key: value
        for key, value in data.items()
        if key in _SAFE_METADATA_KEYS
        and (
            value is None
            or isinstance(value, (str, int, float, bool))
            or (
                isinstance(value, list)
                and all(isinstance(item, str) for item in value)
            )
        )
    }


@router.get("/", response_model=AuditEventPageOut)
def list_audit_events(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    application_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(AuditEvent)
    if current_user.role == UserRole.ADMIN.value:
        pass
    elif current_user.role == UserRole.INSTITUTION_USER.value:
        if current_user.institution_id is None:
            return {"items": [], "limit": limit, "offset": offset, "total": 0}
        accessible_applications = db.query(Application.id).filter(
            Application.institution_id == current_user.institution_id
        )
    elif current_user.role == UserRole.REVIEWER.value:
        accessible_applications = db.query(ComplianceAssessment.application_id).filter(
            ComplianceAssessment.reviewer_id == current_user.id
        ).distinct()
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access audit history",
        )

    if current_user.role != UserRole.ADMIN.value:
        accessible_application_ids = db.query(cast(Application.id, String)).filter(
            Application.id.in_(accessible_applications)
        )
        accessible_document_ids = db.query(cast(Document.id, String)).filter(
            Document.application_id.in_(accessible_applications)
        )
        accessible_assessment_ids = db.query(cast(ComplianceAssessment.id, String)).filter(
            ComplianceAssessment.application_id.in_(accessible_applications)
        )
        query = query.filter(
            or_(
                (AuditEvent.entity_type == "application")
                & AuditEvent.entity_id.in_(accessible_application_ids),
                (AuditEvent.entity_type == "document")
                & AuditEvent.entity_id.in_(accessible_document_ids),
                (AuditEvent.entity_type == "compliance_assessment")
                & AuditEvent.entity_id.in_(accessible_assessment_ids),
            )
        )

    if application_id is not None:
        if current_user.role != UserRole.ADMIN.value:
            accessible_application = db.query(Application.id).filter(
                Application.id == application_id,
                Application.id.in_(accessible_applications),
            ).first()
            if accessible_application is None:
                raise HTTPException(status_code=404, detail="Application not found")
        application_ids = db.query(Application.id).filter(Application.id == application_id)
        application_document_ids = db.query(cast(Document.id, String)).filter(
            Document.application_id.in_(application_ids)
        )
        application_assessment_ids = db.query(cast(ComplianceAssessment.id, String)).filter(
            ComplianceAssessment.application_id.in_(application_ids)
        )
        query = query.filter(
            or_(
                (AuditEvent.entity_type == "application") & (AuditEvent.entity_id == str(application_id)),
                (AuditEvent.entity_type == "document") & AuditEvent.entity_id.in_(application_document_ids),
                (AuditEvent.entity_type == "compliance_assessment") & AuditEvent.entity_id.in_(application_assessment_ids),
            )
        )

    total = query.count()
    rows = (
        query.order_by(AuditEvent.timestamp.desc(), AuditEvent.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    items = []
    for event in rows:
        actor = db.query(User.full_name).filter(User.id == event.user_id).scalar()
        items.append(
            {
                "id": event.id,
                "user_id": event.user_id,
                "actor_name": actor,
                "action": event.action,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "timestamp": event.timestamp,
                "metadata": _safe_metadata(event.audit_metadata),
            }
        )
    return {"items": items, "limit": limit, "offset": offset, "total": total}
