"""add append-only human reviews for compliance assessments

Revision ID: a71c9f4e2b36
Revises: c4d7e9a1b602
Create Date: 2026-10-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a71c9f4e2b36"
down_revision: Union[str, None] = "c4d7e9a1b602"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "compliance_assessment_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "assessment_id",
            sa.Integer(),
            sa.ForeignKey("compliance_assessments.id"),
            nullable=False,
        ),
        sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("outcome", sa.String(length=50), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_compliance_assessment_reviews_id", "compliance_assessment_reviews", ["id"])
    op.create_index(
        "ix_compliance_assessment_reviews_assessment_id",
        "compliance_assessment_reviews",
        ["assessment_id"],
    )
    op.create_index(
        "ix_compliance_assessment_reviews_reviewer_id",
        "compliance_assessment_reviews",
        ["reviewer_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_compliance_assessment_reviews_reviewer_id", table_name="compliance_assessment_reviews")
    op.drop_index("ix_compliance_assessment_reviews_assessment_id", table_name="compliance_assessment_reviews")
    op.drop_index("ix_compliance_assessment_reviews_id", table_name="compliance_assessment_reviews")
    op.drop_table("compliance_assessment_reviews")
