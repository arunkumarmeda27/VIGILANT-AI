import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.models import (
    Application,
    AuditEvent,
    ComplianceAssessment,
    ComplianceAssessmentReview,
    ComplianceAssessmentStatusHistory,
    ComplianceRule,
    Document,
    User,
)
from app.schemas.applications import (
    ComplianceAssessmentOut,
    ComplianceAssessmentPageOut,
)
from app.schemas.applications import (
    ComplianceAssessmentAssignmentCreate,
    ComplianceAssessmentDetailOut,
    ComplianceAssessmentReviewCreate,
    ComplianceAssessmentReviewOut,
    ComplianceAssessmentStatusUpdate,
)


router = APIRouter()


def _assessment_for_user(assessment_id: int, db: Session, user: User):
    row = (
        db.query(ComplianceAssessment, Application, ComplianceRule)
        .join(Application, Application.id == ComplianceAssessment.application_id)
        .join(ComplianceRule, ComplianceRule.id == ComplianceAssessment.rule_id)
        .filter(ComplianceAssessment.id == assessment_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    assessment, application, rule = row
    if user.role == UserRole.ADMIN.value:
        return assessment, application, rule
    if user.role == UserRole.INSTITUTION_USER.value:
        if application.institution_id is not None and application.institution_id == user.institution_id:
            return assessment, application, rule
    if user.role == UserRole.REVIEWER.value and assessment.reviewer_id == user.id:
        return assessment, application, rule
    raise HTTPException(status_code=404, detail="Assessment not found")


def _assessment_review_out(review: ComplianceAssessmentReview) -> dict[str, object]:
    return {
        "id": review.id,
        "assessment_id": review.assessment_id,
        "reviewer_id": review.reviewer_id,
        "reviewer_name": review.reviewer.full_name,
        "outcome": review.outcome,
        "note": review.note,
        "created_at": review.created_at,
    }


def _review_status_history(
    assessment_id: int,
    db: Session,
    include_reason: bool,
) -> list[dict[str, object]]:
    entries = db.query(ComplianceAssessmentStatusHistory).filter(
        ComplianceAssessmentStatusHistory.assessment_id == assessment_id
    ).order_by(
        ComplianceAssessmentStatusHistory.created_at,
        ComplianceAssessmentStatusHistory.id,
    ).all()
    return [{
        "reviewer_id": entry.reviewer_id,
        "from_status": entry.from_status,
        "to_status": entry.to_status,
        "reason": entry.reason if include_reason else None,
        "created_at": entry.created_at,
    } for entry in entries]


@router.get("/reviewers", response_model=list[dict[str, object]])
def list_reviewers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(status_code=403, detail="Only administrators can list reviewers")
    return [
        {"id": reviewer.id, "full_name": reviewer.full_name, "email": reviewer.email}
        for reviewer in db.query(User).filter(
            User.role == UserRole.REVIEWER.value, User.is_active.is_(True)
        ).order_by(User.full_name, User.id).all()
    ]


@router.get("/{assessment_id}", response_model=ComplianceAssessmentDetailOut)
def get_compliance_assessment(
    assessment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assessment, application, rule = _assessment_for_user(assessment_id, db, current_user)
    documents = db.query(Document).filter(
        Document.application_id == application.id
    ).order_by(Document.id).all()
    evidence = []
    for document in documents:
        processing = document.processing_result or {}
        evidence.append({
            "document_id": document.id,
            "filename": document.original_filename,
            "document_type": document.doc_type,
            "processing_status": document.processing_status,
            "extraction_method": processing.get("extraction_method", "unknown"),
            "fields": processing.get("fields", {}),
        })
    reviews = db.query(ComplianceAssessmentReview).filter(
        ComplianceAssessmentReview.assessment_id == assessment.id
    ).order_by(ComplianceAssessmentReview.created_at, ComplianceAssessmentReview.id).all()
    return {
        "id": assessment.id,
        "application_id": application.id,
        "application_reference": application.reference,
        "entity_name": application.entity_name,
        "rule_code": rule.rule_code,
        "rule_title": rule.title,
        "category": rule.category,
        "status": assessment.status,
        "review_status": assessment.review_status,
        "explanation": assessment.explanation,
        "assessed_at": assessment.assessed_at,
        "reviewer_name": assessment.reviewer.full_name if assessment.reviewer else None,
        "application_status": application.status,
        "rule_description": rule.description,
        "assigned_reviewer_id": assessment.reviewer_id,
        "document_evidence": evidence,
        "reviews": [_assessment_review_out(review) for review in reviews],
        "review_status_history": _review_status_history(
            assessment.id,
            db,
            include_reason=current_user.role != UserRole.INSTITUTION_USER.value,
        ),
    }


@router.post("/{assessment_id}/reviews", response_model=ComplianceAssessmentReviewOut, status_code=201)
def record_assessment_review(
    assessment_id: int,
    review_in: ComplianceAssessmentReviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.REVIEWER.value:
        raise HTTPException(status_code=403, detail="Only assigned reviewers can decide assessments")
    assessment, _application, _rule = _assessment_for_user(assessment_id, db, current_user)
    if assessment.reviewer_id != current_user.id:
        raise HTTPException(status_code=403, detail="This assessment is not assigned to you")
    review = ComplianceAssessmentReview(
        assessment_id=assessment.id,
        reviewer_id=current_user.id,
        outcome=review_in.outcome,
        note=review_in.note,
    )
    db.add(review)
    try:
        db.flush()
        db.add(AuditEvent(
            user_id=current_user.id,
            action="compliance_assessment.review_recorded",
            entity_type="compliance_assessment",
            entity_id=str(assessment.id),
            audit_metadata=json.dumps({"assessment_id": assessment.id, "outcome": review.outcome}),
        ))
        db.commit()
        db.refresh(review)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not save assessment review") from exc
    return _assessment_review_out(review)


@router.post("/{assessment_id}/assignment", response_model=ComplianceAssessmentOut)
def assign_compliance_assessment(
    assessment_id: int,
    assignment: ComplianceAssessmentAssignmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(status_code=403, detail="Only administrators can assign reviewers")
    assessment, application, rule = _assessment_for_user(assessment_id, db, current_user)
    reviewer = db.query(User).filter(
        User.id == assignment.reviewer_id,
        User.role == UserRole.REVIEWER.value,
        User.is_active.is_(True),
    ).first()
    if reviewer is None:
        raise HTTPException(status_code=422, detail="Select an active reviewer account")
    old_reviewer_id = assessment.reviewer_id
    assessment.reviewer_id = reviewer.id
    db.add(AuditEvent(
        user_id=current_user.id,
        action="compliance_assessment.reviewer_assigned",
        entity_type="compliance_assessment",
        entity_id=str(assessment.id),
        audit_metadata=json.dumps({
            "assessment_id": assessment.id,
            "application_id": application.id,
            "previous_reviewer_id": old_reviewer_id,
            "reviewer_id": reviewer.id,
        }),
    ))
    try:
        db.commit()
        db.refresh(assessment)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not assign reviewer") from exc
    return {
        "id": assessment.id,
        "application_id": application.id,
        "assigned_reviewer_id": reviewer.id,
        "application_reference": application.reference,
        "entity_name": application.entity_name,
        "rule_code": rule.rule_code,
        "rule_title": rule.title,
        "category": rule.category,
        "status": assessment.status,
        "review_status": assessment.review_status,
        "explanation": assessment.explanation,
        "assessed_at": assessment.assessed_at,
        "reviewer_name": reviewer.full_name,
    }


@router.post("/{assessment_id}/review-status")
def update_assessment_review_status(
    assessment_id: int,
    update: ComplianceAssessmentStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assessment, _application, _rule = _assessment_for_user(assessment_id, db, current_user)
    if current_user.role == UserRole.REVIEWER.value and assessment.reviewer_id != current_user.id:
        raise HTTPException(status_code=404, detail="Assessment not found")
    if current_user.role not in {UserRole.ADMIN.value, UserRole.REVIEWER.value}:
        raise HTTPException(status_code=403, detail="Not authorized to update review status")

    current_status = assessment.review_status
    requested_status = update.review_status
    transitions = {
        "PENDING_REVIEW": {"IN_REVIEW"},
        "IN_REVIEW": {"ADDITIONAL_INFORMATION_REQUIRED", "ESCALATED", "CLOSED"},
        "ADDITIONAL_INFORMATION_REQUIRED": {"IN_REVIEW", "ESCALATED", "CLOSED"},
        "ESCALATED": {"IN_REVIEW", "CLOSED"},
        "CLOSED": set(),
    }
    if requested_status == current_status:
        return {
            "assessment_id": assessment.id,
            "review_status": current_status,
            "changed": False,
        }
    if requested_status not in transitions.get(current_status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Review status cannot transition from {current_status} to {requested_status}",
        )
    reason = update.reason.strip() if update.reason else ""
    if requested_status in {"ADDITIONAL_INFORMATION_REQUIRED", "ESCALATED", "CLOSED"} and not reason:
        raise HTTPException(
            status_code=422,
            detail="A reason is required for this review status transition",
        )

    changed = db.query(ComplianceAssessment).filter(
        ComplianceAssessment.id == assessment.id,
        ComplianceAssessment.review_status == current_status,
    ).update(
        {ComplianceAssessment.review_status: requested_status},
        synchronize_session=False,
    )
    if changed != 1:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Review status changed concurrently; reload before retrying",
        )
    db.add(ComplianceAssessmentStatusHistory(
        assessment_id=assessment.id,
        reviewer_id=current_user.id,
        from_status=current_status,
        to_status=requested_status,
        reason=reason or None,
    ))
    db.add(AuditEvent(
        user_id=current_user.id,
        action="compliance_assessment.review_status_changed",
        entity_type="compliance_assessment",
        entity_id=str(assessment.id),
        audit_metadata=json.dumps({
            "from_status": current_status,
            "to_status": requested_status,
        }),
    ))
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not save review status") from exc
    return {
        "assessment_id": assessment.id,
        "review_status": requested_status,
        "changed": True,
    }


@router.get("/", response_model=ComplianceAssessmentPageOut)
def list_compliance_assessments(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    application_id: int | None = Query(default=None, gt=0),
    review_status: Literal[
        "PENDING_REVIEW",
        "IN_REVIEW",
        "ADDITIONAL_INFORMATION_REQUIRED",
        "ESCALATED",
        "CLOSED",
    ] | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = (
        db.query(ComplianceAssessment, Application, ComplianceRule, User)
        .join(Application, Application.id == ComplianceAssessment.application_id)
        .join(ComplianceRule, ComplianceRule.id == ComplianceAssessment.rule_id)
        .outerjoin(User, User.id == ComplianceAssessment.reviewer_id)
        .options(
            selectinload(ComplianceAssessment.reviews).joinedload(
                ComplianceAssessmentReview.reviewer
            )
        )
    )
    if current_user.role == UserRole.ADMIN.value:
        pass
    elif current_user.role == UserRole.INSTITUTION_USER.value:
        if current_user.institution_id is None:
            return {"items": [], "total": 0}
        query = query.filter(Application.institution_id == current_user.institution_id)
    elif current_user.role == UserRole.REVIEWER.value:
        query = query.filter(ComplianceAssessment.reviewer_id == current_user.id)
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access compliance assessments",
        )

    if application_id is not None:
        # Preserve the same role/ownership filter before applying an application filter.
        query = query.filter(ComplianceAssessment.application_id == application_id)
    if review_status is not None:
        query = query.filter(ComplianceAssessment.review_status == review_status)

    total = query.count()
    rows = (
        query.order_by(
            ComplianceAssessment.assessed_at.desc(),
            ComplianceAssessment.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    items = [
        {
            "id": assessment.id,
            "application_id": application.id,
            "assigned_reviewer_id": assessment.reviewer_id,
            "application_reference": application.reference,
            "entity_name": application.entity_name,
            "rule_code": rule.rule_code,
            "rule_title": rule.title,
            "category": rule.category,
            "status": assessment.status,
            "review_status": assessment.review_status,
            "explanation": assessment.explanation,
            "assessed_at": assessment.assessed_at,
            "reviewer_name": reviewer.full_name if reviewer else None,
            "reviews": [
                _assessment_review_out(review)
                for review in sorted(
                    assessment.reviews,
                    key=lambda item: (item.created_at, item.id),
                )
            ],
        }
        for assessment, application, rule, reviewer in rows
    ]
    return {"items": items, "total": total}
