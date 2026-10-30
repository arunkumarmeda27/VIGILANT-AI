import json
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.api.deps import RoleChecker, get_current_user
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.models import AuditEvent, DocumentSchemaVersion, DocumentType, User
from app.schemas.document_registry import (
    DocumentTypeCreate,
    DocumentTypeMetadataUpdate,
    DocumentTypeOut,
    SchemaDefinition,
    SchemaValidationOut,
    SchemaVersionCreate,
)


router = APIRouter()
admin_only = RoleChecker([UserRole.ADMIN])


def _type_payload(document_type: DocumentType) -> dict:
    return {
        "id": document_type.id,
        "display_name": document_type.display_name,
        "category": document_type.category,
        "family": document_type.family,
        "description": document_type.description,
        "aliases": document_type.aliases or [],
        "supported_file_formats": document_type.supported_file_formats or [],
        "supported_languages": document_type.supported_languages or [],
        "application_categories": document_type.application_categories or [],
        "regulatory_rule_references": document_type.regulatory_rule_references or [],
        "issuing_authority": document_type.issuing_authority,
        "verification_config": document_type.verification_config,
        "expiry_config": document_type.expiry_config,
        "status": document_type.status,
        "schema_versions": [
            {
                "id": version.id,
                "schema_version": version.schema_version,
                "definition": version.definition,
                "status": version.status,
                "created_at": version.created_at,
                "activated_at": version.activated_at,
            }
            for version in document_type.schema_versions
        ],
    }


