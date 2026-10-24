import importlib.util
from pathlib import Path
from datetime import datetime

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    inspect,
    insert,
    select,
)


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "b8f5c2d91a44_add_consistency_runs.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("consistency_runs_migration", MIGRATION_PATH)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_consistency_migration_backfills_existing_results_without_data_loss(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'consistency-migration.db'}")
    metadata = MetaData()
    Table("applications", metadata, Column("id", Integer, primary_key=True))
    Table("users", metadata, Column("id", Integer, primary_key=True))
    Table(
        "documents",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("application_id", Integer, ForeignKey("applications.id"), nullable=False),
    )
    results = Table(
        "document_consistency_results",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("application_id", Integer, ForeignKey("applications.id"), nullable=False),
        Column("field", String(100), nullable=False),
        Column("category", String(50), nullable=False),
        Column("val1", String),
        Column("val2", String),
        Column("norm1", String),
        Column("norm2", String),
        Column("doc1_id", Integer, ForeignKey("documents.id"), nullable=False),
        Column("doc2_id", Integer, ForeignKey("documents.id"), nullable=False),
        Column("explanation", Text, nullable=False),
        Column("human_review_recommended", Boolean, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(insert(metadata.tables["applications"]), [{"id": 1}])
        connection.execute(insert(metadata.tables["documents"]), [
            {"id": 10, "application_id": 1},
            {"id": 11, "application_id": 1},
        ])
        connection.execute(insert(results), [
            {
                "id": 101,
                "application_id": 1,
                "field": "institution_name",
                "category": "MATCH",
                "val1": "Institute A",
                "val2": "Institute A",
                "norm1": "institute a",
                "norm2": "institute a",
                "doc1_id": 10,
                "doc2_id": 11,
                "explanation": "Values match.",
                "human_review_recommended": False,
                "created_at": datetime(2026, 1, 1),
            },
            {
                "id": 102,
                "application_id": 1,
                "field": "registration_number",
                "category": "INSUFFICIENT_EVIDENCE",
                "val1": "REG-1",
                "val2": None,
                "norm1": "reg-1",
                "norm2": None,
                "doc1_id": 10,
                "doc2_id": 11,
                "explanation": "Only one value exists.",
                "human_review_recommended": True,
                "created_at": datetime(2026, 1, 2),
            },
        ])

    migration = load_migration()
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()

    inspector = inspect(engine)
    migrated_columns = {column["name"]: column for column in inspector.get_columns("document_consistency_results")}
    assert migrated_columns["run_id"]["nullable"] is False
    assert migrated_columns["updated_at"]["nullable"] is False
    assert {fk["referred_table"] for fk in inspector.get_foreign_keys("document_consistency_results")} == {
        "applications", "documents", "consistency_runs"
    }
    run_columns = {column["name"]: column for column in inspector.get_columns("consistency_runs")}
    assert run_columns["application_id"]["nullable"] is False
    assert run_columns["user_id"]["nullable"] is True
    assert run_columns["created_at"]["nullable"] is False
    assert run_columns["updated_at"]["nullable"] is False
    assert {fk["referred_table"] for fk in inspector.get_foreign_keys("consistency_runs")} == {
        "applications", "users"
    }

    migrated_metadata = MetaData()
    migrated_results = Table(
        "document_consistency_results", migrated_metadata, autoload_with=engine
    )
    migrated_runs = Table("consistency_runs", migrated_metadata, autoload_with=engine)
    with engine.connect() as connection:
        result_rows = connection.execute(
            select(
                migrated_results.c.id,
                migrated_results.c.application_id,
                migrated_results.c.field,
                migrated_results.c.category,
                migrated_results.c.val1,
                migrated_results.c.val2,
                migrated_results.c.explanation,
                migrated_results.c.human_review_recommended,
                migrated_results.c.run_id,
            ).order_by(migrated_results.c.id)
        ).mappings().all()
        runs = connection.execute(select(migrated_runs)).mappings().all()

    assert [row["id"] for row in result_rows] == [101, 102]
    assert [row["field"] for row in result_rows] == ["institution_name", "registration_number"]
    assert result_rows[0]["val1"] == "Institute A"
    assert result_rows[1]["human_review_recommended"] is True
    assert all(row["application_id"] == 1 and row["run_id"] == runs[0]["id"] for row in result_rows)
    assert len(runs) == 1
    assert runs[0]["comparisons_count"] == 2

    engine.dispose()


def test_finding_reviews_migration_adds_history_table_without_changing_findings(tmp_path):
    migration_path = Path(__file__).parents[1] / "alembic" / "versions" / "c4d7e9a1b602_add_finding_reviews.py"
    spec = importlib.util.spec_from_file_location("finding_reviews_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'finding-reviews-migration.db'}")
    metadata = MetaData()
    users = Table("users", metadata, Column("id", Integer, primary_key=True))
    findings = Table("findings", metadata, Column("id", Integer, primary_key=True))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(users), {"id": 1})
        connection.execute(insert(findings), {"id": 9})
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
    inspector = inspect(engine)
    assert "finding_reviews" in inspector.get_table_names()
    assert {fk["referred_table"] for fk in inspector.get_foreign_keys("finding_reviews")} == {"findings", "users"}
    review_columns = {column["name"]: column for column in inspector.get_columns("finding_reviews")}
    assert review_columns["finding_id"]["nullable"] is False
    assert review_columns["reviewer_id"]["nullable"] is False
    with engine.connect() as connection:
        assert connection.execute(select(findings.c.id)).scalars().all() == [9]
    engine.dispose()
