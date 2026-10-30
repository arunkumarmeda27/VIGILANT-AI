"""add persisted image evidence quality history

Revision ID: f16b8c2d904a
Revises: d29f6a4c120e
Create Date: 2026-10-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f16b8c2d904a"
down_revision: Union[str, None] = "d29f6a4c120e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "image_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("uploader_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("validation_run_id", sa.Integer(), sa.ForeignKey("validation_runs.id"), nullable=True),
        sa.Column("storage_key", sa.String(length=512), nullable=False, unique=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("processing_status", sa.String(length=50), nullable=False),
        sa.Column("analysis_result", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_image_evidence_id", "image_evidence", ["id"])
    op.create_index("ix_image_evidence_application_id", "image_evidence", ["application_id"])
    op.create_index("ix_image_evidence_uploader_id", "image_evidence", ["uploader_id"])
    op.create_index("ix_image_evidence_validation_run_id", "image_evidence", ["validation_run_id"])


def downgrade() -> None:
    op.drop_index("ix_image_evidence_validation_run_id", table_name="image_evidence")
    op.drop_index("ix_image_evidence_uploader_id", table_name="image_evidence")
    op.drop_index("ix_image_evidence_application_id", table_name="image_evidence")
    op.drop_index("ix_image_evidence_id", table_name="image_evidence")
    op.drop_table("image_evidence")
