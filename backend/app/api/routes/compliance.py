from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.models import Application, ComplianceAssessment, ComplianceRule, User
from app.schemas.applications import (
    ComplianceAssessmentOut,
    ComplianceAssessmentPageOut,
)


router = APIRouter()


@router.get("/", response_model=ComplianceAssessmentPageOut)
def list_compliance_assessments(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = (
        db.query(ComplianceAssessment, Application, ComplianceRule, User)
        .join(Application, Application.id == ComplianceAssessment.application_id)
        .join(ComplianceRule, ComplianceRule.id == ComplianceAssessment.rule_id)
        .outerjoin(User, User.id == ComplianceAssessment.reviewer_id)
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
            "application_reference": application.reference,
            "entity_name": application.entity_name,
            "rule_code": rule.rule_code,
            "rule_title": rule.title,
            "category": rule.category,
            "status": assessment.status,
            "explanation": assessment.explanation,
            "assessed_at": assessment.assessed_at,
            "reviewer_name": reviewer.full_name if reviewer else None,
        }
        for assessment, application, rule, reviewer in rows
    ]
    return {"items": items, "total": total}
