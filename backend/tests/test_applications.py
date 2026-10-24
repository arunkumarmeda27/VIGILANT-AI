import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db.base import Base
from app.core.security import get_password_hash
from app.models.enums import UserRole
from app.models.models import AuditEvent, User, Application, Institution, ComplianceAssessment, ComplianceRule
from app.schemas.auth import UserCreate
from app.db.session import get_db as real_get_db

# Use a single shared test database for the whole suite to avoid file contention
SQLALCHEMY_DATABASE_URL = "sqlite:///test_suite.db"

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

# Apply the override globally for the app instance used by TestClient
client = TestClient(app)

@pytest.fixture(scope="function", autouse=True)
def setup_db(monkeypatch):
    # Clean and rebuild schema for every single test to ensure total isolation
    monkeypatch.setitem(app.dependency_overrides, real_get_db, override_get_db)
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
    assert resp.status_code == 200, f"Auth failed for {email}: {resp.text}"
    return resp.json()["access_token"]

# --- Application Tests ---

def test_unauthenticated_creation_rejected():
    response = client.post(
        "/api/applications",
        json={"reference": "REF001", "entity_name": "Test Corp", "app_type": "Standard"}
    )
    assert response.status_code == 401

def test_authenticated_creation_success():
    # Setup: Create an institution and a user assigned to it
    session = TestingSessionLocal()
    inst = Institution(name="Test Institution")
    session.add(inst)
    session.commit()
    inst_id = inst.id
    session.close()

    user_email = create_test_user(institution_id=inst_id)
    token = get_token(user_email)

    response = client.post(
        "/api/applications",
        json={"reference": "REF001", "entity_name": "Test Corp", "app_type": "Standard"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 201
    assert response.json()["reference"] == "REF001"
    assert response.json()["status"] == "submitted"

    session = TestingSessionLocal()
    created_application = session.query(Application).filter_by(reference="REF001").one()
    assert created_application.institution_id == inst_id
    event = session.query(AuditEvent).filter_by(
        entity_type="application",
        entity_id=str(created_application.id),
        action="application.created",
    ).one()
    assert event.user_id is not None
    session.close()

def test_administrator_creation_is_unassigned_and_status_is_backend_controlled():
    admin_email = create_test_user("admin@example.com", UserRole.ADMIN)
    token = get_token(admin_email)
    session = TestingSessionLocal()
    institution = Institution(name="Administrator Institution")
    session.add(institution)
    session.commit()
    institution_id = institution.id
    session.close()

    response = client.post(
        "/api/applications/",
        json={
            "reference": "ADMIN-REF",
            "entity_name": "Synthetic Organization",
            "app_type": "Demonstration",
            "institution_id": institution_id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "submitted"
    session = TestingSessionLocal()
    created_application = session.query(Application).filter_by(reference="ADMIN-REF").one()
    assert created_application.institution_id == institution_id
    session.close()

def test_reviewer_cannot_create_application():
    reviewer_email = create_test_user("reviewer@example.com", UserRole.REVIEWER)
    token = get_token(reviewer_email)

    response = client.post(
        "/api/applications/",
        json={
            "reference": "REVIEWER-REF",
            "entity_name": "Synthetic Organization",
            "app_type": "Demonstration",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403

def test_application_creation_rejects_client_selected_status_and_institution():
    admin_email = create_test_user("admin@example.com", UserRole.ADMIN)
    token = get_token(admin_email)

    response = client.post(
        "/api/applications/",
        json={
            "reference": "CLIENT-CONTROLLED",
            "entity_name": "Synthetic Organization",
            "app_type": "Demonstration",
            "status": "approved",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422

def test_institution_user_cannot_select_another_institution():
    own = Institution(name="Own Institution")
    other = Institution(name="Other Institution")
    session = TestingSessionLocal()
    session.add_all([own, other])
    session.commit()
    own_id, other_id = own.id, other.id
    session.close()
    user_email = create_test_user(
        "cannot-select@example.com",
        institution_id=own_id,
    )
    token = get_token(user_email)

    response = client.post(
        "/api/applications/",
        json={
            "reference": "OTHER-OWNER",
            "entity_name": "Other Institution",
            "app_type": "Demonstration",
            "institution_id": other_id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403

def test_list_applications_authenticated():
    # Setup: Create an institution and a user assigned to it
    session = TestingSessionLocal()
    inst = Institution(name="Test Institution")
    session.add(inst)
    session.commit()
    inst_id = inst.id
    session.close()

    user_email = create_test_user(institution_id=inst_id)
    token = get_token(user_email)

    session = TestingSessionLocal()
    app1 = Application(reference="R1", entity_name="E1", app_type="T1", institution_id=inst_id)
    app2 = Application(reference="R2", entity_name="E2", app_type="T2", institution_id=inst_id)
    session.add_all([app1, app2])
    session.commit()
    session.close()

    response = client.get(
        "/api/applications",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert len(response.json()) == 2

def test_get_application_success():
    # Setup: Create an institution and a user assigned to it
    session = TestingSessionLocal()
    inst = Institution(name="Test Institution")
    session.add(inst)
    session.commit()
    inst_id = inst.id
    session.close()

    user_email = create_test_user(institution_id=inst_id)
    token = get_token(user_email)

    session = TestingSessionLocal()
    app1 = Application(reference="R1", entity_name="E1", app_type="T1", institution_id=inst_id)
    session.add(app1)
    session.commit()
    app_id = app1.id
    session.close()

    response = client.get(
        f"/api/applications/{app_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["reference"] == "R1"

def test_get_application_not_found():
    user_email = create_test_user()
    token = get_token(user_email)

    response = client.get(
        "/api/applications/999",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404

def test_update_application_success():
    session = TestingSessionLocal()
    inst = Institution(name="Test Institution")
    session.add(inst)
    session.commit()
    inst_id = inst.id
    session.close()

    user_email = create_test_user(institution_id=inst_id)
    token = get_token(user_email)
    session = TestingSessionLocal()
    app1 = Application(reference="R1", entity_name="E1", app_type="T1", institution_id=inst_id)
    session.add(app1)
    session.commit()
    app_id = app1.id
    session.close()

    response = client.patch(
        f"/api/applications/{app_id}",
        json={"entity_name": "Updated Corp"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["entity_name"] == "Updated Corp"
    with TestingSessionLocal() as session:
        assert session.query(AuditEvent).filter_by(
            action="application.updated", entity_id=str(app_id)
        ).count() == 1


def test_unchanged_application_update_does_not_create_a_changed_fields_audit_event():
    session = TestingSessionLocal()
    institution = Institution(name="Unchanged Update Institution")
    session.add(institution)
    session.commit()
    application = Application(
        reference="UNCHANGED-REF",
        entity_name="Unchanged Entity",
        app_type="Demonstration",
        institution_id=institution.id,
    )
    session.add(application)
    session.commit()
    application_id = application.id
    institution_id = institution.id
    session.close()

    user_email = create_test_user("unchanged-update@example.com", institution_id=institution_id)
    response = client.patch(
        f"/api/applications/{application_id}",
        json={"entity_name": "Unchanged Entity"},
        headers={"Authorization": f"Bearer {get_token(user_email)}"},
    )
    assert response.status_code == 200
    with TestingSessionLocal() as session:
        assert session.query(AuditEvent).filter_by(
            action="application.updated", entity_id=str(application_id)
        ).count() == 0


def test_reviewer_cannot_update_application_fields_other_than_status():
    reviewer_email = create_test_user("restricted-reviewer@example.com", UserRole.REVIEWER)
    with TestingSessionLocal() as session:
        reviewer_id = session.query(User.id).filter_by(email=reviewer_email).scalar()
    session = TestingSessionLocal()
    institution = Institution(name="Reviewer Update Institution")
    session.add(institution)
    session.flush()
    application = Application(
        reference="REVIEWER-UPDATE-REF",
        entity_name="Original Entity",
        app_type="Demonstration",
        institution_id=institution.id,
    )
    session.add(application)
    rule = ComplianceRule(
        rule_code="REVIEWER-UPDATE-TEST",
        title="Test rule",
        description="Test only",
        category="test",
    )
    session.add(rule)
    session.flush()
    session.add(ComplianceAssessment(
        application_id=application.id,
        rule_id=rule.id,
        status="Not evaluated",
        explanation="Test assignment",
        reviewer_id=reviewer_id,
    ))
    session.commit()
    application_id = application.id
    session.close()

    response = client.patch(
        f"/api/applications/{application_id}",
        json={"entity_name": "Attempted Change"},
        headers={"Authorization": f"Bearer {get_token(reviewer_email)}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Reviewers can update application status only"
def test_institution_user_cannot_change_application_status():
    session = TestingSessionLocal()
    inst = Institution(name="Status Institution")
    session.add(inst)
    session.commit()
    inst_id = inst.id
    application = Application(
        reference="STATUS-REF",
        entity_name="Status Entity",
        app_type="Demonstration",
        institution_id=inst_id,
    )
    session.add(application)
    session.commit()
    application_id = application.id
    session.close()

    user_email = create_test_user("status-user@example.com", institution_id=inst_id)
    token = get_token(user_email)
    response = client.patch(
        f"/api/applications/{application_id}",
        json={"status": "approved"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403

def test_invalid_payload_rejected():
    user_email = create_test_user()
    token = get_token(user_email)

    response = client.post(
        "/api/applications",
        json={"reference": ""},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 422

def test_duplicate_application_reference_rejected():
    session = TestingSessionLocal()
    institution = Institution(name="Duplicate Institution")
    session.add(institution)
    session.commit()
    institution_id = institution.id
    session.add(Application(
        reference="DUPLICATE-REF",
        entity_name="Existing",
        app_type="Demonstration",
        institution_id=institution_id,
    ))
    session.commit()
    session.close()

    user_email = create_test_user(
        "duplicate-user@example.com",
        institution_id=institution_id,
    )
    token = get_token(user_email)
    response = client.post(
        "/api/applications/",
        json={
            "reference": "DUPLICATE-REF",
            "entity_name": "Another organization",
            "app_type": "Demonstration",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400


def test_admin_institution_selection_requires_existing_institution():
    admin_email = create_test_user("missing-institution-admin@example.com", UserRole.ADMIN)
    token = get_token(admin_email)

    response = client.post(
        "/api/applications/",
        json={
            "reference": "MISSING-INSTITUTION",
            "entity_name": "Synthetic Organization",
            "app_type": "Demonstration",
            "institution_id": 99999,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


def test_institution_lifecycle_endpoints_are_admin_only():
    institution_user = create_test_user(
        "institution-route-user@example.com",
        UserRole.INSTITUTION_USER,
    )
    user_headers = {"Authorization": f"Bearer {get_token(institution_user)}"}
    assert client.get("/api/institutions/", headers=user_headers).status_code == 403
    assert client.post(
        "/api/institutions/",
        headers=user_headers,
        json={"name": "Unauthorized Institution"},
    ).status_code == 403

    admin = create_test_user("institution-route-admin@example.com", UserRole.ADMIN)
    admin_headers = {"Authorization": f"Bearer {get_token(admin)}"}
    created = client.post(
        "/api/institutions/",
        headers=admin_headers,
        json={"name": "Admin Managed Institution"},
    )
    assert created.status_code == 201
    assert created.json()["name"] == "Admin Managed Institution"
    assert client.get("/api/institutions/", headers=admin_headers).json() == [created.json()]
    duplicate = client.post(
        "/api/institutions/",
        headers=admin_headers,
        json={"name": "Admin Managed Institution"},
    )
    assert duplicate.status_code == 409


def test_admin_can_create_and_retrieve_application_for_selected_institution():
    admin = create_test_user("lifecycle-admin@example.com", UserRole.ADMIN)
    headers = {"Authorization": f"Bearer {get_token(admin)}"}
    institution = client.post(
        "/api/institutions/",
        headers=headers,
        json={"name": "Lifecycle Institution"},
    )
    assert institution.status_code == 201
    institution_id = institution.json()["id"]

    created = client.post(
        "/api/applications/",
        headers=headers,
        json={
            "reference": "LIFECYCLE-001",
            "entity_name": "Lifecycle Institution",
            "app_type": "New application",
            "institution_id": institution_id,
        },
    )
    assert created.status_code == 201
    application_id = created.json()["id"]
    assert created.json()["institution_id"] == institution_id

    listing = client.get("/api/applications/", headers=headers)
    assert any(item["id"] == application_id for item in listing.json())
    details = client.get(f"/api/applications/{application_id}", headers=headers)
    assert details.status_code == 200
    assert details.json()["institution_id"] == institution_id
    updated = client.patch(
        f"/api/applications/{application_id}",
        headers=headers,
        json={"entity_name": "Updated Lifecycle Institution"},
    )
    assert updated.status_code == 200
    assert updated.json()["entity_name"] == "Updated Lifecycle Institution"


def test_audit_history_is_scoped_to_accessible_applications():
    first_institution = Institution(name="Audit First Institution")
    second_institution = Institution(name="Audit Second Institution")
    session = TestingSessionLocal()
    session.add_all([first_institution, second_institution])
    session.commit()
    first_id, second_id = first_institution.id, second_institution.id
    session.close()

    first_user = create_test_user(
        "audit-first@example.com",
        UserRole.INSTITUTION_USER,
        first_id,
    )
    second_user = create_test_user(
        "audit-second@example.com",
        UserRole.INSTITUTION_USER,
        second_id,
    )
    first_headers = {"Authorization": f"Bearer {get_token(first_user)}"}
    second_headers = {"Authorization": f"Bearer {get_token(second_user)}"}
    first_application = client.post(
        "/api/applications/",
        headers=first_headers,
        json={
            "reference": "AUDIT-FIRST",
            "entity_name": "Audit First Institution",
            "app_type": "Demo",
        },
    ).json()
    second_application = client.post(
        "/api/applications/",
        headers=second_headers,
        json={
            "reference": "AUDIT-SECOND",
            "entity_name": "Audit Second Institution",
            "app_type": "Demo",
        },
    ).json()

    first_events = client.get("/api/audit-events/", headers=first_headers)
    assert first_events.status_code == 200
    assert first_events.json()["total"] == 1
    assert first_events.json()["items"][0]["entity_id"] == str(first_application["id"])
    assert first_events.json()["items"][0]["metadata"] == {"reference": "AUDIT-FIRST"}
    assert all(item["entity_id"] != str(second_application["id"]) for item in first_events.json()["items"])
    assert client.get("/api/audit-events/").status_code == 401


def test_audit_history_supports_bounded_pagination():
    admin = create_test_user("audit-admin@example.com", UserRole.ADMIN)
    headers = {"Authorization": f"Bearer {get_token(admin)}"}
    institution = Institution(name="Audit Pagination Institution")
    session = TestingSessionLocal()
    session.add(institution)
    session.commit()
    institution_id = institution.id
    session.close()
    client.post(
        "/api/applications/",
        headers=headers,
        json={
            "reference": "AUDIT-PAGE-1",
            "entity_name": "Audit Pagination Institution",
            "app_type": "Demo",
            "institution_id": institution_id,
        },
    )
    response = client.get("/api/audit-events/?limit=1&offset=0", headers=headers)
    assert response.status_code == 200
    assert response.json()["limit"] == 1
    assert len(response.json()["items"]) == 1
    assert response.json()["total"] == 1
    assert client.get("/api/audit-events/?limit=201", headers=headers).status_code == 422
