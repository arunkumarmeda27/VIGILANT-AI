"""add versioned document type registry

Revision ID: d29f6a4c120e
Revises: f4c1a8b7d203
Create Date: 2026-10-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d29f6a4c120e"
down_revision: Union[str, None] = "f4c1a8b7d203"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_CATEGORIES = (
    (
        "fire_safety_certificate",
        "Fire Safety Certificate",
        ["fire safety certificate", "fire clearance certificate", "fire department", "fire and emergency services"],
    ),
    (
        "faculty_qualification_certificate",
        "Faculty Qualification Certificate",
        ["faculty qualification", "educational qualification", "degree certificate", "university transcript"],
    ),
    (
        "accreditation_certificate",
        "Accreditation Certificate",
        ["accreditation certificate", "national board of accreditation", "nba accreditation", "naac accreditation"],
    ),
)

LEGACY_SCHEMA = {
    "fields": [
        {
            "id": field_id,
            "label": label,
            "data_type": "string" if field_id in {"institution_name", "certificate_number"} else "date",
            "required": False,
            "normalization": {"trim": True, "case": "preserve", "remove_whitespace": False},
            "constraints": {},
        }
        for field_id, label in (
            ("institution_name", "Institution name"),
            ("certificate_number", "Certificate number"),
            ("issue_date", "Issue date"),
            ("expiry_date", "Expiry date"),
        )
    ]
}


def upgrade() -> None:
    op.create_table(
        "document_types",
        sa.Column("id", sa.String(length=100), primary_key=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("family", sa.String(length=100), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("supported_file_formats", sa.JSON(), nullable=False),
        sa.Column("supported_languages", sa.JSON(), nullable=False),
        sa.Column("application_categories", sa.JSON(), nullable=False),
        sa.Column("regulatory_rule_references", sa.JSON(), nullable=False),
        sa.Column("issuing_authority", sa.JSON(), nullable=True),
        sa.Column("verification_config", sa.JSON(), nullable=True),
        sa.Column("expiry_config", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "document_schema_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_type_id", sa.String(length=100), sa.ForeignKey("document_types.id"), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("activated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("document_type_id", "schema_version", name="uq_document_schema_type_version"),
    )
    op.create_index(
        "ix_document_schema_versions_document_type_id",
        "document_schema_versions",
        ["document_type_id"],
    )
    op.create_index("ix_document_schema_versions_id", "document_schema_versions", ["id"])

    op.add_column("documents", sa.Column("processed_doc_type", sa.String(length=100), nullable=True))
    op.add_column("documents", sa.Column("predicted_doc_type", sa.String(length=100), nullable=True))
    op.add_column(
        "documents",
        sa.Column(
            "schema_version_id",
            sa.Integer(),
            sa.ForeignKey("document_schema_versions.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_documents_schema_version_id", "documents", ["schema_version_id"])

    op.create_table(
        "document_type_corrections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("previous_document_type", sa.String(length=100), nullable=False),
        sa.Column("corrected_document_type", sa.String(length=100), sa.ForeignKey("document_types.id"), nullable=False),
        sa.Column("original_prediction", sa.String(length=100), nullable=True),
        sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_document_type_corrections_id", "document_type_corrections", ["id"])
    op.create_index("ix_document_type_corrections_document_id", "document_type_corrections", ["document_id"])

    document_types = sa.table(
        "document_types",
        sa.column("id", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("category", sa.String()),
        sa.column("family", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("aliases", sa.JSON()),
        sa.column("supported_file_formats", sa.JSON()),
        sa.column("supported_languages", sa.JSON()),
        sa.column("application_categories", sa.JSON()),
        sa.column("regulatory_rule_references", sa.JSON()),
        sa.column("status", sa.String()),
    )
    schema_versions = sa.table(
        "document_schema_versions",
        sa.column("document_type_id", sa.String()),
        sa.column("schema_version", sa.String()),
        sa.column("definition", sa.JSON()),
        sa.column("status", sa.String()),
    )
    for type_id, display_name, aliases in LEGACY_CATEGORIES:
        op.bulk_insert(
            document_types,
            [{
                "id": type_id,
                "display_name": display_name,
                "category": "legacy_preview",
                "family": "certificate",
                "description": (
                    "Imported from the legacy synthetic document-classification configuration. "
                    "This draft is not an authoritative document or regulatory definition."
                ),
                "aliases": aliases,
                "supported_file_formats": ["pdf"],
                "supported_languages": ["en"],
                "application_categories": [],
                "regulatory_rule_references": [],
                "status": "draft",
            }],
        )
        op.bulk_insert(
            schema_versions,
            [{
                "document_type_id": type_id,
                "schema_version": "1.0.0",
                "definition": LEGACY_SCHEMA,
                "status": "draft",
            }],
        )


def downgrade() -> None:
    op.drop_index("ix_document_type_corrections_document_id", table_name="document_type_corrections")
    op.drop_index("ix_document_type_corrections_id", table_name="document_type_corrections")
    op.drop_table("document_type_corrections")
    op.drop_index("ix_documents_schema_version_id", table_name="documents")
    op.drop_column("documents", "schema_version_id")
    op.drop_column("documents", "predicted_doc_type")
    op.drop_column("documents", "processed_doc_type")
    op.drop_index("ix_document_schema_versions_document_type_id", table_name="document_schema_versions")
    op.drop_index("ix_document_schema_versions_id", table_name="document_schema_versions")
    op.drop_table("document_schema_versions")
    op.drop_table("document_types")
