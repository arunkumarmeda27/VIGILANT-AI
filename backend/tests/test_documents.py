import hashlib
import json
from io import BytesIO

import fitz
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import create_engine, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.security import get_password_hash
from app.db.base import Base
from app.db.session import get_db as real_get_db
from app.main import app
from app.models.enums import UserRole
from app.models.models import (
    Application,
    AuditEvent,
    ComplianceAssessment,
    ComplianceRule,
    Document,
    Finding,
    FindingReview,
    Institution,
    User,
)
from app.services import document_processing
from app.services.checklists import parse_unambiguous_date
from app.api.routes import applications as application_routes


def make_text_pdf(text: str) -> bytes:
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), text)
    content = pdf.tobytes()
    pdf.close()
    return content


def make_image_pdf() -> bytes:
    image = Image.new("RGB", (900, 300), "white")
    ImageDraw.Draw(image).text((30, 30), "Institution Name: Image Institute", fill="black")
    image_buffer = BytesIO()
    image.save(image_buffer, format="PNG")
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_image(page.rect, stream=image_buffer.getvalue())
    content = pdf.tobytes()
    pdf.close()
    return content


def make_blank_pdf() -> bytes:
    pdf = fitz.open()
    pdf.new_page()
    content = pdf.tobytes()
    pdf.close()
    return content


PDF_CONTENT = make_text_pdf("Sample document")
client = TestClient(app)


@pytest.fixture
def test_database(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'documents.db'}",
        connect_args={"check_same_thread": False},
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(settings, "DOCUMENT_STORAGE_DIR", tmp_path / "document-storage")
    monkeypatch.setitem(app.dependency_overrides, real_get_db, override_get_db)
    Base.metadata.create_all(bind=engine)
    yield testing_session_local
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def create_institution(test_database, name):
    with test_database() as db:
        institution = Institution(name=name)
        db.add(institution)
        db.commit()
        return institution.id


def create_user(test_database, email, role, institution_id=None):
    with test_database() as db:
        user = User(
            full_name=email,
            email=email,
            password_hash=get_password_hash("test-password"),
            role=role.value,
            is_active=True,
            institution_id=institution_id,
        )
        db.add(user)
        db.commit()
        return user.id


def create_application(test_database, reference, institution_id=None):
    with test_database() as db:
        application = Application(
            reference=reference,
            entity_name="Test Entity",
            app_type="Test",
            status="submitted",
            institution_id=institution_id,
        )
        db.add(application)
        db.commit()
        return application.id


def login(email):
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "test-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def upload(application_id, headers, filename="supporting.pdf", content=PDF_CONTENT, content_type="application/pdf"):
    return client.post(
        f"/api/applications/{application_id}/documents",
        headers=headers,
        files={"file": (filename, content, content_type)},
    )


def process(application_id, document_id, headers):
    return client.post(
        f"/api/applications/{application_id}/documents/{document_id}/process",
        headers=headers,
    )


def validate(application_id, document_id, headers):
    return client.post(
        f"/api/applications/{application_id}/documents/{document_id}/validate",
        headers=headers,
    )


def inspect_integrity(application_id, document_id, headers):
    return client.get(
        f"/api/applications/{application_id}/documents/{document_id}/integrity-preview",
        headers=headers,
    )


def create_processed_document(
    test_database,
    email,
    reference,
    content=None,
):
    if content is None:
        content = make_text_pdf(
            "Synthetic processed document with enough searchable text for extraction."
        )
    institution_id = create_institution(test_database, f"{reference} institution")
    create_user(test_database, email, UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, reference, institution_id)
    headers = login(email)
    uploaded = upload(application_id, headers, content=content)
    assert uploaded.status_code == 201
    processed = process(application_id, uploaded.json()["id"], headers)
    assert processed.status_code == 200
    return application_id, uploaded.json()["id"], headers


def test_pdf_upload_persists_metadata_and_hash(test_database):
    institution_id = create_institution(test_database, "Upload institution")
    create_user(test_database, "uploader@example.com", UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, "UPLOAD-1", institution_id)

    response = upload(
        application_id,
        login("uploader@example.com"),
        filename=r"..\private\proof.pdf",
        content_type="text/plain",
    )

    assert response.status_code == 201
    result = response.json()
    assert result["original_filename"] == "proof.pdf"
    assert result["application_id"] == application_id
    assert result["sha256"] == hashlib.sha256(PDF_CONTENT).hexdigest()
    assert result["file_size"] == len(PDF_CONTENT)
    assert result["processing_status"] == "pending"

    stored_files = list(settings.DOCUMENT_STORAGE_DIR.iterdir())
    assert len(stored_files) == 1
    assert stored_files[0].name == f"{stored_files[0].stem}.pdf"
    assert stored_files[0].read_bytes() == PDF_CONTENT
    with test_database() as db:
        document = db.query(Document).one()
        assert document.sha256 == result["sha256"]
        assert document.file_size == len(PDF_CONTENT)
        assert document.storage_key == stored_files[0].name
        audit = db.query(AuditEvent).filter_by(
            action="document.uploaded",
            entity_id=str(document.id),
        ).one()
        assert audit.user_id is not None
        assert "sha256" not in audit.audit_metadata


