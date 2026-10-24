import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.security import get_password_hash
from app.db.base import Base
from app.db.session import get_db as real_get_db
from app.main import app
from app.models.enums import UserRole
from app.models.models import User
from app.api.routes import ai as ai_routes


TEST_EMAIL = "ai-test@example.com"
TEST_PASSWORD = "ai-test-password"
client = TestClient(app)


@pytest.fixture
def test_database(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ai-tests.db'}",
        connect_args={"check_same_thread": False},
    )
    testing_session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[real_get_db] = override_get_db
    Base.metadata.create_all(bind=engine)
    yield testing_session_local
    app.dependency_overrides.pop(real_get_db, None)
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def create_authenticated_user(test_database):
    with test_database() as db:
        db.add(
            User(
                full_name="AI Test User",
                email=TEST_EMAIL,
                password_hash=get_password_hash(TEST_PASSWORD),
                role=UserRole.INSTITUTION_USER.value,
                is_active=True,
            )
        )
        db.commit()

    response = client.post(
        "/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class StubAnswerGenerator:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.question = None

    def generate_answer(self, question):
        self.question = question
        if self.error:
            raise self.error
        return self.result


def test_ask_requires_authentication():
    response = client.post("/api/ai/ask", json={"question": "Faculty qualifications"})

    assert response.status_code == 401


def test_ask_returns_authenticated_evidence_and_citations(test_database, monkeypatch):
    headers = create_authenticated_user(test_database)
    generator = StubAnswerGenerator(
        result={
            "question": "Faculty qualifications?",
            "status": "source_evidence_found",
            "answer": "Retrieved source passages are shown below.",
            "evidence": [
                {
                    "text": "Required faculty qualification passage.",
                    "source_text": "Full source chunk with qualification conditions.",
                    "evidence_type": "matched_passage",
                    "retrieval_score": 0.82,
                    "citation": {
                        "source_document": "AICTE handbook",
                        "pdf_page": 96,
                        "printed_handbook_page": 68,
                        "chunk_id": "AICTE-P096-C0001",
                    },
                }
            ],
            "warnings": [],
        }
    )
    monkeypatch.setattr(ai_routes, "get_answer_generator", lambda: generator)

    response = client.post(
        "/api/ai/ask",
        headers=headers,
        json={"question": "  Faculty qualifications?  "},
    )

    assert response.status_code == 200
    assert generator.question == "Faculty qualifications?"
    assert response.json()["status"] == "source_evidence_found"
    assert response.json()["evidence"][0]["citation"]["chunk_id"] == "AICTE-P096-C0001"
    assert response.json()["evidence"][0]["source_text"] == (
        "Full source chunk with qualification conditions."
    )


def test_ask_preserves_insufficient_evidence_response(test_database, monkeypatch):
    headers = create_authenticated_user(test_database)
    monkeypatch.setattr(
        ai_routes,
        "get_answer_generator",
        lambda: StubAnswerGenerator(
            result={
                "question": "Unrelated question",
                "status": "insufficient_evidence",
                "answer": "The available retrieved passages do not establish an answer.",
                "evidence": [],
                "warnings": [],
            }
        ),
    )

    response = client.post(
        "/api/ai/ask",
        headers=headers,
        json={"question": "Unrelated question"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_evidence"
    assert response.json()["evidence"] == []


@pytest.mark.parametrize(
    "question",
    ["", "   ", "x" * 1001],
)
def test_ask_rejects_empty_or_excessively_long_questions(
    test_database,
    question,
):
    headers = create_authenticated_user(test_database)

    response = client.post(
        "/api/ai/ask",
        headers=headers,
        json={"question": question},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError("private dataset path"),
        RuntimeError("internal retrieval details"),
    ],
)
def test_ask_returns_controlled_error_when_retrieval_fails(
    test_database,
    monkeypatch,
    error,
):
    headers = create_authenticated_user(test_database)
    monkeypatch.setattr(
        ai_routes,
        "get_answer_generator",
        lambda: StubAnswerGenerator(error=error),
    )

    response = client.post(
        "/api/ai/ask",
        headers=headers,
        json={"question": "Faculty qualifications"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "AI evidence retrieval is temporarily unavailable."
    }
    assert "private dataset path" not in response.text
    assert "internal retrieval details" not in response.text
