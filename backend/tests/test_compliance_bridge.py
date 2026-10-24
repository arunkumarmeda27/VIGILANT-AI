import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db.base import Base
from app.core.security import get_password_hash
from app.models.enums import UserRole
from app.models.models import User, Application, Document, Institution, ComplianceAssessment, ComplianceRule, Finding
from app.db.session import get_db as real_get_db
from datetime import datetime, timedelta, timezone
from pathlib import Path
from app.api.routes import applications as application_routes
from app.services.regulatory_validation import load_registry

TEST_REGISTRY_PATH = (
    Path(__file__).parents[1]
    / "data"
    / "processed"
    / "regulatory_rules"
    / "fire_safety_preview_registry.json"
)

SQLALCHEMY_DATABASE_URL = "sqlite:///test_compliance_bridge.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

client = TestClient(app)

@pytest.fixture(scope="function", autouse=True)
def setup_db(monkeypatch):
    monkeypatch.setitem(app.dependency_overrides, real_get_db, override_get_db)
    monkeypatch.setattr(
        application_routes,
        "load_registry",
        lambda: load_registry(TEST_REGISTRY_PATH),
    )
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

def create_test_user(email="user@example.com", role=UserRole.INSTITUTION_USER, institution_id=None):
    session = TestingSessionLocal()
    user = User(
        full_name="Test User",
        email=email,
        password_hash=get_password_hash("password123"),
        role=role.value,
        is_active=True,
        institution_id=institution_id
    )
    session.add(user)
    session.commit()
    email_val = user.email
    session.close()
    return email_val

def get_token(email):
    resp = client.post(
        "/api/auth/login",
        json={"email": email, "password": "password123"}
    )
    return resp.json()["access_token"]

def create_institution(name="Test Institution"):
    session = TestingSessionLocal()
    inst = Institution(name=name)
    session.add(inst)
    session.commit()
    id_val = inst.id
    session.close()
    return id_val

def create_application(ref="REF001", app_type="Standard Regulatory", inst_id=None):
    session = TestingSessionLocal()
    app_obj = Application(
        reference=ref,
        entity_name="Test Entity",
        app_type=app_type,
        institution_id=inst_id
    )
    session.add(app_obj)
    session.commit()
    id_val = app_obj.id
    session.close()
    return id_val

def create_processed_document(app_id, doc_type, fields):
    session = TestingSessionLocal()
    doc = Document(
        application_id=app_id,
        doc_type=doc_type,
        original_filename="test.pdf",
        storage_key="test_key",
        processing_status="completed",
        processing_result={"fields": fields}
    )
    session.add(doc)
    session.commit()
    session.close()

def test_validate_all_success():
    inst_id = create_institution()
    user_email = create_test_user(institution_id=inst_id)
    token = get_token(user_email)
    app_id = create_application(inst_id=inst_id)

    create_processed_document(app_id, "fire_safety_certificate", {
        "certificate_number": {"value": "CERT123", "status": "extracted", "evidence": "Cert No: CERT123"},
        "expiry_date": {"value": (datetime.now(timezone.utc) + timedelta(days=365)).isoformat(), "status": "extracted", "evidence": "Expires: 2027-01-01"}
    })

    response = client.post(
        f"/api/applications/{app_id}/validate-all",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    # Check that FS-001 and FS-002 passed
    results = {r["rule_id"]: r["status"] for r in data["results"]}
    assert results["FS-001"] == "Compliant"
    assert results["FS-002"] == "Compliant"
    findings_response = client.get(
        f"/api/applications/{app_id}/findings",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert findings_response.status_code == 200
    assert isinstance(findings_response.json(), list)

    # Verify persistence
    session = TestingSessionLocal()
    assessments = session.query(ComplianceAssessment).filter(ComplianceAssessment.application_id == app_id).all()
    assert len(assessments) >= 2
    session.close()


def test_validate_all_preserves_preexisting_assessments():
    inst_id = create_institution()
    user_email = create_test_user(institution_id=inst_id)
    token = get_token(user_email)
    app_id = create_application(inst_id=inst_id)
    create_processed_document(app_id, "fire_safety_certificate", {
        "certificate_number": {"value": "CERT123", "status": "extracted"},
        "expiry_date": {"value": (datetime.now(timezone.utc) + timedelta(days=365)).isoformat(), "status": "extracted"},
    })

    session = TestingSessionLocal()
    rule = ComplianceRule(
        rule_code="EXISTING-REVIEW",
        title="Existing human review",
        description="Must remain preserved after another validation.",
        category="test",
    )
    session.add(rule)
    session.flush()
    assessment = ComplianceAssessment(
        application_id=app_id,
        rule_id=rule.id,
        status="Partial",
        explanation="Previously recorded reviewer assessment.",
    )
    session.add(assessment)
    session.commit()
    assessment_id = assessment.id
    session.close()

    response = client.post(
        f"/api/applications/{app_id}/validate-all",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    with TestingSessionLocal() as session:
        preserved = session.query(ComplianceAssessment).filter_by(id=assessment_id).one()
        assert preserved.status == "Partial"
        assert preserved.explanation == "Previously recorded reviewer assessment."

def test_validate_all_expired_certificate():
    inst_id = create_institution()
    user_email = create_test_user(institution_id=inst_id)
    token = get_token(user_email)
    app_id = create_application(inst_id=inst_id)

    create_processed_document(app_id, "fire_safety_certificate", {
        "certificate_number": {"value": "CERT123", "status": "extracted", "evidence": "Cert No: CERT123"},
        "expiry_date": {"value": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), "status": "extracted", "evidence": "Expired yesterday"}
    })

    response = client.post(
        f"/api/applications/{app_id}/validate-all",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    results = {r["rule_id"]: r["status"] for r in response.json()["results"]}
    assert results["FS-002"] == "Non-Compliant"

    # Verify finding creation
    session = TestingSessionLocal()
    finding = session.query(Finding).filter(Finding.application_id == app_id).first()
    assert finding is not None
    assert "Regulatory Violation" in finding.finding_type
    session.close()

def test_validate_all_missing_document():
    inst_id = create_institution()
    user_email = create_test_user(institution_id=inst_id)
    token = get_token(user_email)
    app_id = create_application(inst_id=inst_id)

    # No documents created
    response = client.post(
        f"/api/applications/{app_id}/validate-all",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 400
    assert "No processed documents" in response.json()["detail"]

def test_validate_all_unsupported_category():
    inst_id = create_institution()
    user_email = create_test_user(institution_id=inst_id)
    token = get_token(user_email)
    app_id = create_application(app_type="Unknown Category", inst_id=inst_id)

    create_processed_document(app_id, "fire_safety_certificate", {
        "certificate_number": {"value": "CERT123", "status": "extracted"}
    })

    response = client.post(
        f"/api/applications/{app_id}/validate-all",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    results = {r["rule_id"]: r["status"] for r in response.json()["results"]}
    # FS rules should be "Not evaluated" or similar because scope is unknown
    assert results["FS-001"] == "Not evaluated"

def test_validate_all_unauthorized():
    inst_id = create_institution()
    user_email = create_test_user(institution_id=inst_id)
    token = get_token(user_email)

    # Create application for another institution
    other_inst_id = create_institution("Other Inst")
    app_id = create_application(inst_id=other_inst_id)

    response = client.post(
        f"/api/applications/{app_id}/validate-all",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404 # Isolation: return 404 for other inst apps
