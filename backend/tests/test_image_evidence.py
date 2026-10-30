from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.security import get_password_hash
from app.db.base import Base
from app.db.session import get_db as real_get_db
from app.main import app
from app.models.enums import UserRole
from app.models.models import Application, AuditEvent, ImageEvidence, Institution, User, ValidationRun


client = TestClient(app)


@pytest.fixture
def image_database(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = testing_sessions()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(settings, "DOCUMENT_STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setitem(app.dependency_overrides, real_get_db, override_get_db)
    Base.metadata.create_all(bind=engine)
    yield testing_sessions
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _image_bytes(*, dark: bool = False) -> bytes:
    image = Image.new("RGB", (320, 240), (15, 15, 15) if dark else "white")
    if not dark:
        draw = ImageDraw.Draw(image)
        draw.rectangle((30, 30, 280, 210), outline="black", width=4)
        draw.line((30, 120, 280, 120), fill="black", width=3)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _user_and_application(testing_sessions, email: str, *, institution_name: str) -> int:
    with testing_sessions() as db:
        institution = Institution(name=institution_name)
        db.add(institution)
        db.flush()
        db.add(User(
            full_name=email,
            email=email,
            password_hash=get_password_hash("synthetic-test-password"),
            role=UserRole.INSTITUTION_USER.value,
            is_active=True,
            institution_id=institution.id,
        ))
        application = Application(
            reference=f"IMG-{institution.id}",
            entity_name="Synthetic Image Test",
            app_type="Synthetic",
            status="submitted",
            institution_id=institution.id,
        )
        db.add(application)
        db.commit()
        return application.id


def _headers(email: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "synthetic-test-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _upload(application_id: int, headers: dict[str, str], content: bytes | None = None):
    return client.post(
        f"/api/applications/{application_id}/image-evidence",
        headers=headers,
        files={"file": ("facility.png", content or _image_bytes(), "image/png")},
    )


def test_image_quality_assessment_persists_hash_and_evidence_history(image_database):
    application_id = _user_and_application(
        image_database,
        "image-quality@example.com",
        institution_name="Image Quality Institution",
    )
    headers = _headers("image-quality@example.com")

    uploaded = _upload(application_id, headers)

    assert uploaded.status_code == 201, uploaded.text
    record = uploaded.json()
    assert record["processing_status"] == "quality_reviewable"
    assert record["content_type"] == "image/png"
    assert record["file_size"] > 0
    assert len(record["sha256"]) == 64
    assert record["analysis_result"]["task"] == "image_quality_assessment"
    assert record["analysis_result"]["analysis_version"] == "deterministic-image-quality-v1"
    assert record["analysis_result"]["dimensions"] == {"width": 320, "height": 240}
    assert "mean_grayscale_brightness_0_255" in record["analysis_result"]["metrics"]
    assert record["analysis_result"]["human_review_required"] is True
    assert record["analysis_result"]["model"] is None

    history = client.get(
        f"/api/applications/{application_id}/image-evidence",
        headers=headers,
    )
    assert history.status_code == 200
    assert history.json()[0]["id"] == record["id"]

    source = client.get(
        f"/api/applications/{application_id}/image-evidence/{record['id']}/file",
        headers=headers,
    )
    assert source.status_code == 200
    assert source.content == _image_bytes()

    with image_database() as db:
        saved = db.query(ImageEvidence).filter_by(id=record["id"]).one()
        audit = db.query(AuditEvent).filter_by(
            action="image_evidence.quality_assessed",
            entity_id=str(record["id"]),
        ).one()
        assert saved.analysis_result == record["analysis_result"]
        assert audit.user_id is not None
        assert record["sha256"] not in audit.audit_metadata


def test_quality_limited_image_has_explainable_warnings_without_fake_detection(image_database):
    application_id = _user_and_application(
        image_database,
        "image-dark@example.com",
        institution_name="Dark Image Institution",
    )
    headers = _headers("image-dark@example.com")

    uploaded = _upload(application_id, headers, _image_bytes(dark=True))

    assert uploaded.status_code == 201, uploaded.text
    result = uploaded.json()
    assert result["processing_status"] == "quality_limited"
    assert "image_is_very_dark" in result["analysis_result"]["warnings"]
    assert result["analysis_result"]["model"] is None
    assert result["analysis_result"]["human_review_required"] is True


@pytest.mark.parametrize(
    ("filename", "content_type", "content", "expected_status"),
    [
        ("bad.gif", "image/gif", b"not an image", 415),
        ("bad.png", "image/png", b"not an image", 415),
        ("wrong-extension.jpg", "image/jpeg", _image_bytes(), 415),
        ("empty.png", "image/png", b"", 415),
    ],
)
def test_image_upload_rejects_malformed_or_unsupported_images(
    image_database,
    filename,
    content_type,
    content,
    expected_status,
):
    application_id = _user_and_application(
        image_database,
        "image-invalid@example.com",
        institution_name="Invalid Image Institution",
    )
    headers = _headers("image-invalid@example.com")

    response = client.post(
        f"/api/applications/{application_id}/image-evidence",
        headers=headers,
        files={"file": (filename, content, content_type)},
    )

    assert response.status_code == expected_status
    assert client.get(
        f"/api/applications/{application_id}/image-evidence",
        headers=headers,
    ).json() == []


def test_image_evidence_is_authorized_and_linked_to_validation_history(image_database):
    own_application_id = _user_and_application(
        image_database,
        "image-owner@example.com",
        institution_name="Image Owner Institution",
    )
    other_application_id = _user_and_application(
        image_database,
        "image-outsider@example.com",
        institution_name="Image Outsider Institution",
    )
    owner_headers = _headers("image-owner@example.com")
    outsider_headers = _headers("image-outsider@example.com")
    uploaded = _upload(own_application_id, owner_headers)
    assert uploaded.status_code == 201
    evidence_id = uploaded.json()["id"]

    assert client.get(
        f"/api/applications/{own_application_id}/image-evidence",
        headers=outsider_headers,
    ).status_code == 404
    assert client.get(
        f"/api/applications/{other_application_id}/image-evidence/{evidence_id}/file",
        headers=owner_headers,
    ).status_code == 404
    assert client.get(
        f"/api/applications/{own_application_id}/image-evidence",
    ).status_code == 401

    validation = client.post(
        f"/api/applications/{own_application_id}/validate-all",
        headers=owner_headers,
    )
    assert validation.status_code == 200, validation.text
    run_id = validation.json()["run_id"]

    with image_database() as db:
        evidence = db.query(ImageEvidence).filter_by(id=evidence_id).one()
        run = db.query(ValidationRun).filter_by(id=run_id).one()
        assert evidence.validation_run_id == run.id
        stage = next(
            item for item in run.stage_outcomes
            if item["name"] == "infrastructure_image_quality"
        )
        assert stage["result_count"] == 1
        result = next(
            item for item in run.results
            if item["type"] == "infrastructure_image_quality"
        )
        assert result["image_evidence_id"] == evidence_id
        assert result["sha256"] == evidence.sha256
        assert "does not identify infrastructure objects" in result["limitation"]