def test_integrity_preview_detects_identical_files_only_within_application(test_database):
    institution_id = create_institution(test_database, "Integrity institution")
    create_user(test_database, "integrity@example.com", UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, "INTEGRITY-1", institution_id)
    headers = login("integrity@example.com")
    first = upload(application_id, headers, filename="first.pdf", content=PDF_CONTENT)
    second = upload(application_id, headers, filename="second.pdf", content=PDF_CONTENT)
    assert first.status_code == 201
    assert second.status_code == 201

    response = inspect_integrity(application_id, second.json()["id"], headers)

    assert response.status_code == 200
    result = response.json()
    assert result["duplicate_file_check"]["status"] == "duplicate"
    assert result["duplicate_file_check"]["matches"] == [{
        "document_id": first.json()["id"],
        "original_filename": "first.pdf",
    }]
    assert result["authenticity_status"] == "not_assessed"
    assert result["issuer_verification"] == "not_performed"
    assert "does not establish" in result["limitations"][1]


def test_duplicate_upload_persists_advisory_finding_and_audit_without_cross_application_match(test_database):
    institution_id = create_institution(test_database, "Duplicate institution")
    create_user(test_database, "duplicate@example.com", UserRole.INSTITUTION_USER, institution_id)
    first_application = create_application(test_database, "DUPLICATE-A", institution_id)
    second_application = create_application(test_database, "DUPLICATE-B", institution_id)
    headers = login("duplicate@example.com")
    first = upload(first_application, headers, filename="original.pdf", content=PDF_CONTENT)
    same = upload(first_application, headers, filename="renamed.pdf", content=PDF_CONTENT)
    different = upload(first_application, headers, filename="different.pdf", content=make_text_pdf("Different PDF bytes"))
    across_application = upload(second_application, headers, filename="other-app.pdf", content=PDF_CONTENT)
    assert all(response.status_code == 201 for response in [first, same, different, across_application])

    with test_database() as db:
        duplicate_findings = db.query(Finding).filter_by(finding_type="Duplicate document").all()
        assert len(duplicate_findings) == 1
        assert duplicate_findings[0].application_id == first_application
        assert duplicate_findings[0].document_id == same.json()["id"]
        assert "not a fraud finding" in duplicate_findings[0].description
        event = db.query(AuditEvent).filter_by(action="document.duplicate_detected").one()
        assert json.loads(event.audit_metadata)["matched_document_id"] == first.json()["id"]
        assert db.query(Finding).filter(Finding.document_id == different.json()["id"]).count() == 0
        assert db.query(Finding).filter(Finding.application_id == second_application).count() == 0


