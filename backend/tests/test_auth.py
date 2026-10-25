from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db.base import Base
from app.core.security import get_password_hash
from app.models.enums import UserRole
from app.models.models import AuditEvent, User
from app.db.session import get_db as real_get_db

# Share one isolated in-memory connection across the synchronous test client.
SQLALCHEMY_DATABASE_URL = "sqlite://"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Apply override globally
def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

client = TestClient(app)

@pytest.fixture(scope="function", autouse=True)
def setup_db(monkeypatch):
    # Ensure clean state for every single test
    monkeypatch.setitem(app.dependency_overrides, real_get_db, override_get_db)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

def get_test_session():
    """Helper to get a session for data setup."""
    return TestingSessionLocal()

def test_login_success(capsys):
    session = get_test_session()
    try:
        user = User(
            full_name="Test User",
            email="test@example.com",
            password_hash=get_password_hash("password123"),
            role=UserRole.ADMIN.value,
            is_active=True
        )
        session.add(user)
        session.commit()

        response = client.post(
            "/api/auth/login",
            json={"email": "test@example.com", "password": "password123"}
        )
        assert response.status_code == 200, f"Login failed with {response.status_code}: {response.text}"
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
    finally:
        session.close()

def test_login_failure_wrong_password():
    session = get_test_session()
    try:
        user = User(
            full_name="Test User",
            email="test@example.com",
            password_hash=get_password_hash("password123"),
            role=UserRole.ADMIN.value,
            is_active=True
        )
        session.add(user)
        session.commit()

        response = client.post(
            "/api/auth/login",
            json={"email": "test@example.com", "password": "wrongpassword"}
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Incorrect email or password"
    finally:
        session.close()

def test_login_failure_unknown_user():
    response = client.post(
        "/api/auth/login",
        json={"email": "unknown@example.com", "password": "password123"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"

def test_auth_me_without_token():
    response = client.get("/api/auth/me")
    assert response.status_code == 401

def test_auth_me_success():
    session = get_test_session()
    try:
        user = User(
            full_name="Test User",
            email="test@example.com",
            password_hash=get_password_hash("password123"),
            role=UserRole.ADMIN.value,
            is_active=True
        )
        session.add(user)
        session.commit()

        # Get token
        login_resp = client.post(
            "/api/auth/login",
            json={"email": "test@example.com", "password": "password123"}
        )
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]

        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "test@example.com"
        assert "password_hash" not in data
    finally:
        session.close()

def test_disabled_user_login():
    session = get_test_session()
    try:
        user = User(
            full_name="Disabled User",
            email="disabled@example.com",
            password_hash=get_password_hash("password123"),
            role=UserRole.ADMIN.value,
            is_active=False
        )
        session.add(user)
        session.commit()

        response = client.post(
            "/api/auth/login",
            json={"email": "disabled@example.com", "password": "password123"}
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "Account is disabled"
    finally:
        session.close()

def test_admin_user_creation():
    session = get_test_session()
    try:
        admin = User(
            full_name="Admin User",
            email="admin@example.com",
            password_hash=get_password_hash("adminpass"),
            role=UserRole.ADMIN.value,
            is_active=True
        )
        session.add(admin)
        session.commit()

        # Login as admin
        login_resp = client.post(
            "/api/auth/login",
            json={"email": "admin@example.com", "password": "adminpass"}
        )
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]

        # Create new user
        new_user_data = {
            "full_name": "New User",
            "email": "new@example.com",
            "password": "User-pass-test-123",
            "role": UserRole.INSTITUTION_USER.value
        }
        response = client.post(
            "/api/auth/users",
            json=new_user_data,
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert response.json()["email"] == "new@example.com"
    finally:
        session.close()

def test_non_admin_cannot_create_user():
    session = get_test_session()
    try:
        user = User(
            full_name="Regular User",
            email="user@example.com",
            password_hash=get_password_hash("userpass"),
            role=UserRole.INSTITUTION_USER.value,
            is_active=True
        )
        session.add(user)
        session.commit()

        # Login as regular user
        login_resp = client.post(
            "/api/auth/login",
            json={"email": "user@example.com", "password": "userpass"}
        )
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]

        # Attempt to create user
        new_user_data = {
            "full_name": "Hacker",
            "email": "hacker@example.com",
            "password": "password",
            "role": UserRole.ADMIN.value
        }
        response = client.post(
            "/api/auth/users",
            json=new_user_data,
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403
    finally:
        session.close()


def test_admin_user_management_is_filtered_authorized_and_audited():
    admin = User(
        full_name="Management Admin",
        email="management-admin@example.com",
        password_hash=get_password_hash("admin-password"),
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    reviewer = User(
        full_name="Synthetic Reviewer",
        email="synthetic-reviewer@example.com",
        password_hash=get_password_hash("reviewer-password"),
        role=UserRole.REVIEWER.value,
        is_active=True,
    )
    with TestingSessionLocal() as session:
        session.add_all([admin, reviewer])
        session.commit()
        admin_id, reviewer_id = admin.id, reviewer.id

    admin_token = client.post(
        "/api/auth/login",
        json={"email": "management-admin@example.com", "password": "admin-password"},
    ).json()["access_token"]
    reviewer_token = client.post(
        "/api/auth/login",
        json={"email": "synthetic-reviewer@example.com", "password": "reviewer-password"},
    ).json()["access_token"]

    listed = client.get(
        "/api/auth/users?role=REVIEWER&is_active=true&search=Synthetic",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == reviewer_id
    assert "password_hash" not in listed.json()["items"][0]
    assert client.get(
        "/api/auth/users", headers={"Authorization": f"Bearer {reviewer_token}"}
    ).status_code == 403
    assert client.get("/api/auth/users").status_code == 401

    self_deactivation = client.patch(
        f"/api/auth/users/{admin_id}",
        json={"is_active": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert self_deactivation.status_code == 400
    self_demotion = client.patch(
        f"/api/auth/users/{admin_id}",
        json={"role": "REVIEWER"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert self_demotion.status_code == 400

    role_update = client.patch(
        f"/api/auth/users/{reviewer_id}",
        json={"role": "ADMIN"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert role_update.status_code == 200
    with TestingSessionLocal() as session:
        event = session.query(AuditEvent).filter_by(
            action="user.updated", entity_id=str(reviewer_id)
        ).one()
        assert '"role"' in event.audit_metadata


def test_user_management_rejects_unknown_roles():
    admin = User(
        full_name="Role Test Admin",
        email="role-test-admin@example.com",
        password_hash=get_password_hash("admin-password"),
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    with TestingSessionLocal() as session:
        session.add(admin)
        session.commit()
        admin_id = admin.id
    token = client.post(
        "/api/auth/login",
        json={"email": "role-test-admin@example.com", "password": "admin-password"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    invalid_create = client.post(
        "/api/auth/users",
        json={"full_name": "Invalid Role", "email": "invalid-role@example.com", "password": "unused", "role": "SUPERUSER"},
        headers=headers,
    )
    invalid_update = client.patch(
        f"/api/auth/users/{admin_id}",
        json={"role": "SUPERUSER"},
        headers=headers,
    )
    weak_password = client.post(
        "/api/auth/users",
        json={"full_name": "Weak Password", "email": "weak-password@example.com", "password": "short-pass", "role": "REVIEWER"},
        headers=headers,
    )
    assert invalid_create.status_code == 422
    assert invalid_update.status_code == 422
    assert weak_password.status_code == 422
