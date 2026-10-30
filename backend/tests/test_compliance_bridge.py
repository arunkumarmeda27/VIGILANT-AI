import hashlib
import json

import fitz
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session as SQLAlchemySession, sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from app.main import app
from app.db.base import Base
from app.core.security import get_password_hash
from app.models.enums import UserRole
from app.models.models import User, Application, Document, Institution, ComplianceAssessment, ComplianceRule, Finding, AuditEvent, ComplianceAssessmentReview, ComplianceAssessmentStatusHistory, ValidationRun, ConsistencyRun, DocumentConsistencyResult
from app.db.session import get_db as real_get_db
from datetime import datetime, timedelta, timezone
from pathlib import Path
from app.api.routes import applications as application_routes
from app.services.regulatory_validation import RegistryValidationError, load_registry

TEST_REGISTRY_PATH = (
    Path(__file__).parents[2]
    / "data"
    / "processed"
    / "regulatory_rules"
    / "fire_safety_preview_registry.json"
)

SQLALCHEMY_DATABASE_URL = "sqlite://"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
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
    assert data["execution_status"] == "partial"
    assert any(
        stage["name"] == "document_classification"
        and stage["status"] == "unavailable"
        for stage in data["stages"]
    )
    assert data["status"] == "inconclusive"
    assert data["evaluated_rules_count"] == 0
    regulatory_results = [result for result in data["results"] if result["type"] == "regulatory_rule"]
    assert data["not_evaluated_rules_count"] == len(regulatory_results)
    assert {result["reason_code"] for result in regulatory_results} == {"rule_unapproved"}
    assert {
        result["rule_reference"]["preview_status"]
        for result in regulatory_results
    } == {"not_approved_for_preview"}
    findings_response = client.get(
        f"/api/applications/{app_id}/findings",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert findings_response.status_code == 200
    assert isinstance(findings_response.json(), list)

    # Verify persistence
    with TestingSessionLocal() as session:
        assessments = (
            session.query(ComplianceAssessment, ComplianceRule.rule_code)
            .join(ComplianceRule)
            .filter(ComplianceAssessment.application_id == app_id)
            .all()
        )
        persisted = {
            rule_code: (assessment.status, assessment.explanation)
            for assessment, rule_code in assessments
        }
        returned = {
            result["rule_id"]: (result["status"], result["explanation"])
            for result in data["results"]
            if result["type"] == "regulatory_rule"
        }
        assert persisted == returned


def test_validation_run_preserves_blank_and_unreadable_page_metadata():
    inst_id = create_institution("Page metadata institution")
    user_email = create_test_user("page-metadata@example.com", institution_id=inst_id)
    token = get_token(user_email)
    app_id = create_application(inst_id=inst_id)
    create_processed_document(app_id, "supporting_document", {})
    with TestingSessionLocal() as session:
        document = session.query(Document).filter_by(application_id=app_id).one()
        document.processing_status = "partial"
        document.processing_result = {
            "processing_status": "partial",
            "extraction_method": "ocr",
            "unreadable_pages": [1],
            "blank_pages": [2],
            "fields": {},
            "warnings": ["OCR failed on page 1; manual review is required."],
        }
        session.commit()

    response = client.post(
        f"/api/applications/{app_id}/validate-all",
        headers={"Authorization": "Bearer " + token},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    intelligence = next(
        result
        for result in data["results"]
        if result.get("type") == "document_intelligence"
    )
    assert intelligence["blank_pages"] == [2]
    assert intelligence["unreadable_pages"] == [1]
    with TestingSessionLocal() as session:
        run = session.query(ValidationRun).filter_by(id=data["run_id"]).one()
        persisted = next(
            result
            for result in run.results
            if result.get("type") == "document_intelligence"
        )
        assert persisted == intelligence
        run = session.query(ValidationRun).filter_by(id=data["run_id"]).one()
        assert run.application_id == app_id
        assert run.user_id is not None
        assert run.outcome == data["status"]
        assert run.results == data["results"]
        assert run.stage_outcomes == data["stages"]
        assert session.query(ValidationRun).filter_by(application_id=app_id).count() == 1
        assert len(run.assessments) == len(data["results"]) - sum(
            result.get("type") != "regulatory_rule" for result in data["results"]
        )
        audit_event = session.query(AuditEvent).filter_by(
            action="application.validate_all",
            entity_id=str(app_id),
        ).one()
        assert json.loads(audit_event.audit_metadata)["validation_status"] == data["status"]

def test_repeated_validation_preserves_one_identical_snapshot_and_audit_history():
    institution_id = create_institution()
    user_email = create_test_user("repeat-validation@example.com", institution_id=institution_id)
    token = get_token(user_email)
    application_id = create_application(inst_id=institution_id)
    create_processed_document(application_id, "fire_safety_certificate", {
        "certificate_number": {"value": "CERT-REPEAT", "status": "extracted"},
    })
    headers = {"Authorization": f"Bearer {token}"}
    url = f"/api/applications/{application_id}/validate-all"

    first = client.post(url, headers=headers)
    assert first.status_code == 200
    assert first.json()["status"] == "inconclusive"
    with TestingSessionLocal() as session:
        first_snapshot_count = session.query(ComplianceAssessment).filter_by(
            application_id=application_id
        ).count()
        assert first_snapshot_count > 0

    second = client.post(url, headers=headers)
    assert second.status_code == 200
    assert second.json()["status"] == "inconclusive"
    assert first.json()["run_id"] != second.json()["run_id"]
    with TestingSessionLocal() as session:
        assert session.query(ComplianceAssessment).filter_by(
            application_id=application_id
        ).count() == first_snapshot_count
        runs = session.query(ValidationRun).filter_by(application_id=application_id).all()
        assert len(runs) == 2
        assert all(run.assessments for run in runs)
        assert session.query(AuditEvent).filter_by(
            action="application.validate_all", entity_id=str(application_id)
        ).count() == 2


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
    assert response.json()["status"] == "inconclusive"
    assert all(
        result["status"] == "Not evaluated"
        for result in response.json()["results"]
        if result["type"] == "regulatory_rule"
    )

    # Verify finding creation
    session = TestingSessionLocal()
    finding = session.query(Finding).filter(Finding.application_id == app_id).first()
    assert finding is None or finding.finding_type != "Verification Required"
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
    assert response.status_code == 200
    data = response.json()
    assert data["execution_status"] == "completed"
    assert data["status"] == "inconclusive"
    assert data["document_stages"] == []
    assert all(
        result["status"] == "Not evaluated"
        for result in data["results"]
        if result["type"] == "regulatory_rule"
    )

    with TestingSessionLocal() as session:
        persisted_statuses = {
            rule_code: assessment_status
            for assessment_status, rule_code in session.query(
                ComplianceAssessment.status, ComplianceRule.rule_code
            )
            .join(ComplianceRule)
            .filter(ComplianceAssessment.application_id == app_id)
            .all()
        }
    assert persisted_statuses == {
        result["rule_id"]: result["status"]
        for result in data["results"]
        if result["type"] == "regulatory_rule"
    }


def test_validate_all_returns_unavailable_when_registry_cannot_load(monkeypatch):
    institution_id = create_institution("Unavailable registry institution")
    email = create_test_user(
        "unavailable-registry@example.com",
        institution_id=institution_id,
    )
    application_id = create_application(inst_id=institution_id)

    def unavailable_registry():
        raise RegistryValidationError("registry file is unavailable")

    monkeypatch.setattr(application_routes, "load_registry", unavailable_registry)
    response = client.post(
        f"/api/applications/{application_id}/validate-all",
        headers={"Authorization": f"Bearer {get_token(email)}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["execution_status"] == "partial"
    assert data["status"] == "inconclusive"
    assert data["stages"][0] == {
        "name": "regulatory_validation",
        "status": "unavailable",
        "reason": "Regulatory rule registry is unavailable.",
        "result_count": 0,
    }
    with TestingSessionLocal() as session:
        run = session.query(ValidationRun).filter_by(id=data["run_id"]).one()
        assert run.outcome == data["status"]
        assert run.execution_status == data["execution_status"]


def test_validate_all_reports_persistence_failure_without_success(monkeypatch):
    institution_id = create_institution("Persistence failure institution")
    email = create_test_user(
        "validation-persistence-failure@example.com",
        institution_id=institution_id,
    )
    application_id = create_application(inst_id=institution_id)
    headers = {"Authorization": f"Bearer {get_token(email)}"}
    original_commit = SQLAlchemySession.commit

    def fail_validation_commit(session):
        if any(
            isinstance(item, AuditEvent)
            and item.action == "application.validate_all"
            for item in session.new
        ):
            raise SQLAlchemyError("forced validation commit failure")
        return original_commit(session)

    monkeypatch.setattr(SQLAlchemySession, "commit", fail_validation_commit)
    response = client.post(
        f"/api/applications/{application_id}/validate-all",
        headers=headers,
    )

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "Application validation results could not be saved."
    )
    with TestingSessionLocal() as session:
        assert session.query(ComplianceAssessment).filter_by(
            application_id=application_id
        ).count() == 0
        assert session.query(AuditEvent).filter_by(
            action="application.validate_all",
            entity_id=str(application_id),
        ).count() == 0

def test_validate_all_with_no_applicable_rules_is_inconclusive(monkeypatch):
    institution_id = create_institution("No applicable rules institution")
    email = create_test_user(
        "no-applicable-rules@example.com",
        institution_id=institution_id,
    )
    application_id = create_application(inst_id=institution_id)
    rule = {
        "rule_id": "DOCUMENT-CANDIDATE",
        "document_type": "fire_safety_certificate",
        "preview_approved": True,
    }
    monkeypatch.setattr(application_routes, "load_registry", lambda: [rule])
    monkeypatch.setattr(
        application_routes,
        "evaluate_preview_eligibility",
        lambda *_args: "not_applicable",
    )

    response = client.post(
        f"/api/applications/{application_id}/validate-all",
        headers={"Authorization": f"Bearer {get_token(email)}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["execution_status"] == "completed"
    assert data["status"] == "inconclusive"
    assert data["evaluated_rules_count"] == 0
    assert data["not_applicable_rules_count"] == 1
    assert data["results"][0]["status"] == "Not-Applicable"
    with TestingSessionLocal() as session:
        assessment = (
            session.query(ComplianceAssessment)
            .join(ComplianceRule)
            .filter(
                ComplianceAssessment.application_id == application_id,
                ComplianceRule.rule_code == "DOCUMENT-CANDIDATE",
            )
            .one()
        )
        assert assessment.status == data["results"][0]["status"]
        assert assessment.explanation == data["results"][0]["explanation"]


def test_validate_all_registry_rule_id_without_evaluator_is_not_evaluated(monkeypatch):
    institution_id = create_institution("Unsupported rule institution")
    email = create_test_user(
        "unsupported-rule@example.com",
        institution_id=institution_id,
    )
    application_id = create_application(inst_id=institution_id)
    create_processed_document(
        application_id,
        "fire_safety_certificate",
        {"certificate_number": {"value": "CERT-UNSUPPORTED", "status": "extracted"}},
    )
    rule = {
        "rule_id": "DOCUMENT-0012",
        "document_type": "fire_safety_certificate",
        "preview_approved": True,
    }
    monkeypatch.setattr(application_routes, "load_registry", lambda: [rule])
    monkeypatch.setattr(
        application_routes,
        "evaluate_preview_eligibility",
        lambda *_args: "eligible_for_preview",
    )

    response = client.post(
        f"/api/applications/{application_id}/validate-all",
        headers={"Authorization": f"Bearer {get_token(email)}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "inconclusive"
    assert data["evaluated_rules_count"] == 0
    assert data["results"][0] == {
        "type": "regulatory_rule",
        "rule_id": "DOCUMENT-0012",
        "document_type": "fire_safety_certificate",
        "status": "Not evaluated",
        "reason_code": "unsupported_rule",
        "explanation": (
            "No evaluator is implemented for rule DOCUMENT-0012; it was not evaluated."
        ),
        "evidence": None,
        "evidence_refs": [],
        "candidate_requirement": None,
        "preview_approved": True,
        "source_reference": None,
        "rule_reference": {
            "rule_id": "DOCUMENT-0012",
            "definition_sha256": hashlib.sha256(
                json.dumps(
                    rule,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest(),
            "preview_status": "approved_for_preview",
        },
    }
    with TestingSessionLocal() as session:
        assessment = (
            session.query(ComplianceAssessment)
            .join(ComplianceRule)
            .filter(
                ComplianceAssessment.application_id == application_id,
                ComplianceRule.rule_code == "DOCUMENT-0012",
            )
            .one()
        )
        assert assessment.status == data["results"][0]["status"]
        assert assessment.explanation == data["results"][0]["explanation"]


@pytest.mark.parametrize("evaluation_status", ["Pass", "Fail"])
def test_validate_all_never_maps_field_signals_to_compliance(
    evaluation_status,
    monkeypatch,
):
    institution_id = create_institution(f"{evaluation_status} signal institution")
    email = create_test_user(
        f"{evaluation_status.lower()}-signal@example.com",
        institution_id=institution_id,
    )
    application_id = create_application(inst_id=institution_id)
    create_processed_document(
        application_id,
        "fire_safety_certificate",
        {"certificate_number": {"value": "CERT-SIGNAL", "status": "extracted"}},
    )
    rule = {
        "rule_id": "FS-001",
        "document_type": "fire_safety_certificate",
        "preview_approved": True,
    }
    monkeypatch.setattr(application_routes, "load_registry", lambda: [rule])
    monkeypatch.setattr(
        application_routes,
        "evaluate_preview_eligibility",
        lambda *_args: "eligible_for_preview",
    )
    monkeypatch.setattr(
        application_routes,
        "evaluate_rule_result",
        lambda *_args: {
            "status": evaluation_status,
            "explanation": f"Unverified field check returned {evaluation_status}.",
            "evidence": "Certificate No: CERT-SIGNAL",
        },
    )

    response = client.post(
        f"/api/applications/{application_id}/validate-all",
        headers={"Authorization": f"Bearer {get_token(email)}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "partial"
    assert data["evaluated_rules_count"] == 1
    assert data["results"][0]["status"] == "Partial"
    assert data["results"][0]["reason_code"] == "review_required"
    assert "does not establish regulatory compliance" in data["results"][0]["explanation"]
    assert data["results"][0]["status"] not in {"Compliant", "Non-Compliant"}
    with TestingSessionLocal() as session:
        assessment = (
            session.query(ComplianceAssessment)
            .join(ComplianceRule)
            .filter(
                ComplianceAssessment.application_id == application_id,
                ComplianceRule.rule_code == "FS-001",
            )
            .one()
        )
        assert assessment.status == data["results"][0]["status"]
        assert assessment.explanation == data["results"][0]["explanation"]


@pytest.mark.parametrize(
    ("processing_status", "expected_stage", "expected_reason"),
    [
        ("pending", "pending", "document_pending"),
        ("failed", "failed", "document_failed"),
        ("ocr_unavailable", "unavailable", "document_unavailable"),
    ],
)
def test_validate_all_reports_unprocessed_document_stages(
    processing_status,
    expected_stage,
    expected_reason,
    monkeypatch,
):
    institution_id = create_institution(f"{processing_status} institution")
    email = create_test_user(
        f"{processing_status}-stage@example.com",
        institution_id=institution_id,
    )
    application_id = create_application(inst_id=institution_id)
    rule = {
        "rule_id": "APPROVED-CANDIDATE",
        "document_type": "fire_safety_certificate",
        "preview_approved": True,
    }
    monkeypatch.setattr(application_routes, "load_registry", lambda: [rule])
    monkeypatch.setattr(
        application_routes,
        "evaluate_preview_eligibility",
        lambda *_args: "eligible_for_preview",
    )
    if processing_status == "pending":
        def processing_is_in_progress(**_kwargs):
            raise application_routes.HTTPException(
                status_code=409,
                detail="Document processing is already in progress",
            )

        monkeypatch.setattr(
            application_routes,
            "process_document",
            processing_is_in_progress,
        )
    with TestingSessionLocal() as session:
        session.add(
            Document(
                application_id=application_id,
                doc_type="fire_safety_certificate",
                original_filename="unprocessed.pdf",
                storage_key="unprocessed.pdf",
                processing_status=processing_status,
            )
        )
        session.commit()

    response = client.post(
        f"/api/applications/{application_id}/validate-all",
        headers={"Authorization": f"Bearer {get_token(email)}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["execution_status"] == "partial"
    assert data["status"] == "inconclusive"
    assert data["document_stages"][0]["status"] == expected_stage
    assert data["results"][0]["reason_code"] == expected_reason
    assert data["results"][0]["status"] == "Not evaluated"
    assert any(stage["name"] == "document_processing" and stage["status"] == "partial" for stage in data["stages"])


def test_validate_all_processes_pending_pdf_and_reuses_persisted_result(
    tmp_path,
    monkeypatch,
):
    institution_id = create_institution("Orchestrated processing institution")
    email = create_test_user(
        "orchestrated-processing@example.com",
        institution_id=institution_id,
    )
    application_id = create_application(inst_id=institution_id)
    storage_dir = tmp_path / "documents"
    monkeypatch.setattr(application_routes.settings, "DOCUMENT_STORAGE_DIR", storage_dir)

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text(
        (72, 72),
        "Fire Safety Certificate\nCertificate Number: SYNTHETIC-001",
    )
    pdf_bytes = pdf.tobytes()
    pdf.close()

    upload = client.post(
        f"/api/applications/{application_id}/documents",
        headers={"Authorization": f"Bearer {get_token(email)}"},
        files={"file": ("synthetic-certificate.pdf", pdf_bytes, "application/pdf")},
        data={"doc_type": "fire_safety_certificate"},
    )
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["id"]

    response = client.post(
        f"/api/applications/{application_id}/validate-all",
        headers={"Authorization": f"Bearer {get_token(email)}"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    orchestration = next(
        stage for stage in data["stages"]
        if stage["name"] == "document_processing_orchestration"
    )
    assert orchestration["status"] == "completed"
    assert orchestration["documents"] == [{
        "document_id": document_id,
        "status": "completed",
        "reason": "Document processing was run as part of application validation.",
    }]
    with TestingSessionLocal() as session:
        document = session.query(Document).filter_by(id=document_id).one()
        assert document.processing_status == "completed"
        assert document.processing_result["fields"]["certificate_number"]["value"] == "SYNTHETIC-001"
        first_processed_at = document.processed_at
        run = session.query(ValidationRun).filter_by(id=data["run_id"]).one()
        assert run.stage_outcomes == data["stages"]
        assert run.results == data["results"]

    repeated = client.post(
        f"/api/applications/{application_id}/validate-all",
        headers={"Authorization": f"Bearer {get_token(email)}"},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["run_id"] != data["run_id"]
    repeated_orchestration = next(
        stage for stage in repeated.json()["stages"]
        if stage["name"] == "document_processing_orchestration"
    )
    assert repeated_orchestration["status"] == "skipped"
    with TestingSessionLocal() as session:
        document = session.query(Document).filter_by(id=document_id).one()
        assert document.processed_at == first_processed_at


def test_validate_all_marks_unknown_document_type_unsupported():
    institution_id = create_institution("Unsupported document institution")
    email = create_test_user(
        "unsupported-document@example.com",
        institution_id=institution_id,
    )
    application_id = create_application(inst_id=institution_id)
    with TestingSessionLocal() as session:
        session.add(
            Document(
                application_id=application_id,
                doc_type="unknown_document_type",
                original_filename="unknown.pdf",
                storage_key="unknown.pdf",
                processing_status="completed",
                processing_result={"fields": {}},
            )
        )
        session.commit()

    response = client.post(
        f"/api/applications/{application_id}/validate-all",
        headers={"Authorization": f"Bearer {get_token(email)}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "inconclusive"
    assert data["document_stages"][0]["status"] == "unsupported"
    assert data["document_stages"][0]["processing_status"] == "completed"


def test_validate_all_reports_missing_required_document_without_failing_rule(monkeypatch):
    institution_id = create_institution("Missing required document institution")
    email = create_test_user(
        "missing-required-document@example.com",
        institution_id=institution_id,
    )
    application_id = create_application(inst_id=institution_id)
    rule = {
        "rule_id": "APPROVED-CANDIDATE",
        "document_type": "fire_safety_certificate",
        "preview_approved": True,
    }
    monkeypatch.setattr(application_routes, "load_registry", lambda: [rule])
    monkeypatch.setattr(
        application_routes,
        "evaluate_preview_eligibility",
        lambda *_args: "eligible_for_preview",
    )

    response = client.post(
        f"/api/applications/{application_id}/validate-all",
        headers={"Authorization": f"Bearer {get_token(email)}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "inconclusive"
    assert data["results"][0]["status"] == "Not evaluated"
    assert data["results"][0]["reason_code"] == "document_missing"
    assert data["findings_count"] == 1
    with TestingSessionLocal() as session:
        assessment = (
            session.query(ComplianceAssessment)
            .join(ComplianceRule)
            .filter(
                ComplianceAssessment.application_id == application_id,
                ComplianceRule.rule_code == "APPROVED-CANDIDATE",
            )
            .one()
        )
        assert assessment.status == data["results"][0]["status"]
        assert assessment.explanation == data["results"][0]["explanation"]


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
    data = response.json()
    assert all(result["status"] == "Not evaluated" for result in data["results"] if result["type"] == "regulatory_rule")
    assert any(stage["name"] == "application_checklist" and stage["status"] == "unsupported" for stage in data["stages"])


def test_validation_run_persists_evidence_stages_and_consistency_association(monkeypatch):
    institution_id = create_institution("Validation provenance institution")
    email = create_test_user(
        "validation-provenance@example.com",
        institution_id=institution_id,
    )
    token = get_token(email)
    application_id = create_application(inst_id=institution_id)
    evidence_fields = {
        "certificate_number": {
            "value": "CERT-PROVENANCE",
            "status": "extracted",
            "page": 3,
            "evidence": "Certificate No: CERT-PROVENANCE",
        },
        "institution_name": {
            "value": "Example Institute",
            "status": "extracted",
            "page": 3,
            "evidence": "Institution: Example Institute",
        },
    }
    second_document_fields = {
        **evidence_fields,
        "institution_name": {
            "value": "Example Institute Annex",
            "status": "extracted",
            "page": 3,
            "evidence": "Institution: Example Institute Annex",
        },
    }
    create_processed_document(application_id, "fire_safety_certificate", evidence_fields)
    create_processed_document(application_id, "fire_safety_certificate", second_document_fields)
    with TestingSessionLocal() as session:
        uploaded_documents = session.query(Document).filter_by(
            application_id=application_id
        ).order_by(Document.id).all()
        uploaded_documents[0].sha256 = "a" * 64
        uploaded_documents[1].sha256 = "a" * 64
        uploaded_documents[1].processing_result = {
            "fields": second_document_fields,
            "extraction_method": "ocr",
            "field_extraction_version": "test-extractor-v1",
            "ocr": {
                "engine": "tesseract",
                "engine_version": "5.4",
                "languages": ["eng"],
                "status": "completed",
            },
        }
        matching_document_id = uploaded_documents[0].id
        duplicate_document_id = uploaded_documents[1].id
        duplicate_finding = Finding(
            application_id=application_id,
            document_id=uploaded_documents[1].id,
            finding_type="Duplicate document",
            severity="Low",
            description="Exact file-byte match detected during upload; advisory only.",
            status="open",
        )
        session.add(duplicate_finding)
        session.commit()
        duplicate_finding_id = duplicate_finding.id
    registry_rule = {
        "rule_id": "FS-001",
        "document_type": "fire_safety_certificate",
        "candidate_requirement": "Candidate text preserved from registry.",
        "preview_approved": True,
        "handbook_version": "test-version",
        "source_path": "source.pdf",
        "section": "1.2",
        "printed_page": 12,
        "pdf_page": 14,
    }
    monkeypatch.setattr(application_routes, "load_registry", lambda: [registry_rule])
    monkeypatch.setattr(
        application_routes,
        "evaluate_preview_eligibility",
        lambda *_args: "eligible_for_preview",
    )
    monkeypatch.setattr(
        application_routes,
        "evaluate_rule_result",
        lambda *_args: {
            "status": "Needs review",
            "explanation": "A source check requires human review.",
            "evidence": "Certificate No: CERT-PROVENANCE",
        },
    )

    response = client.post(
        f"/api/applications/{application_id}/validate-all",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["run_id"]
    regulatory_result = next(item for item in data["results"] if item["type"] == "regulatory_rule")
    assert regulatory_result["candidate_requirement"] == registry_rule["candidate_requirement"]
    assert regulatory_result["source_reference"] == {
        "handbook_version": "test-version",
        "source_path": "source.pdf",
        "section": "1.2",
        "printed_page": 12,
        "pdf_page": 14,
    }
    assert regulatory_result["rule_reference"]["rule_id"] == "FS-001"
    assert regulatory_result["rule_reference"]["preview_status"] == "approved_for_preview"
    assert len(regulatory_result["rule_reference"]["definition_sha256"]) == 64
    with TestingSessionLocal() as session:
        source_document_id = session.query(Document.id).filter_by(
            application_id=application_id
        ).order_by(Document.id.desc()).first()[0]
    assert regulatory_result["evidence_refs"] == [{
        "document_id": source_document_id,
        "filename": "test.pdf",
        "field": "certificate_number",
        "verification_status": "unverified",
        "evidence_status": "available",
        "page": 3,
        "excerpt": "Certificate No: CERT-PROVENANCE",
        "processing_provenance": {
            "document_sha256": "a" * 64,
            "document_type": "fire_safety_certificate",
            "processing_status": "completed",
            "processed_at": None,
            "schema_version_id": None,
            "extraction_method": "ocr",
            "field_extraction_version": "test-extractor-v1",
            "ocr": {
                "engine": "tesseract",
                "engine_version": "5.4",
                "languages": ["eng"],
                "status": "completed",
            },
        },
    }]
    consistency_result = next(
        item for item in data["results"]
        if item["type"] == "consistency" and item["field"] == "institution_name"
    )
    assert consistency_result["category"] == "POSSIBLE_MISMATCH"
    assert consistency_result["values"] == ["Example Institute", "Example Institute Annex"]
    assert consistency_result["human_review_recommended"] is True
    assert "human reviewer must verify" in consistency_result["explanation"]
    assert len(consistency_result["evidence_refs"]) == 2
    assert all(
        reference["verification_status"] == "unverified"
        and reference["evidence_status"] == "available"
        for reference in consistency_result["evidence_refs"]
    )
    integrity_result = next(
        item for item in data["results"]
        if item["type"] == "document_integrity"
        and item["document_id"] == duplicate_document_id
    )
    assert integrity_result["duplicate_file_check"]["status"] == "duplicate"
    assert integrity_result["duplicate_file_check"]["matches"][0]["document_id"] == matching_document_id
    assert integrity_result["finding_ids"] == [duplicate_finding_id]
    assert integrity_result["issuer_verification"] == "not_performed"
    assert integrity_result["authenticity_status"] == "not_assessed"

    history = client.get(
        f"/api/applications/{application_id}/validation-runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert history.status_code == 200, history.text
    persisted = next(item for item in history.json()["items"] if item["id"] == data["run_id"])
    assert persisted["results"] == data["results"]
    assert persisted["stage_outcomes"] == data["stages"]
    persisted_consistency = next(
        item for item in persisted["results"]
        if item["type"] == "consistency" and item["field"] == "institution_name"
    )
    assert persisted_consistency == consistency_result
    persisted_finding_ids = {
        item["finding_id"]
        for item in persisted["results"]
        if item["type"] == "finding"
    }
    assert duplicate_finding_id in persisted_finding_ids
    assert any(
        item["type"] == "finding"
        and item["finding_type"] == "Verification Required"
        for item in persisted["results"]
    )
    with TestingSessionLocal() as session:
        run = session.query(ValidationRun).filter_by(id=data["run_id"]).one()
        assert run.assessments
        consistency_run = session.query(ConsistencyRun).filter_by(validation_run_id=run.id).one()
        assert consistency_run.comparisons_count > 0
        assert session.query(DocumentConsistencyResult).filter_by(run_id=consistency_run.id).count() == consistency_run.comparisons_count

    other_institution = create_institution("Other validation provenance institution")
    other_email = create_test_user(
        "other-validation-provenance@example.com",
        institution_id=other_institution,
    )
    unauthorized = client.get(
        f"/api/applications/{application_id}/validation-runs",
        headers={"Authorization": f"Bearer {get_token(other_email)}"},
    )
    assert unauthorized.status_code == 404


def test_validation_run_records_failed_rule_stage_without_claiming_success(monkeypatch):
    institution_id = create_institution("Failed rule stage institution")
    email = create_test_user(
        "failed-rule-stage@example.com",
        institution_id=institution_id,
    )
    application_id = create_application(inst_id=institution_id)
    create_processed_document(
        application_id,
        "fire_safety_certificate",
        {"certificate_number": {"value": "CERT-FAIL", "status": "extracted"}},
    )
    monkeypatch.setattr(application_routes, "load_registry", lambda: [{
        "rule_id": "FS-001",
        "document_type": "fire_safety_certificate",
        "preview_approved": True,
    }])
    monkeypatch.setattr(
        application_routes,
        "evaluate_preview_eligibility",
        lambda *_args: "eligible_for_preview",
    )

    def failed_evaluator(*_args):
        raise RuntimeError("forced evaluator failure")

    monkeypatch.setattr(application_routes, "evaluate_rule_result", failed_evaluator)
    response = client.post(
        f"/api/applications/{application_id}/validate-all",
        headers={"Authorization": f"Bearer {get_token(email)}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["execution_status"] == "partial"
    assert data["status"] == "inconclusive"
    assert data["error_summary"] == "Regulatory validation stage failed."
    assert data["stages"][0]["status"] == "failed"
    failed_result = next(item for item in data["results"] if item.get("rule_id") == "FS-001")
    assert failed_result["status"] == "Not evaluated"
    assert failed_result["reason_code"] == "evaluation_stage_failed"
    with TestingSessionLocal() as session:
        run = session.query(ValidationRun).filter_by(id=data["run_id"]).one()
        assert run.execution_status == "partial"
        assert run.outcome == "inconclusive"
        assert run.results == data["results"]


def test_validation_run_history_keeps_earlier_snapshot_when_assessment_changes(monkeypatch):
    institution_id = create_institution("Historical validation snapshot institution")
    email = create_test_user(
        "historical-validation-snapshot@example.com",
        institution_id=institution_id,
    )
    token = get_token(email)
    application_id = create_application(inst_id=institution_id)
    create_processed_document(
        application_id,
        "fire_safety_certificate",
        {"certificate_number": {"value": "CERT-HISTORY", "status": "extracted"}},
    )
    rule = {
        "rule_id": "FS-001",
        "document_type": "fire_safety_certificate",
        "preview_approved": True,
        "candidate_requirement": "Test-only candidate rule.",
    }
    evaluation = {
        "status": "Not evaluated",
        "explanation": "No evaluator is implemented for this rule.",
        "evidence": None,
    }
    monkeypatch.setattr(application_routes, "load_registry", lambda: [rule])
    monkeypatch.setattr(
        application_routes,
        "evaluate_preview_eligibility",
        lambda *_args: "eligible_for_preview",
    )
    monkeypatch.setattr(
        application_routes,
        "evaluate_rule_result",
        lambda *_args: evaluation.copy(),
    )
    headers = {"Authorization": f"Bearer {token}"}

    first_response = client.post(
        f"/api/applications/{application_id}/validate-all",
        headers=headers,
    )
    assert first_response.status_code == 200, first_response.text
    first_run = first_response.json()
    first_rule_result = next(
        result for result in first_run["results"]
        if result.get("type") == "regulatory_rule"
    )
    assert first_rule_result["status"] == "Not evaluated"

    with TestingSessionLocal() as session:
        persisted_first_run = session.query(ValidationRun).filter_by(id=first_run["run_id"]).one()
        first_assessment = persisted_first_run.assessments[0]
        first_assessment_id = first_assessment.id
        first_assessment_state = (first_assessment.status, first_assessment.explanation)

    evaluation.update({
        "status": "Needs review",
        "explanation": "A test-only signal requires review.",
        "evidence": "Certificate No: CERT-HISTORY",
    })
    second_response = client.post(
        f"/api/applications/{application_id}/validate-all",
        headers=headers,
    )
    assert second_response.status_code == 200, second_response.text
    second_run = second_response.json()
    second_rule_result = next(
        result for result in second_run["results"]
        if result.get("type") == "regulatory_rule"
    )
    assert second_run["run_id"] != first_run["run_id"]
    assert second_rule_result["status"] == "Partial"
    assert second_rule_result != first_rule_result

    history_response = client.get(
        f"/api/applications/{application_id}/validation-runs",
        headers=headers,
    )
    assert history_response.status_code == 200, history_response.text
    history = history_response.json()["items"]
    reloaded_first_run = next(item for item in history if item["id"] == first_run["run_id"])
    reloaded_second_run = next(item for item in history if item["id"] == second_run["run_id"])
    assert reloaded_first_run["results"] == first_run["results"]
    assert reloaded_second_run["results"] == second_run["results"]
    reloaded_first_rule = next(
        result for result in reloaded_first_run["results"]
        if result.get("type") == "regulatory_rule"
    )
    assert reloaded_first_rule == first_rule_result

    with TestingSessionLocal() as session:
        first_assessment_after_second_run = session.query(ComplianceAssessment).filter_by(
            id=first_assessment_id,
        ).one()
        assert (
            first_assessment_after_second_run.status,
            first_assessment_after_second_run.explanation,
        ) == first_assessment_state
        persisted_first_run = session.query(ValidationRun).filter_by(id=first_run["run_id"]).one()
        persisted_second_run = session.query(ValidationRun).filter_by(id=second_run["run_id"]).one()
        assert persisted_first_run.assessments[0].id == first_assessment_id
        assert persisted_first_run.assessments[0].status == "Not evaluated"
        assert persisted_second_run.assessments[0].status == "Partial"


def test_not_evaluated_result_is_not_relabelled_not_applicable_or_failure(monkeypatch):
    inst_id = create_institution("Unknown result institution")
    user_email = create_test_user("unknown-result@example.com", institution_id=inst_id)
    token = get_token(user_email)
    app_id = create_application(app_type="Standard Regulatory", inst_id=inst_id)
    create_processed_document(app_id, "fire_safety_certificate", {
        "certificate_number": {"value": "CERT-UNKNOWN", "status": "extracted"}
    })
    monkeypatch.setattr(application_routes, "load_registry", lambda: [{
        "rule_id": "UNSUPPORTED-CHECK",
        "document_type": "fire_safety_certificate",
        "preview_approved": True,
    }])
    monkeypatch.setattr(application_routes, "evaluate_preview_eligibility", lambda *_args: "eligible_for_preview")
    monkeypatch.setattr(application_routes, "evaluate_rule_result", lambda *_args: {
        "status": "Not evaluated", "explanation": "Insufficient source evidence.", "evidence": None,
    })

    response = client.post(
        f"/api/applications/{app_id}/validate-all",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "inconclusive"
    assert data["results"][0]["status"] == "Not evaluated"
    assert data["results"][0]["reason_code"] == "insufficient_evidence"
    with TestingSessionLocal() as session:
        assert session.query(Finding).filter_by(
            application_id=app_id,
            finding_type="Verification Required",
        ).count() == 0


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
    assert assigned.json()["assigned_reviewer_id"] == reviewer_id

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
    assert client.post(review_url, json={"outcome": "evidence_accepted", "note": "missing auth"}).status_code == 401
    assert client.post(review_url, headers=other_headers, json={"outcome": "evidence_accepted", "note": "not assigned"}).status_code == 404
    assert client.post(review_url, headers=owner_headers, json={"outcome": "evidence_accepted", "note": "not a reviewer"}).status_code == 403
    invalid_outcome = client.post(review_url, headers=reviewer_headers, json={"outcome": "approved", "note": "invalid outcome"})
    assert invalid_outcome.status_code == 422
    decision1 = client.post(review_url, headers=reviewer_headers, json={"outcome": "information_requested", "note": "Please provide a legible source."})
    decision2 = client.post(review_url, headers=reviewer_headers, json={"outcome": "further_investigation", "note": "Check issuer manually."})
    assert decision1.status_code == decision2.status_code == 201
    assert decision1.json()["reviewer_name"] == "Test User"
    assert decision1.json()["outcome"] == "information_requested"
    assert decision1.json()["note"] == "Please provide a legible source."
    assert decision1.json()["created_at"]
    history = client.get(detail_url, headers=reviewer_headers)
    assert history.status_code == 200
    assert [review["outcome"] for review in history.json()["reviews"]] == [
        "information_requested", "further_investigation",
    ]
    assert all(review["reviewer_name"] == "Test User" and review["created_at"] for review in history.json()["reviews"])
    assessment_list = client.get(
        f"/api/compliance-assessments/?application_id={app_id}&limit=200",
        headers=reviewer_headers,
    )
    assert assessment_list.status_code == 200
    listed_assessment = next(
        item for item in assessment_list.json()["items"] if item["id"] == assessment_id
    )
    assert [review["outcome"] for review in listed_assessment["reviews"]] == [
        "information_requested", "further_investigation",
    ]
    assert listed_assessment["reviews"][0]["note"] == "Please provide a legible source."
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
        assert session.query(Application).filter_by(id=app_id).one().status == "submitted"
        assert session.query(AuditEvent).filter_by(action="compliance_assessment.reviewer_assigned").count() == 1
        assert session.query(AuditEvent).filter_by(action="compliance_assessment.review_recorded").count() == 2


def test_assessment_review_status_transitions_are_separate_authorized_and_historical():
    institution_id = create_institution("Review lifecycle institution")
    owner_email = create_test_user("review-lifecycle-owner@example.com", institution_id=institution_id)
    reviewer_email = create_test_user("review-lifecycle-reviewer@example.com", UserRole.REVIEWER)
    other_reviewer_email = create_test_user("review-lifecycle-other@example.com", UserRole.REVIEWER)
    admin_email = create_test_user("review-lifecycle-admin@example.com", UserRole.ADMIN)
    application_id = create_application("REVIEW-LIFECYCLE", "Standard Regulatory", institution_id)
    with TestingSessionLocal() as session:
        rule = ComplianceRule(
            rule_code="REVIEW-LIFECYCLE",
            title="Review lifecycle",
            description="Synthetic review lifecycle rule",
            category="test",
        )
        session.add(rule)
        session.flush()
        assessment = ComplianceAssessment(
            application_id=application_id,
            rule_id=rule.id,
            status="Not evaluated",
            explanation="Automated result remains inconclusive.",
        )
        session.add(assessment)
        session.commit()
        assessment_id = assessment.id
        reviewer_id = session.query(User.id).filter_by(email=reviewer_email).scalar()

    admin_headers = {"Authorization": f"Bearer {get_token(admin_email)}"}
    reviewer_headers = {"Authorization": f"Bearer {get_token(reviewer_email)}"}
    other_headers = {"Authorization": f"Bearer {get_token(other_reviewer_email)}"}
    owner_headers = {"Authorization": f"Bearer {get_token(owner_email)}"}
    assignment = client.post(
        f"/api/compliance-assessments/{assessment_id}/assignment",
        headers=admin_headers,
        json={"reviewer_id": reviewer_id},
    )
    assert assignment.status_code == 200, assignment.text
    assert assignment.json()["review_status"] == "PENDING_REVIEW"
    assert client.post(
        f"/api/compliance-assessments/{assessment_id}/review-status",
        headers=other_headers,
        json={"review_status": "IN_REVIEW"},
    ).status_code == 404
    assert client.post(
        f"/api/compliance-assessments/{assessment_id}/review-status",
        headers=owner_headers,
        json={"review_status": "IN_REVIEW"},
    ).status_code == 403

    status_url = f"/api/compliance-assessments/{assessment_id}/review-status"
    invalid_transition = client.post(
        status_url,
        headers=reviewer_headers,
        json={"review_status": "CLOSED", "reason": "Not yet reviewed"},
    )
    assert invalid_transition.status_code == 409
    entered_review = client.post(
        status_url,
        headers=reviewer_headers,
        json={"review_status": "IN_REVIEW"},
    )
    assert entered_review.status_code == 200
    missing_reason = client.post(
        status_url,
        headers=reviewer_headers,
        json={"review_status": "ADDITIONAL_INFORMATION_REQUIRED"},
    )
    assert missing_reason.status_code == 422
    requested_info = client.post(
        status_url,
        headers=reviewer_headers,
        json={
            "review_status": "ADDITIONAL_INFORMATION_REQUIRED",
            "reason": "The uploaded scan is unreadable.",
        },
    )
    assert requested_info.status_code == 200
    reopened = client.post(
        status_url,
        headers=reviewer_headers,
        json={"review_status": "IN_REVIEW"},
    )
    assert reopened.status_code == 200
    escalated = client.post(
        status_url,
        headers=reviewer_headers,
        json={"review_status": "ESCALATED", "reason": "Issuer cannot be verified locally."},
    )
    assert escalated.status_code == 200
    closed = client.post(
        status_url,
        headers=reviewer_headers,
        json={"review_status": "CLOSED", "reason": "Review action is complete."},
    )
    assert closed.status_code == 200
    duplicate_close = client.post(
        status_url,
        headers=reviewer_headers,
        json={"review_status": "CLOSED"},
    )
    assert duplicate_close.status_code == 200
    assert duplicate_close.json()["changed"] is False
    reopened_closed = client.post(
        status_url,
        headers=reviewer_headers,
        json={"review_status": "IN_REVIEW"},
    )
    assert reopened_closed.status_code == 409

    history = client.get(
        f"/api/compliance-assessments/{assessment_id}",
        headers=reviewer_headers,
    )
    assert history.status_code == 200
    details = history.json()
    assert details["review_status"] == "CLOSED"
    assert [item["to_status"] for item in details["review_status_history"]] == [
        "IN_REVIEW",
        "ADDITIONAL_INFORMATION_REQUIRED",
        "IN_REVIEW",
        "ESCALATED",
        "CLOSED",
    ]
    assert details["review_status_history"][1]["reason"] == "The uploaded scan is unreadable."
    assert details["status"] == "Not evaluated"
    owner_history = client.get(
        f"/api/compliance-assessments/{assessment_id}",
        headers=owner_headers,
    )
    assert owner_history.status_code == 200
    assert owner_history.json()["review_status_history"][1]["reason"] is None
    with TestingSessionLocal() as session:
        assert session.query(Application).filter_by(id=application_id).one().status == "submitted"
        assert session.query(ComplianceAssessmentStatusHistory).filter_by(
            assessment_id=assessment_id
        ).count() == 5
        assert session.query(AuditEvent).filter_by(
            action="compliance_assessment.review_status_changed",
            entity_id=str(assessment_id),
        ).count() == 5

    closed_queue = client.get(
        "/api/compliance-assessments/?review_status=CLOSED",
        headers=admin_headers,
    )
    assert closed_queue.status_code == 200
    assert [item["id"] for item in closed_queue.json()["items"]] == [assessment_id]
    pending_queue = client.get(
        "/api/compliance-assessments/?review_status=PENDING_REVIEW",
        headers=admin_headers,
    )
    assert pending_queue.status_code == 200
    assert pending_queue.json()["items"] == []


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
