import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db.base import Base
from app.core.security import get_password_hash
from app.models.enums import UserRole
from app.models.models import User
from app.schemas.auth import UserCreate
from app.db.session import get_db as real_get_db

# Use a single shared test database for the whole suite to avoid contention
SQLALCHEMY_DATABASE_URL = "sqlite:///test_suite.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
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
            "password": "userpass",
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
