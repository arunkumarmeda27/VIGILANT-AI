import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db.base import Base
from app.core.security import get_password_hash
from app.models.enums import UserRole
from app.models.models import User, Application, Institution
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
def setup_db():
    # Clean and rebuild schema for every single test to ensure total isolation
    app.dependency_overrides[real_get_db] = override_get_db
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

    response = client.patch(
        f"/api/applications/{app_id}",
        json={"entity_name": "Updated Corp"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["entity_name"] == "Updated Corp"

def test_invalid_payload_rejected():
    user_email = create_test_user()
    token = get_token(user_email)

    response = client.post(
        "/api/applications",
        json={"reference": ""},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 422
