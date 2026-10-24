import hashlib
from io import BytesIO

import fitz
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import create_engine
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
    ComplianceAssessment,
    ComplianceRule,
    Document,
    Institution,
    User,
)
from app.services import document_processing
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
    app.dependency_overrides[real_get_db] = override_get_db
    Base.metadata.create_all(bind=engine)
    yield testing_session_local
    app.dependency_overrides.pop(real_get_db, None)
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
