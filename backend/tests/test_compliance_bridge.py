import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db.base import Base
from app.core.security import get_password_hash
from app.models.enums import UserRole
from app.models.models import User, Application, Document, Institution, ComplianceAssessment, ComplianceRule, Finding, AuditEvent, ComplianceAssessmentReview
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

def test_validate_all_keeps_unapproved_rules_unevaluated():
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
    # Extracted values alone do not establish scope or approve candidate rules.
    results = {r["rule_id"]: r["status"] for r in data["results"]}
    assert results["FS-001"] == "Not evaluated"
    assert results["FS-002"] == "Not evaluated"
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

def test_validate_all_does_not_label_expiry_as_violation_without_rule_approval():
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
    assert results["FS-002"] == "Not evaluated"

    # Verify finding creation
    session = TestingSessionLocal()
    finding = session.query(Finding).filter(Finding.application_id == app_id).first()
    assert finding is None
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


def test_not_evaluated_result_is_not_relabelled_not_applicable_or_failure(monkeypatch):
    inst_id = create_institution("Unknown result institution")
    user_email = create_test_user("unknown-result@example.com", institution_id=inst_id)
    token = get_token(user_email)
    app_id = create_application(app_type="Standard Regulatory", inst_id=inst_id)
    create_processed_document(app_id, "fire_safety_certificate", {
        "certificate_number": {"value": "CERT-UNKNOWN", "status": "extracted"}
    })
    monkeypatch.setattr(application_routes, "evaluate_preview_eligibility", lambda *_args: "eligible_for_preview")
    monkeypatch.setattr(application_routes, "evaluate_rule_result", lambda *_args: {
        "status": "Not evaluated", "explanation": "Insufficient source evidence.", "evidence": None,
    })

    response = client.post(
        f"/api/applications/{app_id}/validate-all",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert all(item["status"] == "Not evaluated" for item in response.json()["results"])
    with TestingSessionLocal() as session:
        assert session.query(Finding).filter_by(application_id=app_id).count() == 0


def test_assessment_assignment_and_append_only_review_are_authorized_and_audited():
    institution_id = create_institution("Assessment review institution")
    owner_email = create_test_user("assessment-owner@example.com", institution_id=institution_id)
    foreign_institution_id = create_institution("Foreign assessment review institution")
    foreign_owner_email = create_test_user("assessment-foreign@example.com", institution_id=foreign_institution_id)
    reviewer_email = create_test_user("assessment-reviewer@example.com", UserRole.REVIEWER)
    other_reviewer_email = create_test_user("assessment-other@example.com", UserRole.REVIEWER)
    admin_email = create_test_user("assessment-admin@example.com", UserRole.ADMIN)
    app_id = create_application("ASSESSMENT-REVIEW", "Standard Regulatory", institution_id)
    with TestingSessionLocal() as session:
        rule = ComplianceRule(rule_code="ASSESSMENT-REVIEW", title="Synthetic review", description="Synthetic test rule", category="test")
        session.add(rule)
        session.flush()
        assessment = ComplianceAssessment(application_id=app_id, rule_id=rule.id, status="Not evaluated", explanation="Scope is unknown.")
        session.add(assessment)
        session.flush()
        assessment_id = assessment.id
        session.add(Document(
            application_id=app_id, doc_type="fire_safety_certificate", original_filename="review.pdf",
            storage_key="review.pdf", processing_status="completed",
            processing_result={"extraction_method": "text", "fields": {"certificate_number": {"value": "CERT-1", "evidence": "Certificate No: CERT-1", "page": 1}}},
        ))
        session.commit()

    with TestingSessionLocal() as session:
        reviewer_id = session.query(User).filter_by(email=reviewer_email).one().id
    assign_url = f"/api/compliance-assessments/{assessment_id}/assignment"
    assert client.post(assign_url, headers={"Authorization": f"Bearer {get_token(owner_email)}"}, json={"reviewer_id": reviewer_id}).status_code == 403
    assigned = client.post(assign_url, headers={"Authorization": f"Bearer {get_token(admin_email)}"}, json={"reviewer_id": reviewer_id})
    assert assigned.status_code == 200, assigned.text

    detail_url = f"/api/compliance-assessments/{assessment_id}"
    reviewer_headers = {"Authorization": f"Bearer {get_token(reviewer_email)}"}
    other_headers = {"Authorization": f"Bearer {get_token(other_reviewer_email)}"}
    detail = client.get(detail_url, headers=reviewer_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "Not evaluated"
    assert detail.json()["document_evidence"][0]["fields"]["certificate_number"]["evidence"] == "Certificate No: CERT-1"
    assert client.get(detail_url, headers=other_headers).status_code == 404
    owner_headers = {"Authorization": f"Bearer {get_token(owner_email)}"}
    foreign_owner_headers = {"Authorization": f"Bearer {get_token(foreign_owner_email)}"}
    assert client.get(detail_url, headers=owner_headers).status_code == 200
    assert client.get(detail_url, headers=foreign_owner_headers).status_code == 404

    review_url = f"/api/compliance-assessments/{assessment_id}/reviews"
    # The API intentionally hides assessments not assigned to this reviewer.
    assert client.post(review_url, headers=other_headers, json={"outcome": "evidence_accepted", "note": "not assigned"}).status_code == 404
    assert client.post(review_url, headers=owner_headers, json={"outcome": "evidence_accepted", "note": "not a reviewer"}).status_code == 403
    decision1 = client.post(review_url, headers=reviewer_headers, json={"outcome": "information_requested", "note": "Please provide a legible source."})
    decision2 = client.post(review_url, headers=reviewer_headers, json={"outcome": "further_investigation", "note": "Check issuer manually."})
    assert decision1.status_code == decision2.status_code == 201
    audit = client.get(f"/api/audit-events/?application_id={app_id}&limit=100", headers=reviewer_headers)
    assert audit.status_code == 200
    assert {event["action"] for event in audit.json()["items"]} >= {
        "compliance_assessment.reviewer_assigned",
        "compliance_assessment.review_recorded",
    }
    assert client.get(f"/api/audit-events/?application_id={app_id}", headers=foreign_owner_headers).status_code == 404
    with TestingSessionLocal() as session:
        assert session.query(ComplianceAssessmentReview).filter_by(assessment_id=assessment_id).count() == 2
        assert session.query(ComplianceAssessment).filter_by(id=assessment_id).one().status == "Not evaluated"
        assert session.query(AuditEvent).filter_by(action="compliance_assessment.reviewer_assigned").count() == 1
        assert session.query(AuditEvent).filter_by(action="compliance_assessment.review_recorded").count() == 2


def test_assessment_pagination_and_application_filter_use_actual_totals():
    admin_email = create_test_user("assessment-pages-admin@example.com", UserRole.ADMIN)
    inst_id = create_institution("Assessment pages institution")
    app_id = create_application("ASSESSMENT-PAGES", "Standard Regulatory", inst_id)
    with TestingSessionLocal() as session:
        for index in range(3):
            rule = ComplianceRule(
                rule_code=f"PAGE-RULE-{index}", title=f"Page rule {index}",
                description="Test pagination", category="test",
            )
            session.add(rule)
            session.flush()
            session.add(ComplianceAssessment(
                application_id=app_id, rule_id=rule.id,
                status="Not evaluated", explanation="Scope unknown.",
            ))
        session.commit()

    headers = {"Authorization": f"Bearer {get_token(admin_email)}"}
    first = client.get("/api/compliance-assessments/?limit=2&offset=0", headers=headers)
    second = client.get("/api/compliance-assessments/?limit=2&offset=2", headers=headers)
    filtered = client.get(f"/api/compliance-assessments/?application_id={app_id}&limit=200", headers=headers)
    assert first.status_code == second.status_code == filtered.status_code == 200
    assert len(first.json()["items"]) == 2 and first.json()["total"] == 3
    assert len(second.json()["items"]) == 1 and second.json()["total"] == 3
    assert len(filtered.json()["items"]) == 3 and filtered.json()["total"] == 3

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