def test_synthetic_checklist_distinguishes_missing_pending_and_incomplete_fields(test_database):
    institution_id = create_institution(test_database, "Checklist institution")
    create_user(test_database, "checklist@example.com", UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, "CHECKLIST-1", institution_id)
    with test_database() as db:
        app_obj = db.query(Application).filter_by(id=application_id).one()
        app_obj.app_type = "Technical Institution"
        db.add(Document(application_id=application_id, doc_type="fire_safety_certificate", original_filename="pending.pdf", storage_key="pending.pdf", processing_status="pending"))
        db.commit()

    headers = login("checklist@example.com")
    preview = client.get(f"/api/applications/{application_id}/checklist", headers=headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["items"][0]["status"] == "processing_pending"
    with test_database() as db:
        assert db.query(Finding).filter_by(application_id=application_id).count() == 0
        assert db.query(AuditEvent).filter_by(action="application.checklist_validated").count() == 0

    response = client.post(f"/api/applications/{application_id}/validate-checklist", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["source"] == "synthetic_demo"
    assert data["items"][0]["status"] == "processing_pending"
    with test_database() as db:
        finding_descriptions = [finding.description for finding in db.query(Finding).filter_by(application_id=application_id).all()]
        assert any("processing_pending" in description for description in finding_descriptions)
        assert any("missing_document" in description for description in finding_descriptions)
        assert db.query(AuditEvent).filter_by(action="application.checklist_validated").count() == 1

    incomplete_app_id = create_application(test_database, "CHECKLIST-INCOMPLETE", institution_id)
    with test_database() as db:
        app_obj = db.query(Application).filter_by(id=incomplete_app_id).one()
        app_obj.app_type = "Standard Regulatory"
        db.add(Document(
            application_id=incomplete_app_id,
            doc_type="fire_safety_certificate",
            original_filename="incomplete.pdf",
            storage_key="incomplete.pdf",
            processing_status="completed",
            processing_result={"fields": {"institution_name": {"value": "Test Entity"}, "certificate_number": {"value": None}, "expiry_date": {"value": None}}},
        ))
        db.commit()
    incomplete = client.post(f"/api/applications/{incomplete_app_id}/validate-checklist", headers=login("checklist@example.com"))
    assert incomplete.status_code == 200
    assert incomplete.json()["items"][0]["status"] == "incomplete_fields"
    assert set(incomplete.json()["items"][0]["missing_fields"]) == {"certificate_number", "expiry_date"}


def test_checklist_preview_requires_authentication_and_respects_application_ownership(test_database):
    owner_institution = create_institution(test_database, "Checklist preview owner")
    other_institution = create_institution(test_database, "Checklist preview other")
    create_user(test_database, "checklist-preview-owner@example.com", UserRole.INSTITUTION_USER, owner_institution)
    create_user(test_database, "checklist-preview-other@example.com", UserRole.INSTITUTION_USER, other_institution)
    application_id = create_application(test_database, "CHECKLIST-PREVIEW-ACCESS", owner_institution)

    unauthenticated = client.get(f"/api/applications/{application_id}/checklist")
    forbidden = client.get(
        f"/api/applications/{application_id}/checklist",
        headers=login("checklist-preview-other@example.com"),
    )
    assert unauthenticated.status_code == 401
    assert forbidden.status_code == 404


def test_eoa_application_has_explicit_synthetic_checklist_without_scope_claim(test_database):
    institution_id = create_institution(test_database, "EoA checklist institution")
    create_user(test_database, "eoa-checklist@example.com", UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, "EOA-CHECKLIST-1", institution_id)
    with test_database() as db:
        application = db.query(Application).filter_by(id=application_id).one()
        application.app_type = "Extension of Approval (EoA)"
        db.commit()

    response = client.post(
        f"/api/applications/{application_id}/validate-checklist",
        headers=login("eoa-checklist@example.com"),
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["category"] == "Extension of Approval (EoA)"
    assert result["source"] == "synthetic_demo"
    assert [item["document_type"] for item in result["items"]] == ["fire_safety_certificate"]
    assert result["items"][0]["status"] == "missing_document"


def test_reviewer_decisions_are_append_only_audited_and_assignment_protected(test_database):
    assigned_id = create_user(test_database, "finding-reviewer@example.com", UserRole.REVIEWER)
    other_id = create_user(test_database, "other-reviewer@example.com", UserRole.REVIEWER)
    app_id = create_application(test_database, "FINDING-REVIEW")
    rule = ComplianceRule(rule_code="REVIEW-ASSIGN", title="Assignment", description="Assignment", category="test", is_active=True)
    with test_database() as db:
        db.add(rule); db.flush()
        db.add(ComplianceAssessment(application_id=app_id, rule_id=rule.id, reviewer_id=assigned_id, status="pending", explanation=""))
        finding = Finding(application_id=app_id, finding_type="Test", severity="Low", description="Advisory test finding", status="open")
        db.add(finding); db.commit(); finding_id = finding.id
    assigned = login("finding-reviewer@example.com")
    unassigned = login("other-reviewer@example.com")

    rejected = client.post(f"/api/applications/{app_id}/findings/{finding_id}/reviews", headers=unassigned, json={"outcome": "false_positive", "note": "No assignment"})
    first = client.post(f"/api/applications/{app_id}/findings/{finding_id}/reviews", headers=assigned, json={"outcome": "needs_further_review", "note": "Inspect original"})
    second = client.post(f"/api/applications/{app_id}/findings/{finding_id}/reviews", headers=assigned, json={"outcome": "confirmed_issue", "note": "Evidence confirmed"})
    assert rejected.status_code == 403
    assert first.status_code == second.status_code == 201
    with test_database() as db:
        assert db.query(FindingReview).filter_by(finding_id=finding_id).count() == 2
        original = db.query(Finding).filter_by(id=finding_id).one()
        assert original.status == "open"
        assert db.query(AuditEvent).filter_by(action="finding.review_recorded", entity_id=str(finding_id)).count() == 2
    listed = client.get(f"/api/applications/{app_id}/findings", headers=assigned)
    assert [review["outcome"] for review in listed.json()[0]["reviews"]] == ["needs_further_review", "confirmed_issue"]


def test_integrity_preview_reports_pdf_metadata_as_user_controlled(test_database):
    institution_id = create_institution(test_database, "Metadata institution")
    create_user(test_database, "metadata@example.com", UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, "METADATA-1", institution_id)
    headers = login("metadata@example.com")
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Synthetic test PDF with enough content to parse safely.")
    pdf.set_metadata({"author": "Example User", "title": "Synthetic only"})
    content = pdf.tobytes()
    pdf.close()
    uploaded = upload(application_id, headers, content=content)
    assert uploaded.status_code == 201

    response = inspect_integrity(application_id, uploaded.json()["id"], headers)

    assert response.status_code == 200
    result = response.json()
    assert result["pdf_structure_check"]["status"] == "readable"
    assert result["metadata_check"]["status"] == "present"
    assert "user-controlled" in result["metadata_check"]["explanation"]


def test_integrity_check_persists_audit_event(test_database):
    institution_id = create_institution(test_database, "Integrity audit institution")
    create_user(test_database, "integrity-audit@example.com", UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, "INTEGRITY-AUDIT", institution_id)
    headers = login("integrity-audit@example.com")
    uploaded = upload(application_id, headers)
    assert uploaded.status_code == 201
    response = client.post(
        f"/api/applications/{application_id}/documents/{uploaded.json()['id']}/integrity-check",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["authenticity_status"] == "not_assessed"
    with test_database() as db:
        event = db.query(AuditEvent).filter_by(action="document.integrity_checked").one()
        assert event.entity_id == str(uploaded.json()["id"])


def test_integrity_preview_denies_unauthorized_application_and_document(test_database):
    own_institution = create_institution(test_database, "Integrity own institution")
    other_institution = create_institution(test_database, "Integrity other institution")
    create_user(test_database, "integrity-owner@example.com", UserRole.INSTITUTION_USER, own_institution)
    create_user(test_database, "integrity-other@example.com", UserRole.INSTITUTION_USER, other_institution)
    own_application = create_application(test_database, "INTEGRITY-OWN", own_institution)
    other_application = create_application(test_database, "INTEGRITY-OTHER", other_institution)
    owner_headers = login("integrity-owner@example.com")
    other_headers = login("integrity-other@example.com")
    foreign_document = upload(other_application, other_headers).json()["id"]

    assert inspect_integrity(other_application, foreign_document, owner_headers).status_code == 404
    assert inspect_integrity(own_application, foreign_document, owner_headers).status_code == 404
    assert inspect_integrity(own_application, 99999, owner_headers).status_code == 404
    assert inspect_integrity(own_application, 1, {}).status_code == 401


def test_non_pdf_rejected(test_database):
    institution_id = create_institution(test_database, "PDF institution")
    create_user(test_database, "pdf-user@example.com", UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, "PDF-1", institution_id)

    response = upload(application_id, login("pdf-user@example.com"), content=b"not a PDF")

    assert response.status_code == 415
    assert list(settings.DOCUMENT_STORAGE_DIR.iterdir()) == []


def test_oversized_pdf_rejected(test_database, monkeypatch):
    institution_id = create_institution(test_database, "Size institution")
    create_user(test_database, "size-user@example.com", UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, "SIZE-1", institution_id)
    monkeypatch.setattr(settings, "DOCUMENT_MAX_SIZE_BYTES", 16)

    response = upload(application_id, login("size-user@example.com"))

    assert response.status_code == 413
    assert list(settings.DOCUMENT_STORAGE_DIR.iterdir()) == []


def test_upload_requires_valid_authentication(test_database):
    institution_id = create_institution(test_database, "Auth institution")
    application_id = create_application(test_database, "AUTH-1", institution_id)

    missing = upload(application_id, {})
    invalid = upload(application_id, {"Authorization": "Bearer invalid"})
    unauthenticated_listing = client.get(f"/api/applications/{application_id}/documents")
    unauthenticated_download = client.get(
        f"/api/applications/{application_id}/documents/1/download"
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert unauthenticated_listing.status_code == 401
    assert unauthenticated_download.status_code == 401


def test_upload_to_missing_application_returns_404(test_database):
    create_user(test_database, "missing-app@example.com", UserRole.ADMIN)

    response = upload(987654, login("missing-app@example.com"))

    assert response.status_code == 404


def test_institution_user_cannot_upload_to_other_institution(test_database):
    own_institution = create_institution(test_database, "Own institution")
    other_institution = create_institution(test_database, "Other institution")
    create_user(test_database, "isolated@example.com", UserRole.INSTITUTION_USER, own_institution)
    other_application = create_application(test_database, "OTHER-1", other_institution)

    response = upload(other_application, login("isolated@example.com"))

    assert response.status_code == 404
    assert not settings.DOCUMENT_STORAGE_DIR.exists()


def test_unassigned_institution_user_cannot_access_unowned_application(test_database):
    create_user(test_database, "unassigned@example.com", UserRole.INSTITUTION_USER)
    unowned_application = create_application(test_database, "UNOWNED-1")

    response = upload(unowned_application, login("unassigned@example.com"))

    assert response.status_code == 404
    assert not settings.DOCUMENT_STORAGE_DIR.exists()


def test_document_listing_is_scoped_to_authorized_application(test_database):
    own_institution = create_institution(test_database, "Listing institution")
    other_institution = create_institution(test_database, "Hidden institution")
    create_user(test_database, "list-user@example.com", UserRole.INSTITUTION_USER, own_institution)
    own_application = create_application(test_database, "LIST-OWN", own_institution)
    other_application = create_application(test_database, "LIST-OTHER", other_institution)
    headers = login("list-user@example.com")
    uploaded = upload(own_application, headers)
    assert uploaded.status_code == 201

    own_listing = client.get(f"/api/applications/{own_application}/documents", headers=headers)
    other_listing = client.get(f"/api/applications/{other_application}/documents", headers=headers)

    assert own_listing.status_code == 200
    assert [item["id"] for item in own_listing.json()] == [uploaded.json()["id"]]
    assert other_listing.status_code == 404


def test_reviewer_access_requires_application_assignment(test_database):
    create_user(test_database, "reviewer@example.com", UserRole.REVIEWER)
    assigned_reviewer_id = create_user(test_database, "assigned@example.com", UserRole.REVIEWER)
    application_id = create_application(test_database, "REVIEW-1")
    rule = ComplianceRule(
        rule_code="DOC-TEST",
        title="Document test",
        description="Test reviewer assignment",
        category="test",
        is_active=True,
    )
    with test_database() as db:
        db.add(rule)
        db.flush()
        db.add(
            ComplianceAssessment(
                application_id=application_id,
                rule_id=rule.id,
                reviewer_id=assigned_reviewer_id,
                status="pending",
                explanation="",
            )
        )
        db.commit()

    assigned_response = client.get(
        f"/api/applications/{application_id}/documents",
        headers=login("assigned@example.com"),
    )
    unassigned_response = client.get(
        f"/api/applications/{application_id}/documents",
        headers=login("reviewer@example.com"),
    )

    assert assigned_response.status_code == 200
    assert unassigned_response.status_code == 403


def test_admin_can_list_any_application_documents(test_database):
    institution_id = create_institution(test_database, "Admin institution")
    create_user(test_database, "admin@example.com", UserRole.ADMIN)
    application_id = create_application(test_database, "ADMIN-1", institution_id)
    assert upload(application_id, login("admin@example.com")).status_code == 201

    response = client.get(
        f"/api/applications/{application_id}/documents",
        headers=login("admin@example.com"),
    )

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_download_authorizes_application_and_serves_pdf(test_database):
    institution_id = create_institution(test_database, "Download institution")
    other_institution = create_institution(test_database, "Other download institution")
    create_user(test_database, "download-user@example.com", UserRole.INSTITUTION_USER, institution_id)
    own_application = create_application(test_database, "DOWNLOAD-OWN", institution_id)
    other_application = create_application(test_database, "DOWNLOAD-OTHER", other_institution)
    headers = login("download-user@example.com")
    uploaded = upload(own_application, headers)
    document_id = uploaded.json()["id"]

    allowed = client.get(
        f"/api/applications/{own_application}/documents/{document_id}/download",
        headers=headers,
    )
    denied = client.get(
        f"/api/applications/{other_application}/documents/{document_id}/download",
        headers=headers,
    )

    assert allowed.status_code == 200
    assert allowed.content == PDF_CONTENT
    assert denied.status_code == 404


def test_upload_failure_cleans_up_stored_file(test_database, monkeypatch):
    institution_id = create_institution(test_database, "Failure institution")
    create_user(test_database, "failure-user@example.com", UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, "FAIL-1", institution_id)
    headers = login("failure-user@example.com")

    def fail_commit(_self):
        raise SQLAlchemyError("simulated persistence failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = upload(application_id, headers)

    assert response.status_code == 500
    assert list(settings.DOCUMENT_STORAGE_DIR.iterdir()) == []


def test_process_text_pdf_extracts_fields_with_page_evidence(test_database):
    institution_id = create_institution(test_database, "Processing institution")
    create_user(test_database, "processor@example.com", UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, "PROCESS-1", institution_id)
    pdf = make_text_pdf(
        "Institution Name: Northern Research Institute\n"
        "Certificate No: NR-2026-0042\n"
        "Issue Date: 2026-02-14\n"
        "Expiry Date: 2028-02-14"
    )
    uploaded = upload(application_id, login("processor@example.com"), content=pdf)
    assert uploaded.status_code == 201

    response = process(application_id, uploaded.json()["id"], login("processor@example.com"))

    assert response.status_code == 200
    result = response.json()
    assert result["processing_status"] == "completed"
    assert result["extraction_method"] == "text"
    assert result["fields"]["institution_name"]["value"] == "Northern Research Institute"
    assert result["fields"]["institution_name"]["page"] == 1
    assert "Institution Name:" in result["fields"]["institution_name"]["evidence"]
    assert result["fields"]["certificate_number"]["value"] == "NR-2026-0042"
    assert result["fields"]["issue_date"]["value"] == "2026-02-14"
    assert result["fields"]["expiry_date"]["value"] == "2028-02-14"
    assert result["fields"]["issue_date"]["confidence"] is None

    with test_database() as db:
        document = db.query(Document).filter_by(id=uploaded.json()["id"]).one()
        assert document.processing_status == "completed"
        assert document.processing_result["fields"]["certificate_number"]["page"] == 1
        assert document.processed_at is not None
        audit = db.query(AuditEvent).filter_by(
            action="document.processed",
            entity_id=str(document.id),
        ).one()
        assert "pages_processed" in audit.audit_metadata

    audit_history = client.get("/api/audit-events/", headers=login("processor@example.com"))
    assert audit_history.status_code == 200
    actions = {event["action"] for event in audit_history.json()["items"]}
    assert {"document.uploaded", "document.processed"}.issubset(actions)

    persisted = client.get(
        f"/api/applications/{application_id}/documents/{uploaded.json()['id']}/processing-result",
        headers=login("processor@example.com"),
    )
    assert persisted.status_code == 200
    assert persisted.json()["fields"] == result["fields"]


def test_document_classification_uses_content_and_keeps_uncertain_type_unclassified(test_database):
    institution_id = create_institution(test_database, "Classification institution")
    create_user(test_database, "classifier@example.com", UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, "CLASSIFY-1", institution_id)
    headers = login("classifier@example.com")

    certificate = upload(
        application_id,
        headers,
        content=make_text_pdf("Fire Safety Certificate\nIssued by Fire Department"),
    )
    assert certificate.status_code == 201
    classified = process(application_id, certificate.json()["id"], headers)
    assert classified.status_code == 200, classified.text
    result = classified.json()["classification"]
    assert result["status"] == "classified"
    assert result["candidate_document_type"] == "fire_safety_certificate"
    assert result["match_strength"] == "strong"
    assert {item["signal"] for item in result["evidence"]} >= {
        "fire safety certificate",
        "fire department",
    }
    assert "type suggestion only" in result["explanation"]

    generic = upload(application_id, headers, content=make_text_pdf("General records and correspondence"))
    assert generic.status_code == 201
    uncertain = process(application_id, generic.json()["id"], headers)
    assert uncertain.status_code == 200, uncertain.text
    uncertain_result = uncertain.json()["classification"]
    assert uncertain_result["status"] == "needs_review"
    assert uncertain_result["candidate_document_type"] is None
    assert uncertain_result["match_strength"] == "none"


def test_checklist_flags_expired_date_as_advisory_and_rejects_ambiguous_dates(test_database):
    institution_id = create_institution(test_database, "Expiry institution")
    create_user(test_database, "expiry@example.com", UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, "EXPIRY-1", institution_id)
    with test_database() as db:
        app_obj = db.query(Application).filter_by(id=application_id).one()
        app_obj.app_type = "Standard Regulatory"
        db.add(Document(
            application_id=application_id,
            doc_type="fire_safety_certificate",
            original_filename="certificate.pdf",
            storage_key="certificate.pdf",
            processing_status="completed",
            processing_result={
                "extraction_method": "text",
                "fields": {
                    "institution_name": {"value": "Test Entity"},
                    "certificate_number": {"value": "FSC-001"},
                    "expiry_date": {"value": "2000-01-01", "evidence": "Expiry Date: 2000-01-01"},
                },
            },
        ))
        db.commit()

    response = client.post(
        f"/api/applications/{application_id}/validate-checklist",
        headers=login("expiry@example.com"),
    )
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["status"] == "expired_document"
    assert "advisory" in item["explanation"]
    with test_database() as db:
        finding = db.query(Finding).filter_by(
            application_id=application_id,
            finding_type="Checklist expiry review",
        ).one()
        assert finding.severity == "Medium"
        assert "not a legal determination" in finding.description

    assert parse_unambiguous_date("2025-12-31").isoformat() == "2025-12-31"
    assert parse_unambiguous_date("15/02/2025").isoformat() == "2025-02-15"
    assert parse_unambiguous_date("02/03/2025") is None
    assert parse_unambiguous_date("not-a-date") is None


def test_validation_preview_returns_separate_evidence_without_database_writes(test_database):
    application_id, document_id, headers = create_processed_document(
        test_database,
        "validation-preview@example.com",
        "VALIDATE-1",
        make_text_pdf(
            "Institution Name: Example Institute\n"
            "Certificate No: FS-2026-001"
        ),
    )
    engine = test_database.kw["bind"]
    statements = []

    def collect_statement(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", collect_statement)
    try:
        response = validate(application_id, document_id, headers)
    finally:
        event.remove(engine, "before_cursor_execute", collect_statement)

    assert response.status_code == 200
    result = response.json()
    assert result["application_id"] == application_id
    assert result["document_id"] == document_id
    assert result["application_scope_status"] == "unknown"
    assert result["overall_status"] == "unknown"
    assert result["document_evidence"]["processing_status"] == "completed"
    assert result["document_evidence"]["fields"]["institution_name"] == {
        "value": "Example Institute",
        "page": 1,
        "evidence": "Institution Name: Example Institute",
        "confidence": None,
        "status": "extracted",
        "verification_status": "unverified",
    }
    assert {rule["rule_id"] for rule in result["candidate_rules"]} == {
        "DOCUMENT-0004",
        "DOCUMENT-0012",
        "DOCUMENT-0021",
        "INFRASTRUCTURE-0002",
    }
    for candidate in result["candidate_rules"]:
        assert candidate["preview_approved"] is False
        assert candidate["eligibility"] == "unknown"
        assert candidate["source_mapping_review"]["status"] in {
            "verified",
            "needs_correction",
        }
        assert candidate["currentness_review"]["status"] == "not_reviewed"
        assert candidate["applicability_review"]["status"] == "unknown"
        assert candidate["evidence"]["source"]["printed_page"] > 0
        assert candidate["evidence"]["source"]["pdf_page"] > 0
    assert all(check["status"] == "unknown" for check in result["checks"])
    assert statements == []
    encoded = json.dumps(result).casefold()
    assert "authenticity" in encoded
    assert "compliance" in encoded
    assert not any(phrase in encoded for phrase in ('"authentic": true', '"compliant": true', '"fraud": true'))
    assert "expiry" in encoded


def test_validation_preview_requires_authentication(test_database):
    institution_id = create_institution(test_database, "Unauth validation institution")
    application_id = create_application(test_database, "VALIDATE-UNAUTH", institution_id)

    response = validate(application_id, 1, {})

    assert response.status_code == 401


def test_validation_preview_rejects_unprocessed_document(test_database):
    institution_id = create_institution(test_database, "Pending validation institution")
    create_user(test_database, "pending-validation@example.com", UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, "VALIDATE-PENDING", institution_id)
    headers = login("pending-validation@example.com")
    uploaded = upload(application_id, headers)

    response = validate(application_id, uploaded.json()["id"], headers)

    assert response.status_code == 409


def test_validation_preview_returns_not_found_for_missing_document(test_database):
    institution_id = create_institution(test_database, "Missing validation institution")
    create_user(test_database, "missing-validation@example.com", UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, "VALIDATE-MISSING", institution_id)

    response = validate(
        application_id,
        99999,
        login("missing-validation@example.com"),
    )

    assert response.status_code == 404


def test_validation_preview_denies_unauthorized_application_and_foreign_document(
    test_database,
):
    first_institution = create_institution(test_database, "First validation institution")
    second_institution = create_institution(test_database, "Second validation institution")
    create_user(
        test_database,
        "first-validation@example.com",
        UserRole.INSTITUTION_USER,
        first_institution,
    )
    create_user(
        test_database,
        "second-validation@example.com",
        UserRole.INSTITUTION_USER,
        second_institution,
    )
    first_application = create_application(
        test_database,
        "VALIDATE-FIRST",
        first_institution,
    )
    second_application = create_application(
        test_database,
        "VALIDATE-SECOND",
        second_institution,
    )
    first_headers = login("first-validation@example.com")
    second_headers = login("second-validation@example.com")
    first_document = upload(first_application, first_headers).json()["id"]
    second_document = upload(second_application, second_headers).json()["id"]

    unauthorized_application = validate(
        second_application,
        second_document,
        first_headers,
    )
    foreign_document = validate(
        first_application,
        second_document,
        first_headers,
    )

    assert unauthorized_application.status_code == 404
    assert foreign_document.status_code == 404


def test_validation_preview_marks_ocr_fields_unverified(test_database):
    application_id, document_id, headers = create_processed_document(
        test_database,
        "ocr-validation@example.com",
        "VALIDATE-OCR",
    )
    with test_database() as db:
        document = db.query(Document).filter_by(id=document_id).one()
        document.processing_result = {
            "processing_status": "completed",
            "extraction_method": "ocr",
            "pages_processed": 1,
            "fields": {
                "certificate_number": {
                    "value": "OCR-001",
                    "page": 1,
                    "evidence": "Certificate No: OCR-001",
                    "confidence": 0.94,
                    "status": "extracted",
                }
            },
            "warnings": [],
        }
        db.commit()

    response = validate(application_id, document_id, headers)

    assert response.status_code == 200
    result = response.json()
    evidence = result["document_evidence"]
    assert evidence["extraction_method"] == "ocr"
    assert evidence["fields"]["certificate_number"]["value"] == "OCR-001"
    assert evidence["fields"]["certificate_number"]["confidence"] == 0.94
    assert evidence["fields"]["certificate_number"]["verification_status"] == "unverified"
    assert not any(
        claim in json.dumps(result).casefold()
        for claim in ('"authentic": true', '"compliant": true', '"fraud": true')
    )


def test_completed_processing_results_are_cached(test_database, monkeypatch):
    institution_id = create_institution(test_database, "Cache institution")
    create_user(test_database, "cache-user@example.com", UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, "CACHE-1", institution_id)
    uploaded = upload(
        application_id,
        login("cache-user@example.com"),
        content=make_text_pdf("Institution Name: Cache Institute"),
    )
    headers = login("cache-user@example.com")
    first = process(application_id, uploaded.json()["id"], headers)

    def unexpected_second_processing(*_args, **_kwargs):
        pytest.fail("cached results should not be processed a second time")

    monkeypatch.setattr(application_routes, "process_pdf", unexpected_second_processing)
    second = process(application_id, uploaded.json()["id"], headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()


def test_concurrent_processing_request_returns_conflict(test_database):
    institution_id = create_institution(test_database, "Concurrent institution")
    create_user(test_database, "concurrent-user@example.com", UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, "CONCURRENT-1", institution_id)
    uploaded = upload(application_id, login("concurrent-user@example.com"))
    with test_database() as db:
        document = db.query(Document).filter_by(id=uploaded.json()["id"]).one()
        document.processing_status = "processing"
        db.commit()

    response = process(
        application_id,
        uploaded.json()["id"],
        login("concurrent-user@example.com"),
    )

    assert response.status_code == 409


def test_scanned_pdf_uses_ocr_and_returns_confidence(test_database, monkeypatch):
    institution_id = create_institution(test_database, "Scanned institution")
    create_user(test_database, "scanner@example.com", UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, "SCAN-1", institution_id)

    monkeypatch.setattr(document_processing.shutil, "which", lambda _: "tesseract")
    monkeypatch.setattr(
        document_processing,
        "_ocr_page",
        lambda *_args: ("Institution Name: Image Institute", 0.93),
    )
    uploaded = upload(application_id, login("scanner@example.com"), content=make_image_pdf())
    response = process(application_id, uploaded.json()["id"], login("scanner@example.com"))

    assert response.status_code == 200
    result = response.json()
    assert result["extraction_method"] == "ocr"
    assert result["fields"]["institution_name"]["value"] == "Image Institute"
    assert result["fields"]["institution_name"]["confidence"] == pytest.approx(0.93)


def test_ocr_output_preserves_line_boundaries(monkeypatch):
    pdf = fitz.open()
    pdf.new_page()
    ocr_data = {
        "text": ["Institution", "Name:", "Line Institute", "Certificate", "No:", "LN-23"],
        "conf": ["90", "92", "88", "91", "93", "89"],
        "block_num": [1, 1, 1, 1, 1, 1],
        "par_num": [1, 1, 1, 1, 1, 1],
        "line_num": [1, 1, 1, 2, 2, 2],
    }
    monkeypatch.setattr(
        document_processing.pytesseract,
        "image_to_data",
        lambda *_args, **_kwargs: ocr_data,
    )

    text, confidence = document_processing._ocr_page(pdf, 0, 5)

    pdf.close()
    assert text == "Institution Name: Line Institute\nCertificate No: LN-23"
    assert confidence == pytest.approx(0.905)


def test_image_only_pdf_reports_ocr_unavailable_without_inventing_fields(test_database, monkeypatch):
    institution_id = create_institution(test_database, "No OCR institution")
    create_user(test_database, "no-ocr@example.com", UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, "NO-OCR-1", institution_id)
    monkeypatch.setattr(document_processing.shutil, "which", lambda _: None)
    uploaded = upload(application_id, login("no-ocr@example.com"), content=make_image_pdf())

    response = process(application_id, uploaded.json()["id"], login("no-ocr@example.com"))

    assert response.status_code == 200
    result = response.json()
    assert result["processing_status"] == "ocr_unavailable"
    assert result["fields"]["institution_name"]["value"] is None
    assert result["fields"]["institution_name"]["status"] == "missing"
    assert any("Tesseract" in warning for warning in result["warnings"])


def test_empty_pdf_reports_missing_fields(test_database):
    institution_id = create_institution(test_database, "Empty text institution")
    create_user(test_database, "empty-text@example.com", UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, "EMPTY-TEXT-1", institution_id)
    uploaded = upload(application_id, login("empty-text@example.com"), content=make_blank_pdf())

    response = process(application_id, uploaded.json()["id"], login("empty-text@example.com"))

    assert response.status_code == 200
    result = response.json()
    assert result["processing_status"] == "ocr_unavailable"
    assert all(field["value"] is None for field in result["fields"].values())


def test_malformed_pdf_processing_returns_error_and_marks_failed(test_database):
    institution_id = create_institution(test_database, "Malformed institution")
    create_user(test_database, "malformed@example.com", UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, "MALFORMED-1", institution_id)
    malformed = b"%PDF-1.4\nthis is not a valid PDF structure\n%%EOF\n"
    uploaded = upload(application_id, login("malformed@example.com"), content=malformed)

    response = process(application_id, uploaded.json()["id"], login("malformed@example.com"))

    assert response.status_code == 422
    with test_database() as db:
        document = db.query(Document).filter_by(id=uploaded.json()["id"]).one()
        assert document.processing_status == "failed"
        assert "malformed" in document.processing_result["warnings"][0].lower()


def test_unauthorized_document_processing_is_denied(test_database):
    own_institution = create_institution(test_database, "Processor own institution")
    other_institution = create_institution(test_database, "Processor other institution")
    create_user(test_database, "owner@example.com", UserRole.INSTITUTION_USER, own_institution)
    create_user(test_database, "outsider@example.com", UserRole.INSTITUTION_USER, other_institution)
    application_id = create_application(test_database, "AUTH-PROCESS-1", own_institution)
    uploaded = upload(application_id, login("owner@example.com"))

    response = process(
        application_id,
        uploaded.json()["id"],
        login("outsider@example.com"),
    )

    assert response.status_code == 404
    with test_database() as db:
        document = db.query(Document).filter_by(id=uploaded.json()["id"]).one()
        assert document.processing_status == "pending"


def test_unauthenticated_document_processing_is_denied(test_database):
    institution_id = create_institution(test_database, "Unauthenticated institution")
    application_id = create_application(test_database, "UNAUTH-PROCESS-1", institution_id)
    create_user(test_database, "auth-owner@example.com", UserRole.ADMIN)
    uploaded = upload(application_id, login("auth-owner@example.com"))

    response = process(application_id, uploaded.json()["id"], {})

    assert response.status_code == 401


def test_processing_requires_reviewer_assignment(test_database):
    assigned_reviewer_id = create_user(test_database, "assigned-processor@example.com", UserRole.REVIEWER)
    create_user(test_database, "unassigned-processor@example.com", UserRole.REVIEWER)
    application_id = create_application(test_database, "REVIEW-PROCESS-1")
    rule = ComplianceRule(
        rule_code="PROCESS-TEST",
        title="Processing assignment",
        description="Assignment test",
        category="test",
        is_active=True,
    )
    with test_database() as db:
        db.add(rule)
        db.flush()
        db.add(
            ComplianceAssessment(
                application_id=application_id,
                rule_id=rule.id,
                reviewer_id=assigned_reviewer_id,
                status="pending",
                explanation="",
            )
        )
        db.commit()
    uploaded = upload(application_id, login("assigned-processor@example.com"))

    denied = process(
        application_id,
        uploaded.json()["id"],
        login("unassigned-processor@example.com"),
    )
    allowed = process(
        application_id,
        uploaded.json()["id"],
        login("assigned-processor@example.com"),
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200


def test_page_limit_and_processing_errors_are_handled(test_database, monkeypatch):
    institution_id = create_institution(test_database, "Limit institution")
    create_user(test_database, "limit-user@example.com", UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, "LIMIT-1", institution_id)
    uploaded = upload(application_id, login("limit-user@example.com"))
    monkeypatch.setattr(settings, "DOCUMENT_PROCESSING_MAX_PAGES", 0)

    response = process(application_id, uploaded.json()["id"], login("limit-user@example.com"))

    assert response.status_code == 422
    assert "processing limit" in response.json()["detail"]
    with test_database() as db:
        document = db.query(Document).filter_by(id=uploaded.json()["id"]).one()
        assert document.processing_status == "failed"


def test_ocr_page_rendering_size_is_limited(test_database, monkeypatch):
    institution_id = create_institution(test_database, "Render limit institution")
    create_user(test_database, "render-limit@example.com", UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, "RENDER-LIMIT-1", institution_id)
    pdf = fitz.open()
    pdf.new_page(width=20_000, height=20_000)
    oversized_page_pdf = pdf.tobytes()
    pdf.close()
    monkeypatch.setattr(document_processing.shutil, "which", lambda _: "tesseract")
    monkeypatch.setattr(
        document_processing,
        "_ocr_page",
        lambda *_args, **_kwargs: pytest.fail("oversized page should not be rendered"),
    )
    uploaded = upload(
        application_id,
        login("render-limit@example.com"),
        content=oversized_page_pdf,
    )

    response = process(
        application_id,
        uploaded.json()["id"],
        login("render-limit@example.com"),
    )

    assert response.status_code == 422
    assert "rendering size limit" in response.json()["detail"]


def test_unexpected_processing_error_is_persisted_safely(test_database, monkeypatch):
    institution_id = create_institution(test_database, "Error institution")
    create_user(test_database, "error-user@example.com", UserRole.INSTITUTION_USER, institution_id)
    application_id = create_application(test_database, "ERROR-1", institution_id)
    uploaded = upload(application_id, login("error-user@example.com"))

    def fail_processing(*_args, **_kwargs):
        raise document_processing.DocumentProcessingError("PDF could not be processed")

    monkeypatch.setattr(application_routes, "process_pdf", fail_processing)
    response = process(application_id, uploaded.json()["id"], login("error-user@example.com"))

    assert response.status_code == 422
    assert response.json()["detail"] == "PDF could not be processed"
    with test_database() as db:
        document = db.query(Document).filter_by(id=uploaded.json()["id"]).one()
        assert document.processing_status == "failed"
        assert document.processing_result["processing_status"] == "failed"
