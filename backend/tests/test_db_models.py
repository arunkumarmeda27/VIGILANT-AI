from app.core.security import get_password_hash, verify_password
from app.db.session import get_db
from app.models.models import Base, User, Application
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pytest

# Use a mock engine for model tests to avoid needing a real DB
# In a real scenario, we would use a sqlite in-memory DB for these tests
engine = create_engine("sqlite:///:memory:")
TestingSessionLocal = sessionmaker(bind=engine)

def test_models_import():
    """Verify that all models can be imported without circular dependencies."""
    assert User is not None
    assert Application is not None

def test_metadata_contains_tables():
    """Verify that SQLAlchemy metadata contains the expected tables."""
    tables = Base.metadata.tables.keys()
    expected_tables = [
        "users", "applications", "documents", "findings",
        "finding_reviews",
        "review_comments", "compliance_rules", "compliance_assessments", "audit_events"
    ]
    for table in expected_tables:
        assert table in tables

def test_security_still_works():
    """Verify Argon2 security tests still pass."""
    password = "test_password"
    hashed = get_password_hash(password)
    assert verify_password(password, hashed) is True
