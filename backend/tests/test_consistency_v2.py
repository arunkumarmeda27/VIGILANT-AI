import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db.base import Base
from app.core.security import get_password_hash
from app.models.enums import UserRole
from app.models.models import User, Application, Document, Institution, DocumentConsistencyResult, ConsistencyRun
from app.db.session import get_db as real_get_db
from datetime import datetime, timezone

SQLALCHEMY_DATABASE_URL = "sqlite:///test_consistency_v2.db"

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

app.dependency_overrides[real_get_db] = override_get_db
client = TestClient(app)

@pytest.fixture(scope="function", autouse=True)
def setup_db():
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

def test_validate_consistency_preserves_history():
    inst_id = create_institution()
    user_email = create_test_user(institution_id=inst_id)
    token = get_token(user_email)
    app_id = create_application(inst_id=inst_id)

    # Run 1: Match
    create_processed_document(app_id, "doc1", {
        "institution_name": {"value": "Institute A", "status": "extracted"}
    })
    create_processed_document(app_id, "doc2", {
        "institution_name": {"value": "Institute A", "status": "extracted"}
    })

    resp1 = client.post(
        f"/api/applications/{app_id}/validate-consistency",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp1.status_code == 200
    run_id1 = resp1.json()["run_id"]

    # Run 2: Mismatch (simulating updated document data)
    session = TestingSessionLocal()
    doc2 = session.query(Document).filter(Document.application_id == app_id).all()[1]
    doc2.processing_result["fields"]["institution_name"]["value"] = "Institute B"
    session.commit()
    session.close()

    resp2 = client.post(
        f"/api/applications/{app_id}/validate-consistency",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp2.status_code == 200
    run_id2 = resp2.json()["run_id"]

    assert run_id1 != run_id2

    # Verify both runs exist in DB
    session = TestingSessionLocal()
    runs = session.query(ConsistencyRun).filter(ConsistencyRun.application_id == app_id).all()
    assert len(runs) == 2

    res1 = session.query(DocumentConsistencyResult).filter(DocumentConsistencyResult.run_id == run_id1).first()
    res2 = session.query(DocumentConsistencyResult).filter(DocumentConsistencyResult.run_id == run_id2).first()

    assert res1.category == "MATCH"
    assert res2.category == "CONFIRMED_MISMATCH"
    session.close()

def test_validate_consistency_too_few_documents():
    inst_id = create_institution()
    user_email = create_test_user(institution_id=inst_id)
    token = get_token(user_email)
    app_id = create_application(inst_id=inst_id)

    create_processed_document(app_id, "doc1", {"institution_name": {"value": "A", "status": "extracted"}})

    response = client.post(
        f"/api/applications/{app_id}/validate-consistency",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 400
    assert "at least two processed documents" in response.json()["detail"]
