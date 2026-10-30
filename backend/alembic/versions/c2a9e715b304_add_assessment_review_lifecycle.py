"""add separate assessment review lifecycle status

Revision ID: c2a9e715b304
Revises: f16b8c2d904a
Create Date: 2026-10-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2a9e715b304"
down_revision: Union[str, None] = "f16b8c2d904a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "compliance_assessments",
        sa.Column(
            "review_status",
            sa.String(length=50),
            nullable=False,
            server_default="PENDING_REVIEW",
        ),
    )
    op.create_index(
        "ix_compliance_assessments_review_status",
        "compliance_assessments",
        ["review_status"],
    )
    op.create_table(
        "compliance_assessment_status_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "assessment_id",
            sa.Integer(),
            sa.ForeignKey("compliance_assessments.id"),
            nullable=False,
        ),
        sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("from_status", sa.String(length=50), nullable=False),
        sa.Column("to_status", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_compliance_assessment_status_history_id",
        "compliance_assessment_status_history",
        ["id"],
    )
    op.create_index(
        "ix_compliance_assessment_status_history_assessment_id",
        "compliance_assessment_status_history",
        ["assessment_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_compliance_assessment_status_history_assessment_id",
        table_name="compliance_assessment_status_history",
    )
    op.drop_index(
        "ix_compliance_assessment_status_history_id",
        table_name="compliance_assessment_status_history",
    )
    op.drop_table("compliance_assessment_status_history")
    op.drop_index(
        "ix_compliance_assessments_review_status",
        table_name="compliance_assessments",
    )
    op.drop_column("compliance_assessments", "review_status")
