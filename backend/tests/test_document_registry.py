import fitz
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.security import get_password_hash
from app.db.base import Base
from app.db.session import get_db as real_get_db
from app.api.routes import applications as application_routes
from app.main import app
from app.models.enums import UserRole
from app.models.models import (
    Application,
    ComplianceAssessment,
    ComplianceRule,
    Document,
    DocumentSchemaVersion,
    DocumentType,
    DocumentTypeCorrection,
    Institution,
    User,
)
from app.services import document_processing


client = TestClient(app)
TEXT_SCHEMA = {
    "fields": [{
        "id": "institution_name",
        "label": "Institution name",
        "data_type": "string",
        "required": True,
        "constraints": {"min_length": 2},
    }]
}


@pytest.fixture
def registry_database(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(settings, "DOCUMENT_STORAGE_DIR", tmp_path / "documents")
    monkeypatch.setitem(app.dependency_overrides, real_get_db, override_get_db)
    Base.metadata.create_all(bind=engine)
    yield testing_session
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _create_user(test_database, email: str, role: UserRole, institution_id: int | None = None) -> str:
    with test_database() as db:
        db.add(User(
            full_name=email,
            email=email,
            password_hash=get_password_hash("test-password"),
            role=role.value,
            is_active=True,
            institution_id=institution_id,
        ))
        db.commit()
    return email


def _token(email: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "test-password"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_application(test_database, reference: str, institution_id: int | None = None) -> int:
    with test_database() as db:
        application = Application(
            reference=reference,
            entity_name="Registry Test Institute",
            app_type="Test",
            status="submitted",
            institution_id=institution_id,
        )
        db.add(application)
        db.commit()
        return application.id


def _create_institution(test_database, name: str) -> int:
    with test_database() as db:
        institution = Institution(name=name)
        db.add(institution)
        db.commit()
        return institution.id


def _registry_payload(
    type_id: str,
    name: str,
    schema: dict | None = None,
    formats=None,
    categories=None,
) -> dict:
    return {
        "id": type_id,
        "display_name": name,
        "category": "test",
        "description": "Test registry type; not an authoritative requirement.",
        "aliases": [],
        "supported_file_formats": formats or ["pdf"],
        "supported_languages": ["en"],
        "application_categories": categories or [],
        "regulatory_rule_references": [],
        "verification_config": {"method": "not_configured"},
        "schema_version": "1.0.0",
        "schema_definition": schema or TEXT_SCHEMA,
    }


def _create_active_type(headers, type_id: str, formats=None, categories=None) -> int:
    created = client.post(
        "/api/document-types/",
        headers=headers,
        json=_registry_payload(
            type_id,
            type_id.replace("_", " ").title(),
            formats=formats,
            categories=categories,
        ),
    )
    assert created.status_code == 201, created.text
    version_id = created.json()["schema_versions"][0]["id"]
    activated = client.post(
        f"/api/document-types/{type_id}/schema-versions/{version_id}/activate",
        headers=headers,
    )
    assert activated.status_code == 200, activated.text
    return version_id


def _pdf(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    result = document.tobytes()
    document.close()
    return result


def test_schema_schema_rejects_duplicate_fields_invalid_constraints_and_bad_versions():
    from pydantic import ValidationError

    from app.schemas.document_registry import DocumentTypeCreate

    duplicate_schema = {"fields": [
        {"id": "name", "label": "Name", "data_type": "string"},
        {"id": "name", "label": "Second name", "data_type": "string"},
    ]}
    with pytest.raises(ValidationError):
        DocumentTypeCreate.model_validate(
            _registry_payload("test_type", "Test Type", schema=duplicate_schema)
        )
    with pytest.raises(ValidationError):
        DocumentTypeCreate.model_validate({
            **_registry_payload("test_type", "Test Type"),
            "schema_version": "latest",
        })


def test_schema_validation_checks_supported_types_and_retains_source_values():
    from app.services.document_schema_validation import validate_extracted_fields

    schema = {
        "fields": [
            {
                "id": "code",
                "label": "Code",
                "data_type": "string",
                "required": True,
                "constraints": {"min_length": 3, "max_length": 4, "pattern": "^[A-Z0-9]+$"},
                "normalization": {"trim": True, "case": "upper"},
            },
            {"id": "state", "label": "State", "data_type": "enum", "required": True, "enum_values": ["ACTIVE", "EXPIRED"]},
            {
                "id": "page_numbers",
                "label": "Page numbers",
                "data_type": "array",
                "required": True,
                "items_type": "integer",
                "constraints": {"min_items": 1},
            },
            {
                "id": "issuer",
                "label": "Issuer",
                "data_type": "object",
                "required": True,
                "object_properties": {"name": "string", "country": "string"},
                "object_required_properties": ["name"],
            },
        ]
    }
    valid_values = {
        "code": {"value": " ab1 ", "page": 2, "evidence": "Code: ab1", "status": "extracted"},
        "state": {"value": "active", "page": 2, "evidence": "State: active", "status": "extracted"},
        "page_numbers": {"value": [1, 2], "page": 2, "evidence": "Pages: 1, 2", "status": "extracted"},
        "issuer": {"value": {"name": "Agency"}, "page": 2, "evidence": "Issuer: Agency", "status": "extracted"},
    }
    valid_result = validate_extracted_fields(schema, valid_values)
    assert valid_result["status"] == "valid"
    code = next(field for field in valid_result["fields"] if field["field_id"] == "code")
    assert code["value"] == " ab1 "
    assert code["raw_value"] == " ab1 "
    assert code["normalized_value"] == "AB1"
    assert code["source"]["evidence"] == "Code: ab1"

    invalid_values = {
        **valid_values,
        "code": {"value": "a@", "page": 2, "evidence": "Code: a@", "status": "extracted"},
        "state": {"value": "unknown", "page": 2, "evidence": "State: unknown", "status": "extracted"},
        "page_numbers": {"value": ["one"], "page": 2, "evidence": "Pages: one", "status": "extracted"},
        "issuer": {"value": {"country": "XX"}, "page": 2, "evidence": "Issuer: country XX", "status": "extracted"},
    }
    invalid_result = validate_extracted_fields(schema, invalid_values)
    assert invalid_result["status"] == "invalid"
    assert {field["status"] for field in invalid_result["fields"]} == {"invalid"}

    missing_result = validate_extracted_fields(schema, {})
    assert missing_result["status"] == "invalid"
    assert all(field["status"] == "missing_required" for field in missing_result["fields"])


def test_schema_value_normalization_parses_only_unambiguous_typed_values():
    from app.services.document_schema_validation import validate_extracted_fields

    schema = {"fields": [
        {"id": "issue_date", "label": "Issue date", "data_type": "date"},
        {"id": "ambiguous_date", "label": "Ambiguous date", "data_type": "date"},
        {"id": "staff_count", "label": "Staff count", "data_type": "integer"},
    ]}
    result = validate_extracted_fields(schema, {
        "issue_date": {"value": "15/08/2026", "raw_value": "15/08/2026", "page": 1, "evidence": "Issue date: 15/08/2026"},
        "ambiguous_date": {"value": "08/09/2026", "raw_value": "08/09/2026", "page": 1, "evidence": "Ambiguous date: 08/09/2026"},
        "staff_count": {"value": "24", "raw_value": "24", "page": 2, "evidence": "Staff count: 24"},
    })
    fields = {field["field_id"]: field for field in result["fields"]}
    assert fields["issue_date"]["value"] == "15/08/2026"
    assert fields["issue_date"]["raw_value"] == "15/08/2026"
    assert fields["issue_date"]["normalized_value"] == "2026-08-15"
    assert fields["issue_date"]["normalization_method"] == "unambiguous_day_first_date_parse"
    assert fields["ambiguous_date"]["status"] == "invalid"
    assert fields["ambiguous_date"]["normalized_value"] == "08/09/2026"
    assert fields["ambiguous_date"]["normalization_method"] == "ambiguous_or_invalid_date"
    assert fields["staff_count"]["normalized_value"] == 24
    assert fields["staff_count"]["source"]["evidence"] == "Staff count: 24"


def test_admin_registry_lifecycle_keeps_legacy_types_draft_and_versions_immutable(registry_database):
    admin = _create_user(registry_database, "registry-admin@example.com", UserRole.ADMIN)
    headers = _token(admin)

    unauthenticated = client.get("/api/document-types/")
    assert unauthenticated.status_code == 401
    valid_schema = client.post(
        "/api/document-types/validate-schema",
        headers=headers,
        json=TEXT_SCHEMA,
    )
    assert valid_schema.status_code == 200
    assert valid_schema.json()["status"] == "valid"
    invalid_schema = client.post(
        "/api/document-types/validate-schema",
        headers=headers,
        json={"fields": [{"id": "bad-id", "label": "Bad", "data_type": "string"}]},
    )
    assert invalid_schema.status_code == 422
    created = client.post(
        "/api/document-types/",
        headers=headers,
        json=_registry_payload("sample_certificate", "Sample certificate"),
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "draft"
    first = created.json()["schema_versions"][0]
    edited_type = client.patch(
        "/api/document-types/sample_certificate",
        headers=headers,
        json={"display_name": "Updated sample certificate", "family": "certificate"},
    )
    assert edited_type.status_code == 200
    assert edited_type.json()["display_name"] == "Updated sample certificate"
    assert edited_type.json()["family"] == "certificate"
    assert first["status"] == "draft"
    edited = client.put(
        f"/api/document-types/sample_certificate/schema-versions/{first['id']}",
        headers=headers,
        json=TEXT_SCHEMA,
    )
    assert edited.status_code == 200
    assert edited.json()["status"] == "draft"

    activated = client.post(
        f"/api/document-types/sample_certificate/schema-versions/{first['id']}/activate",
        headers=headers,
    )
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"
    active_type_edit = client.patch(
        "/api/document-types/sample_certificate",
        headers=headers,
        json={"display_name": "Changed after activation"},
    )
    assert active_type_edit.status_code == 409
    update_active = client.put(
        f"/api/document-types/sample_certificate/schema-versions/{first['id']}",
        headers=headers,
        json={"fields": [{"id": "changed", "label": "Changed", "data_type": "string"}]},
    )
    assert update_active.status_code == 409

    second = client.post(
        "/api/document-types/sample_certificate/schema-versions",
        headers=headers,
        json={"schema_version": "1.1.0", "definition": TEXT_SCHEMA},
    )
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]
    activated_second = client.post(
        f"/api/document-types/sample_certificate/schema-versions/{second_id}/activate",
        headers=headers,
    )
    assert activated_second.status_code == 200
    old_version = client.post(
        "/api/document-types/sample_certificate/schema-versions",
        headers=headers,
        json={"schema_version": "1.0.5", "definition": TEXT_SCHEMA},
    )
    assert old_version.status_code == 409
    with registry_database() as db:
        versions = db.query(DocumentSchemaVersion).order_by(DocumentSchemaVersion.id).all()
        assert [(item.schema_version, item.status) for item in versions] == [
            ("1.0.0", "deprecated"),
            ("1.1.0", "active"),
        ]
        assert versions[0].definition == first["definition"]

    user = _create_user(
        registry_database,
        "registry-reader@example.com",
        UserRole.INSTITUTION_USER,
    )
    deactivate = client.post(
        "/api/document-types/sample_certificate/deactivate",
        headers=headers,
    )
    assert deactivate.status_code == 200
    assert deactivate.json()["status"] == "inactive"
    public_list = client.get("/api/document-types/", headers=_token(user))
    assert public_list.status_code == 200
    assert public_list.json() == []
    with registry_database() as db:
        active_schema = db.query(DocumentSchemaVersion).filter_by(
            id=second_id,
        ).one()
        assert active_schema.status == "active"
    reactivate = client.post(
        "/api/document-types/sample_certificate/activate",
        headers=headers,
    )
    assert reactivate.status_code == 200
    assert reactivate.json()["status"] == "active"
    public_list = client.get("/api/document-types/", headers=_token(user))
    assert public_list.status_code == 200
    assert [item["id"] for item in public_list.json()] == ["sample_certificate"]
    assert all(item["status"] == "active" for item in public_list.json())
    denied_create = client.post(
        "/api/document-types/",
        headers=_token(user),
        json=_registry_payload("forbidden_type", "Forbidden Type"),
    )
    assert denied_create.status_code == 403
    denied_metadata_update = client.patch(
        "/api/document-types/sample_certificate",
        headers=_token(user),
        json={"display_name": "Unauthorized edit"},
    )
    assert denied_metadata_update.status_code == 403
    deprecated = client.post(
        "/api/document-types/sample_certificate/deprecate",
        headers=headers,
    )
    assert deprecated.status_code == 200
    assert deprecated.json()["status"] == "deprecated"


def test_processing_pins_active_schema_and_reports_persisted_field_provenance(registry_database):
    admin = _create_user(registry_database, "processing-admin@example.com", UserRole.ADMIN)
    admin_headers = _token(admin)
    first_schema_id = _create_active_type(admin_headers, "sample_certificate")

    institution_id = _create_institution(registry_database, "Registry Processing Institution")
    user = _create_user(
        registry_database,
        "processing-user@example.com",
        UserRole.INSTITUTION_USER,
        institution_id,
    )
    application_id = _create_application(registry_database, "REGISTRY-PROCESS-1", institution_id)
    headers = _token(user)
    uploaded = client.post(
        f"/api/applications/{application_id}/documents",
        headers=headers,
        data={"doc_type": "sample_certificate"},
        files={"file": ("sample.pdf", _pdf(
            "Institution Name: Sample Institute\n"
            "Supporting text ensures there is enough embedded PDF text for extraction."
        ), "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["id"]

    processed = client.post(
        f"/api/applications/{application_id}/documents/{document_id}/process",
        headers=headers,
    )
    assert processed.status_code == 200, processed.text
    first_result = processed.json()["schema_validation"]
    assert first_result["status"] == "valid"
    assert first_result["schema_version_id"] == first_schema_id
    assert first_result["human_review_required"] is True
    assert "does not establish document authenticity" in first_result["disclaimer"]
    assert first_result["fields"][0]["source"]["page"] == 1
    assert first_result["fields"][0]["source"]["evidence"] == "Institution Name: Sample Institute"
    with registry_database() as db:
        stored = db.query(Document).filter_by(id=document_id).one()
        assert stored.schema_version_id == first_schema_id
        assert stored.processed_doc_type == "sample_certificate"
        assert stored.processing_result["schema_validation"] == first_result
    first_run = client.post(
        f"/api/applications/{application_id}/validate-all",
        headers=headers,
    )
    assert first_run.status_code == 200, first_run.text
    first_run_data = first_run.json()
    schema_stage = next(
        stage for stage in first_run_data["stages"]
        if stage["name"] == "document_schema_validation"
    )
    assert schema_stage["status"] == "completed"
    first_run_schema = next(
        result for result in first_run_data["results"]
        if result["type"] == "document_schema_validation"
    )
    assert first_run_schema["schema_version_id"] == first_schema_id
    assert first_run_schema["fields"][0]["source"]["page"] == 1

    new_schema = client.post(
        "/api/document-types/sample_certificate/schema-versions",
        headers=admin_headers,
        json={
            "schema_version": "1.1.0",
            "definition": {"fields": [
                {"id": "certificate_number", "label": "Certificate number", "data_type": "string", "required": True},
            ]},
        },
    )
    assert new_schema.status_code == 201, new_schema.text
    second_schema_id = new_schema.json()["id"]
    activated = client.post(
        f"/api/document-types/sample_certificate/schema-versions/{second_schema_id}/activate",
        headers=admin_headers,
    )
    assert activated.status_code == 200

    reprocessed = client.post(
        f"/api/applications/{application_id}/documents/{document_id}/process",
        headers=headers,
    )
    assert reprocessed.status_code == 200, reprocessed.text
    assert reprocessed.json()["schema_validation"]["schema_version_id"] == second_schema_id
    assert reprocessed.json()["schema_validation"]["status"] == "invalid"
    with registry_database() as db:
        stored = db.query(Document).filter_by(id=document_id).one()
        assert stored.schema_version_id == second_schema_id
        assert stored.processing_result["schema_validation"]["status"] == "invalid"
    second_run = client.post(
        f"/api/applications/{application_id}/validate-all",
        headers=headers,
    )
    assert second_run.status_code == 200, second_run.text
    second_run_data = second_run.json()
    assert second_run_data["run_id"] != first_run_data["run_id"]
    history = client.get(
        f"/api/applications/{application_id}/validation-runs",
        headers=headers,
    )
    assert history.status_code == 200
    persisted_runs = history.json()["items"]
    persisted_first = next(item for item in persisted_runs if item["id"] == first_run_data["run_id"])
    persisted_second = next(item for item in persisted_runs if item["id"] == second_run_data["run_id"])
    first_snapshot = next(
        result for result in persisted_first["results"]
        if result["type"] == "document_schema_validation"
    )
    second_snapshot = next(
        result for result in persisted_second["results"]
        if result["type"] == "document_schema_validation"
    )
    assert first_snapshot["schema_version_id"] == first_schema_id
    assert second_snapshot["schema_version_id"] == second_schema_id


def test_unknown_draft_and_unsupported_format_are_explicit(registry_database):
    admin = _create_user(registry_database, "status-admin@example.com", UserRole.ADMIN)
    admin_headers = _token(admin)
    created = client.post(
        "/api/document-types/",
        headers=admin_headers,
        json=_registry_payload("draft_certificate", "Draft certificate"),
    )
    assert created.status_code == 201
    institution_id = _create_institution(registry_database, "Registry Status Institution")
    user = _create_user(
        registry_database,
        "status-user@example.com",
        UserRole.INSTITUTION_USER,
        institution_id,
    )
    application_id = _create_application(registry_database, "REGISTRY-STATUS-1", institution_id)
    headers = _token(user)

    draft_upload = client.post(
        f"/api/applications/{application_id}/documents",
        headers=headers,
        data={"doc_type": "draft_certificate"},
        files={"file": ("draft.pdf", _pdf(
            "Institution Name: Draft Institute\n"
            "Supporting text ensures there is enough embedded PDF text for extraction."
        ), "application/pdf")},
    )
    draft_result = client.post(
        f"/api/applications/{application_id}/documents/{draft_upload.json()['id']}/process",
        headers=headers,
    )
    assert draft_result.status_code == 200, draft_result.text
    assert draft_result.json()["schema_validation"]["status"] == "inactive_type"

    _create_active_type(admin_headers, "image_only_record", formats=["png"])
    unsupported_upload = client.post(
        f"/api/applications/{application_id}/documents",
        headers=headers,
        data={"doc_type": "image_only_record"},
        files={"file": ("unsupported.pdf", _pdf(
            "Institution Name: Other Institute\n"
            "Supporting text ensures there is enough embedded PDF text for extraction."
        ), "application/pdf")},
    )
    unsupported_result = client.post(
        f"/api/applications/{application_id}/documents/{unsupported_upload.json()['id']}/process",
        headers=headers,
    )
    assert unsupported_result.status_code == 200, unsupported_result.text
    assert unsupported_result.json()["schema_validation"]["status"] == "unsupported_format"

    unknown_upload = client.post(
        f"/api/applications/{application_id}/documents",
        headers=headers,
        data={"doc_type": "not_in_registry"},
        files={"file": ("unknown.pdf", _pdf(
            "Institution Name: Unknown Institute\n"
            "Supporting text ensures there is enough embedded PDF text for extraction."
        ), "application/pdf")},
    )
    unknown_result = client.post(
        f"/api/applications/{application_id}/documents/{unknown_upload.json()['id']}/process",
        headers=headers,
    )
    assert unknown_result.status_code == 200, unknown_result.text
    assert unknown_result.json()["schema_validation"]["status"] == "unknown_type"

    _create_active_type(
        admin_headers,
        "other_category_record",
        categories=["Another application category"],
    )
    category_upload = client.post(
        f"/api/applications/{application_id}/documents",
        headers=headers,
        data={"doc_type": "other_category_record"},
        files={"file": ("category.pdf", _pdf(
            "Institution Name: Category Institute\n"
            "Supporting text ensures there is enough embedded PDF text for extraction."
        ), "application/pdf")},
    )
    category_result = client.post(
        f"/api/applications/{application_id}/documents/{category_upload.json()['id']}/process",
        headers=headers,
    )
    assert category_result.status_code == 200, category_result.text
    assert category_result.json()["schema_validation"]["status"] == "not_applicable"


def test_processing_pending_and_failed_states_block_schema_success(registry_database, monkeypatch):
    admin = _create_user(registry_database, "stage-admin@example.com", UserRole.ADMIN)
    admin_headers = _token(admin)
    _create_active_type(admin_headers, "stage_certificate")
    institution_id = _create_institution(registry_database, "Registry Stage Institution")
    user = _create_user(
        registry_database,
        "stage-user@example.com",
        UserRole.INSTITUTION_USER,
        institution_id,
    )
    application_id = _create_application(registry_database, "REGISTRY-STAGE-1", institution_id)
    headers = _token(user)
    pending_upload = client.post(
        f"/api/applications/{application_id}/documents",
        headers=headers,
        data={"doc_type": "stage_certificate"},
        files={"file": ("pending.pdf", _pdf("Institution Name: Stage Institute\nEnough text for PDF."), "application/pdf")},
    )

    process_calls = []

    def return_ocr_unavailable(*args, **kwargs):
        process_calls.append(1)
        return {
            "processing_status": "ocr_unavailable",
            "extraction_method": "none",
            "pages_processed": 1,
            "field_extraction_version": application_routes.FIELD_EXTRACTION_VERSION,
            "fields": {"institution_name": {
                "value": None,
                "page": None,
                "evidence": None,
                "confidence": None,
                "status": "missing",
            }},
            "classification": None,
            "warnings": ["OCR is unavailable"],
        }

    monkeypatch.setattr(application_routes, "process_pdf", return_ocr_unavailable)
    pending = client.post(
        f"/api/applications/{application_id}/documents/{pending_upload.json()['id']}/process",
        headers=headers,
    )
    assert pending.status_code == 200, pending.text
    assert pending.json()["schema_validation"]["status"] == "blocked"
    assert pending.json()["schema_validation"]["human_review_required"] is True
    initial_schema_id = pending.json()["schema_validation"]["schema_version_id"]

    new_schema = client.post(
        "/api/document-types/stage_certificate/schema-versions",
        headers=admin_headers,
        json={"schema_version": "1.1.0", "definition": TEXT_SCHEMA},
    )
    assert new_schema.status_code == 201
    second_schema_id = new_schema.json()["id"]
    activated = client.post(
        f"/api/document-types/stage_certificate/schema-versions/{second_schema_id}/activate",
        headers=admin_headers,
    )
    assert activated.status_code == 200
    refreshed_pending = client.post(
        f"/api/applications/{application_id}/documents/{pending_upload.json()['id']}/process",
        headers=headers,
    )
    assert refreshed_pending.status_code == 200, refreshed_pending.text
    assert refreshed_pending.json()["schema_validation"]["status"] == "blocked"
    assert refreshed_pending.json()["schema_validation"]["schema_version_id"] != initial_schema_id
    assert process_calls == [1]

    failed_upload = client.post(
        f"/api/applications/{application_id}/documents",
        headers=headers,
        data={"doc_type": "stage_certificate"},
        files={"file": ("failed.pdf", _pdf("Institution Name: Stage Institute\nEnough text for PDF."), "application/pdf")},
    )

    def fail_processing(*args, **kwargs):
        raise document_processing.DocumentProcessingError("mock extraction failure")

    monkeypatch.setattr(application_routes, "process_pdf", fail_processing)
    failed = client.post(
        f"/api/applications/{application_id}/documents/{failed_upload.json()['id']}/process",
        headers=headers,
    )
    assert failed.status_code == 422
    stored = client.get(
        f"/api/applications/{application_id}/documents/{failed_upload.json()['id']}/processing-result",
        headers=headers,
    )
    assert stored.status_code == 200
    assert stored.json()["processing_status"] == "failed"
    assert stored.json()["schema_validation"]["status"] == "blocked"
    assert stored.json()["schema_validation"]["reason"] == (
        "Document processing status is 'failed'; schema validation was not performed."
    )


def test_reviewer_type_correction_preserves_prediction_and_append_only_history(registry_database):
    admin = _create_user(registry_database, "correction-admin@example.com", UserRole.ADMIN)
    admin_headers = _token(admin)
    _create_active_type(admin_headers, "certificate_type_a")
    _create_active_type(admin_headers, "certificate_type_b")
    _create_active_type(admin_headers, "fire_safety_certificate")
    with registry_database() as db:
        fire_type = db.query(DocumentType).filter_by(id="fire_safety_certificate").one()
        fire_type.aliases = ["fire safety certificate", "fire department"]
        db.commit()

    institution_id = _create_institution(registry_database, "Correction Institution")
    user = _create_user(
        registry_database,
        "correction-user@example.com",
        UserRole.INSTITUTION_USER,
        institution_id,
    )
    reviewer = _create_user(
        registry_database,
        "correction-reviewer@example.com",
        UserRole.REVIEWER,
    )
    application_id = _create_application(registry_database, "REGISTRY-CORRECTION-1", institution_id)
    headers = _token(user)
    reviewer_headers = _token(reviewer)
    with registry_database() as db:
        reviewer_id = db.query(User.id).filter_by(email=reviewer).scalar()
        rule = ComplianceRule(
            rule_code="REGISTRY-CORRECTION-REVIEW",
            title="Registry correction test",
            description="Test reviewer assignment.",
            category="test",
            is_active=True,
        )
        db.add(rule)
        db.flush()
        db.add(ComplianceAssessment(
            application_id=application_id,
            rule_id=rule.id,
            status="Pending",
            explanation="Assigned for document type review.",
            reviewer_id=reviewer_id,
        ))
        db.commit()
    uploaded = client.post(
        f"/api/applications/{application_id}/documents",
        headers=headers,
        data={"doc_type": "certificate_type_a"},
        files={
            "file": (
                "candidate.pdf",
                _pdf("Fire Safety Certificate\nFire Department\nInstitution Name: Candidate Institute"),
                "application/pdf",
            )
        },
    )
    document_id = uploaded.json()["id"]
    processed = client.post(
        f"/api/applications/{application_id}/documents/{document_id}/process",
        headers=headers,
    )
    assert processed.status_code == 200, processed.text
    prediction = processed.json()["classification"]["candidate_document_type"]
    assert prediction == "fire_safety_certificate"

    denied = client.post(
        f"/api/applications/{application_id}/documents/{document_id}/type-corrections",
        headers=headers,
        json={"document_type_id": "certificate_type_b", "reason": "Reviewer confirmed document type."},
    )
    assert denied.status_code == 403

    correction = client.post(
        f"/api/applications/{application_id}/documents/{document_id}/type-corrections",
        headers=reviewer_headers,
        json={"document_type_id": "certificate_type_b", "reason": "Reviewer confirmed document type."},
    )
    assert correction.status_code == 200, correction.text
    assert correction.json()["original_prediction"] == prediction
    assert correction.json()["processing_status"] == "pending"
    history = client.get(
        f"/api/applications/{application_id}/documents/{document_id}/type-corrections",
        headers=reviewer_headers,
    )
    assert history.status_code == 200
    assert len(history.json()) == 1
    assert history.json()[0]["previous_document_type"] == "certificate_type_a"
    with registry_database() as db:
        document = db.query(Document).filter_by(id=document_id).one()
        assert document.doc_type == "certificate_type_b"
        assert document.predicted_doc_type == prediction
        assert document.processing_result is None
        assert db.query(DocumentTypeCorrection).filter_by(document_id=document_id).count() == 1
