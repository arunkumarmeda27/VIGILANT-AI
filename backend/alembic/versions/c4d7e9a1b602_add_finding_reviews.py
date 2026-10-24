"""add append-only reviewer decisions for findings

Revision ID: c4d7e9a1b602
Revises: b8f5c2d91a44
Create Date: 2026-10-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d7e9a1b602"
down_revision: Union[str, None] = "b8f5c2d91a44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "finding_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("finding_id", sa.Integer(), sa.ForeignKey("findings.id"), nullable=False),
        sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("outcome", sa.String(length=50), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_finding_reviews_id", "finding_reviews", ["id"])
    op.create_index("ix_finding_reviews_finding_id", "finding_reviews", ["finding_id"])
    op.create_index("ix_finding_reviews_reviewer_id", "finding_reviews", ["reviewer_id"])


def downgrade() -> None:
    op.drop_index("ix_finding_reviews_reviewer_id", table_name="finding_reviews")
    op.drop_index("ix_finding_reviews_finding_id", table_name="finding_reviews")
    op.drop_index("ix_finding_reviews_id", table_name="finding_reviews")
    op.drop_table("finding_reviews")