def _get_type(db: Session, document_type_id: str) -> DocumentType:
    result = (
        db.query(DocumentType)
        .options(selectinload(DocumentType.schema_versions))
        .filter(DocumentType.id == document_type_id)
        .first()
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Document type not found")
    return result


def _record_admin_event(
    db: Session,
    current_user: User,
    action: str,
    document_type_id: str,
    metadata: dict,
) -> None:
    db.add(AuditEvent(
        user_id=current_user.id,
        action=action,
        entity_type="document_type",
        entity_id=document_type_id,
        audit_metadata=json.dumps(metadata),
    ))


def _version_tuple(version: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version):
        raise HTTPException(status_code=422, detail="Schema version must use MAJOR.MINOR.PATCH")
    return tuple(int(part) for part in version.split("."))


@router.get("/", response_model=list[DocumentTypeOut])
def list_document_types(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(DocumentType).options(selectinload(DocumentType.schema_versions))
    if current_user.role != UserRole.ADMIN.value:
        query = query.filter(DocumentType.status == "active")
    rows = query.order_by(DocumentType.id).all()
    return [_type_payload(row) for row in rows]


@router.get("/{document_type_id}", response_model=DocumentTypeOut)
def get_document_type(
    document_type_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    document_type = _get_type(db, document_type_id)
    if current_user.role != UserRole.ADMIN.value and document_type.status != "active":
        raise HTTPException(status_code=404, detail="Document type not found")
    return _type_payload(document_type)


@router.post("/", response_model=DocumentTypeOut, status_code=status.HTTP_201_CREATED)
def create_document_type(
    payload: DocumentTypeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    if db.query(DocumentType.id).filter(DocumentType.id == payload.id).first():
        raise HTTPException(status_code=409, detail="Document type already exists")

    document_type = DocumentType(
        id=payload.id,
        display_name=payload.display_name,
        category=payload.category,
        family=payload.family,
        description=payload.description,
        aliases=payload.aliases,
        supported_file_formats=payload.supported_file_formats,
        supported_languages=payload.supported_languages,
        application_categories=payload.application_categories,
        regulatory_rule_references=payload.regulatory_rule_references,
        issuing_authority=payload.issuing_authority.model_dump(mode="json") if payload.issuing_authority else None,
        verification_config=payload.verification_config.model_dump(mode="json"),
        expiry_config=payload.expiry_config.model_dump(mode="json") if payload.expiry_config else None,
        status="draft",
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    schema_version = DocumentSchemaVersion(
        schema_version=payload.schema_version,
        definition=payload.schema_definition.model_dump(mode="json"),
        status="draft",
        created_by=current_user.id,
    )
    document_type.schema_versions.append(schema_version)
    db.add(document_type)
    _record_admin_event(db, current_user, "document_type.created", payload.id, {
        "status": "draft",
        "schema_version": payload.schema_version,
    })
    try:
        db.commit()
        db.refresh(document_type)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Document type or schema version already exists") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not save document type") from exc
    return _type_payload(_get_type(db, document_type.id))


@router.patch("/{document_type_id}", response_model=DocumentTypeOut)
def update_document_type_metadata(
    document_type_id: str,
    payload: DocumentTypeMetadataUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    document_type = _get_type(db, document_type_id)
    if document_type.status != "draft":
        raise HTTPException(
            status_code=409,
            detail="Only draft document type metadata can be edited",
        )
    for field in payload.model_fields_set:
        setattr(document_type, field, getattr(payload, field))
    document_type.updated_by = current_user.id
    document_type.updated_at = datetime.now(timezone.utc)
    _record_admin_event(
        db,
        current_user,
        "document_type.draft_updated",
        document_type_id,
        {"updated_fields": sorted(payload.model_fields_set)},
    )
    try:
        db.commit()
        db.refresh(document_type)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not update document type") from exc
    return _type_payload(_get_type(db, document_type_id))


@router.post("/{document_type_id}/schema-versions", status_code=status.HTTP_201_CREATED)
def create_schema_version(
    document_type_id: str,
    payload: SchemaVersionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    document_type = _get_type(db, document_type_id)
    if document_type.status == "deprecated":
        raise HTTPException(status_code=409, detail="A deprecated document type cannot receive new schemas")
    existing_versions = [
        _version_tuple(version.schema_version) for version in document_type.schema_versions
    ]
    if existing_versions and _version_tuple(payload.schema_version) <= max(existing_versions):
        raise HTTPException(status_code=409, detail="New schema version must be greater than existing versions")
    version = DocumentSchemaVersion(
        document_type_id=document_type.id,
        schema_version=payload.schema_version,
        definition=payload.definition.model_dump(mode="json"),
        status="draft",
        created_by=current_user.id,
    )
    db.add(version)
    _record_admin_event(db, current_user, "document_schema.created", document_type_id, {
        "schema_version": payload.schema_version,
        "status": "draft",
    })
    try:
        db.commit()
        db.refresh(version)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Schema version already exists") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not save schema version") from exc
    return {
        "id": version.id,
        "document_type_id": version.document_type_id,
        "schema_version": version.schema_version,
        "definition": version.definition,
        "status": version.status,
        "created_at": version.created_at,
    }


@router.put("/{document_type_id}/schema-versions/{version_id}")
def update_draft_schema(
    document_type_id: str,
    version_id: int,
    payload: SchemaDefinition,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    version = db.query(DocumentSchemaVersion).filter(
        DocumentSchemaVersion.id == version_id,
        DocumentSchemaVersion.document_type_id == document_type_id,
    ).first()
    if version is None:
        raise HTTPException(status_code=404, detail="Schema version not found")
    if version.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft schema versions can be changed")
    version.definition = payload.model_dump(mode="json")
    version.updated_at = datetime.now(timezone.utc)
    _record_admin_event(db, current_user, "document_schema.draft_updated", document_type_id, {
        "schema_version": version.schema_version,
    })
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not update draft schema") from exc
    return {
        "id": version.id,
        "document_type_id": version.document_type_id,
        "schema_version": version.schema_version,
        "definition": version.definition,
        "status": version.status,
    }


@router.post("/{document_type_id}/schema-versions/{version_id}/activate")
def activate_schema_version(
    document_type_id: str,
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    document_type = _get_type(db, document_type_id)
    if document_type.status == "deprecated":
        raise HTTPException(status_code=409, detail="A deprecated document type cannot be activated")
    target = next((v for v in document_type.schema_versions if v.id == version_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Schema version not found")
    if target.status != "draft":
        raise HTTPException(status_code=409, detail="Only a draft schema version can be activated")
    active_versions = [
        _version_tuple(version.schema_version)
        for version in document_type.schema_versions
        if version.status == "active"
    ]
    if active_versions and _version_tuple(target.schema_version) <= max(active_versions):
        raise HTTPException(status_code=409, detail="Activated schema versions must move forward")

    for existing in document_type.schema_versions:
        if existing.status == "active":
            existing.status = "deprecated"
    target.status = "active"
    target.activated_by = current_user.id
    target.activated_at = datetime.now(timezone.utc)
    document_type.status = "active"
    document_type.updated_by = current_user.id
    _record_admin_event(db, current_user, "document_schema.activated", document_type_id, {
        "schema_version": target.schema_version,
    })
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not activate schema version") from exc
    return {
        "document_type_id": document_type.id,
        "schema_version_id": target.id,
        "schema_version": target.schema_version,
        "status": target.status,
    }


@router.post("/{document_type_id}/deprecate")
def deprecate_document_type(
    document_type_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    document_type = _get_type(db, document_type_id)
    document_type.status = "deprecated"
    document_type.updated_by = current_user.id
    for version in document_type.schema_versions:
        if version.status == "active":
            version.status = "deprecated"
    _record_admin_event(db, current_user, "document_type.deprecated", document_type_id, {})
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not deprecate document type") from exc
    return {"document_type_id": document_type_id, "status": "deprecated"}


@router.post("/{document_type_id}/deactivate")
def deactivate_document_type(
    document_type_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    document_type = _get_type(db, document_type_id)
    if document_type.status == "deprecated":
        raise HTTPException(status_code=409, detail="A deprecated document type cannot be deactivated")
    if document_type.status == "draft":
        raise HTTPException(status_code=409, detail="A draft document type is already inactive")
    if document_type.status == "active":
        document_type.status = "inactive"
        document_type.updated_by = current_user.id
        _record_admin_event(
            db,
            current_user,
            "document_type.deactivated",
            document_type_id,
            {},
        )
        try:
            db.commit()
        except SQLAlchemyError as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail="Could not deactivate document type") from exc
    return {"document_type_id": document_type_id, "status": document_type.status}


@router.post("/{document_type_id}/activate")
def activate_document_type(
    document_type_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    document_type = _get_type(db, document_type_id)
    if document_type.status == "deprecated":
        raise HTTPException(status_code=409, detail="A deprecated document type cannot be activated")
    if document_type.status == "draft":
        raise HTTPException(
            status_code=409,
            detail="Activate a schema version before activating a document type",
        )
    if document_type.status != "active":
        has_active_schema = any(
            version.status == "active" for version in document_type.schema_versions
        )
        if not has_active_schema:
            raise HTTPException(
                status_code=409,
                detail="A document type requires an active schema before reactivation",
            )
        document_type.status = "active"
        document_type.updated_by = current_user.id
        _record_admin_event(
            db,
            current_user,
            "document_type.activated",
            document_type_id,
            {},
        )
        try:
            db.commit()
        except SQLAlchemyError as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail="Could not activate document type") from exc
    return {"document_type_id": document_type_id, "status": document_type.status}


@router.post("/validate-schema", response_model=SchemaValidationOut)
def validate_schema(
    definition: SchemaDefinition,
    current_user: User = Depends(admin_only),
):
    return {
        "status": "valid",
        "schema_version_id": None,
        "fields": [field.model_dump(mode="json") for field in definition.fields],
        "unlisted_extracted_fields": [],
    }


@router.get("/{document_type_id}/schema-versions/{version_id}")
def get_schema_version(
    document_type_id: str,
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    version = db.query(DocumentSchemaVersion).filter(
        DocumentSchemaVersion.id == version_id,
        DocumentSchemaVersion.document_type_id == document_type_id,
    ).first()
    if version is None:
        raise HTTPException(status_code=404, detail="Schema version not found")
    return {
        "id": version.id,
        "document_type_id": version.document_type_id,
        "schema_version": version.schema_version,
        "definition": version.definition,
        "status": version.status,
        "created_at": version.created_at,
        "activated_at": version.activated_at,
    }
