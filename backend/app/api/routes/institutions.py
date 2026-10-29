import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.models import AuditEvent, Institution, User
from app.schemas.applications import InstitutionCreate, InstitutionOut


router = APIRouter()
logger = logging.getLogger(__name__)
admin_only = RoleChecker([UserRole.ADMIN])


@router.get("/", response_model=list[InstitutionOut])
def list_institutions(
    db: Session = Depends(get_db),
    _admin: User = Depends(admin_only),
):
    return db.query(Institution).order_by(Institution.name).all()


@router.post("/", response_model=InstitutionOut, status_code=status.HTTP_201_CREATED)
def create_institution(
    institution_in: InstitutionCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_only),
):
    institution = Institution(name=institution_in.name)
    db.add(institution)
    try:
        db.flush()
        db.add(
            AuditEvent(
                user_id=admin.id,
                action="institution.created",
                entity_type="institution",
                entity_id=str(institution.id),
                audit_metadata=json.dumps({"name": institution.name}),
            )
        )
        db.commit()
        db.refresh(institution)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Institution with this name already exists",
        ) from None
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Could not create institution")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create institution",
        ) from None
    return institution
