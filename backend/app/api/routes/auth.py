import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.models import AuditEvent, User
from app.core.security import verify_password, create_access_token
from app.schemas.auth import Token, UserLogin, UserOut, UserCreate, UserUpdate, UserPageOut
from app.api.deps import get_current_user, RoleChecker
from app.models.enums import UserRole

router = APIRouter()

@router.post("/login", response_model=Token)
def login(login_data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == login_data.email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not verify_password(login_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled"
        )

    access_token = create_access_token(subject=user.email)
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/users", response_model=UserPageOut)
def list_users(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, max_length=120),
    role: UserRole | None = None,
    is_active: bool | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(RoleChecker([UserRole.ADMIN])),
):
    query = db.query(User)
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter((User.full_name.ilike(term)) | (User.email.ilike(term)))
    if role is not None:
        query = query.filter(User.role == role.value)
    if is_active is not None:
        query = query.filter(User.is_active.is_(is_active))

    total = query.count()
    users = query.order_by(User.full_name, User.id).offset(offset).limit(limit).all()
    return {"items": users, "total": total, "limit": limit, "offset": offset}

@router.post("/users", response_model=UserOut)
def create_user(
    user_in: UserCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(RoleChecker([UserRole.ADMIN]))
):
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == user_in.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists"
        )

    from app.core.security import get_password_hash
    new_user = User(
        full_name=user_in.full_name,
        email=user_in.email,
        password_hash=get_password_hash(user_in.password),
        role=user_in.role,
        is_active=True
    )
    db.add(new_user)
    try:
        db.flush()
        db.add(AuditEvent(
            user_id=admin.id,
            action="user.created",
            entity_type="user",
            entity_id=str(new_user.id),
            audit_metadata=json.dumps({"changed_fields": ["full_name", "email", "role", "is_active"]}),
        ))
        db.commit()
        db.refresh(new_user)
    except Exception:
        db.rollback()
        raise
    return new_user

@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    user_update: UserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(RoleChecker([UserRole.ADMIN]))
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    updates = user_update.model_dump(exclude_unset=True)
    if user.id == admin.id:
        if updates.get("is_active") is False:
            raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
        if "role" in updates and updates["role"] != UserRole.ADMIN:
            raise HTTPException(status_code=400, detail="You cannot remove your own administrator role")

    changed_fields = []
    for key, value in updates.items():
        if hasattr(value, "value"):
            value = value.value
        if getattr(user, key) != value:
            setattr(user, key, value)
            changed_fields.append(key)

    if changed_fields:
        db.add(AuditEvent(
            user_id=admin.id,
            action="user.updated",
            entity_type="user",
            entity_id=str(user.id),
            audit_metadata=json.dumps({"changed_fields": changed_fields}),
        ))

    try:
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        raise
    return user
