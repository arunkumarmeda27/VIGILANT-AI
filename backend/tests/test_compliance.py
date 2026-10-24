import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.security import get_password_hash
from app.db.base import Base
from app.db.session import get_db as real_get_db
from app.main import app
from app.models.enums import UserRole
from app.models.models import (
    Application,
    ComplianceAssessment,
    ComplianceRule,
    Institution,
    User,
)


client = TestClient(app)


@pytest.fixture
def test_database(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'compliance-tests.db'}",
        connect_args={"check_same_thread": False},
    )
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = session_local()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setitem(app.dependency_overrides, real_get_db, override_get_db)
    Base.metadata.create_all(bind=engine)
    yield session_local
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def create_user(session_local, email, role, institution_id=None):
    with session_local() as db:
        user = User(
            full_name=email,
            email=email,
            password_hash=get_password_hash("compliance-test-password"),
            role=role.value,
            is_active=True,
            institution_id=institution_id,
        )
        db.add(user)
        db.commit()
        return user.id


def login(email):
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "compliance-test-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def seed_assessment(session_local, application_reference, institution_id, reviewer_id):
    with session_local() as db:
        application = Application(
            reference=application_reference,
            entity_name=f"{application_reference} Organization",
            app_type="Synthetic",
            institution_id=institution_id,
        )
        rule = ComplianceRule(
            rule_code=f"TEST-{application_reference}",
            title="Synthetic assessment rule",
            description="Test data only",
            category="synthetic",
            is_active=True,
        )
        db.add_all([application, rule])
        db.flush()
        assessment = ComplianceAssessment(
            application_id=application.id,
            rule_id=rule.id,
            status="Pending",
            explanation="Synthetic test assessment.",
            reviewer_id=reviewer_id,
        )
        db.add(assessment)
        db.commit()
        return application.id


def test_compliance_assessments_are_role_scoped(test_database):
    with test_database() as db:
        first = Institution(name="First compliance institution")
        second = Institution(name="Second compliance institution")
        db.add_all([first, second])
        db.commit()
        first_institution_id, second_institution_id = first.id, second.id

    institution_user_id = create_user(
        test_database,
        "first-institution@example.com",
        UserRole.INSTITUTION_USER,
        first_institution_id,
    )
    other_user_id = create_user(
        test_database,
        "second-institution@example.com",
        UserRole.INSTITUTION_USER,
        second_institution_id,
    )
    reviewer_id = create_user(
        test_database,
        "assigned-reviewer@example.com",
        UserRole.REVIEWER,
    )
    create_user(
        test_database,
        "unassigned-reviewer@example.com",
        UserRole.REVIEWER,
    )
    seed_assessment(test_database, "COMP-A", first_institution_id, reviewer_id)
    seed_assessment(test_database, "COMP-B", second_institution_id, other_user_id)

    first_response = client.get(
        "/api/compliance-assessments/",
        headers=login("first-institution@example.com"),
    )
    reviewer_response = client.get(
        "/api/compliance-assessments/",
        headers=login("assigned-reviewer@example.com"),
    )
    unassigned_response = client.get(
        "/api/compliance-assessments/",
        headers=login("unassigned-reviewer@example.com"),
    )

    assert first_response.status_code == 200
    assert [item["application_reference"] for item in first_response.json()["items"]] == ["COMP-A"]
    assert reviewer_response.status_code == 200
    assert [item["application_reference"] for item in reviewer_response.json()["items"]] == ["COMP-A"]
    assert reviewer_response.json()["items"][0]["reviewer_name"] == "assigned-reviewer@example.com"
    assert unassigned_response.status_code == 200
    assert unassigned_response.json() == {"items": [], "total": 0}


def test_compliance_assessments_are_admin_visible_and_paginated(test_database):
    create_user(test_database, "compliance-admin@example.com", UserRole.ADMIN)
    with test_database() as db:
        institution = Institution(name="Admin compliance institution")
        db.add(institution)
        db.commit()
        institution_id = institution.id
    seed_assessment(test_database, "COMP-ADMIN", institution_id, None)

    response = client.get(
        "/api/compliance-assessments/?limit=1&offset=0",
        headers=login("compliance-admin@example.com"),
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert len(response.json()["items"]) == 1
    assert response.json()["items"][0]["rule_code"] == "TEST-COMP-ADMIN"
    assert client.get("/api/compliance-assessments/").status_code == 401
