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

# Use a separate test DB for this specific set of security tests
SQLALCHEMY_DATABASE_URL = "sqlite:///test_ownership.db"

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
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

def create_institution(name):
    session = TestingSessionLocal()
    inst = Institution(name=name)
    session.add(inst)
    session.commit()
    id_val = inst.id
    session.close()
    return id_val

def create_test_user(email, role, inst_id=None):
    session = TestingSessionLocal()
    user = User(
        full_name="Test User",
        email=email,
        password_hash=get_password_hash("password123"),
        role=role.value,
        is_active=True,
        institution_id=inst_id
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

def test_institution_isolation_creation():
    # Setup: Two institutions
    inst_a = create_institution("Institution A")
    inst_b = create_institution("Institution B")

    user_a = create_test_user("a@test.com", UserRole.INSTITUTION_USER, inst_a)
    token_a = get_token(user_a)

    # Create app as A
    response = client.post(
        "/api/applications",
        json={"reference": "REF-A", "entity_name": "Entity A", "app_type": "Type A"},
        headers={"Authorization": f"Bearer {token_a}"}
    )
    assert response.status_code == 201
    app_id = response.json()["id"]

    # Verify it belongs to Inst A
    session = TestingSessionLocal()
    app_db = session.query(Application).get(app_id)
    assert app_db.institution_id == inst_a
    session.close()

def test_institution_isolation_listing():
    inst_a = create_institution("Institution A")
    inst_b = create_institution("Institution B")

    user_a = create_test_user("a@test.com", UserRole.INSTITUTION_USER, inst_a)
    token_a = get_token(user_a)

    # Create apps for both
    session = TestingSessionLocal()
    app_a = Application(reference="RA", entity_name="EA", app_type="TA", institution_id=inst_a)
    app_b = Application(reference="RB", entity_name="EB", app_type="TB", institution_id=inst_b)
    session.add_all([app_a, app_b])
    session.commit()
    session.close()

    response = client.get(
        "/api/applications",
        headers={"Authorization": f"Bearer {token_a}"}
    )
    assert response.status_code == 200
    # User A should only see app_a
    assert len(response.json()) == 1
    assert response.json()[0]["reference"] == "RA"

def test_institution_isolation_retrieval():
    inst_a = create_institution("Institution A")
    inst_b = create_institution("Institution B")

    user_a = create_test_user("a@test.com", UserRole.INSTITUTION_USER, inst_a)
    token_a = get_token(user_a)

    session = TestingSessionLocal()
    app_b = Application(reference="RB", entity_name="EB", app_type="TB", institution_id=inst_b)
    session.add(app_b)
    session.commit()
    app_id = app_b.id
    session.close()

    response = client.get(
        f"/api/applications/{app_id}",
        headers={"Authorization": f"Bearer {token_a}"}
    )
    # Should return 404 to avoid leaking existence
    assert response.status_code == 404

def test_update_failure_cross_institution():
    inst_a = create_institution("Institution A")
    inst_b = create_institution("Institution B")

    user_a = create_test_user("a@test.com", UserRole.INSTITUTION_USER, inst_a)
    token_a = get_token(user_a)

    session = TestingSessionLocal()
    app_b = Application(reference="RB", entity_name="EB", app_type="TB", institution_id=inst_b)
    session.add(app_b)
    session.commit()
    app_id = app_b.id
    session.close()

    response = client.patch(
        f"/api/applications/{app_id}",
        json={"entity_name": "Hacked Corp"},
        headers={"Authorization": f"Bearer {token_a}"}
    )
    assert response.status_code == 404

def test_no_institution_cannot_create():
    user = create_test_user("no-inst@test.com", UserRole.INSTITUTION_USER, None)
    token = get_token(user)

    response = client.post(
        "/api/applications",
        json={"reference": "REF", "entity_name": "Entity", "app_type": "Type"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403

def test_legacy_records_invisible_to_inst_user():
    inst_a = create_institution("Institution A")
    user_a = create_test_user("a@test.com", UserRole.INSTITUTION_USER, inst_a)
    token_a = get_token(user_a)

    session = TestingSessionLocal()
    app_legacy = Application(reference="LEGACY", entity_name="Old", app_type="Old", institution_id=None)
    session.add(app_legacy)
    session.commit()
    app_id = app_legacy.id
    session.close()

    # List
    resp_list = client.get("/api/applications", headers={"Authorization": f"Bearer {token_a}"})
    assert len(resp_list.json()) == 0

    # Get
    resp_get = client.get(f"/api/applications/{app_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert resp_get.status_code == 404

def test_admin_can_see_legacy():
    admin = create_test_user("admin@test.com", UserRole.ADMIN)
    token = get_token(admin)

    session = TestingSessionLocal()
    app_legacy = Application(reference="LEGACY", entity_name="Old", app_type="Old", institution_id=None)
    session.add(app_legacy)
    session.commit()
    app_id = app_legacy.id
    session.close()

    resp = client.get(f"/api/applications/{app_id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
