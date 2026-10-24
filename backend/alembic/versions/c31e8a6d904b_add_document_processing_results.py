"""add_document_processing_results

Revision ID: c31e8a6d904b
Revises: a7d2c1e9b460
Create Date: 2026-10-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c31e8a6d904b"
down_revision: Union[str, None] = "a7d2c1e9b460"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("processing_result", sa.JSON(), nullable=True))
    op.add_column("documents", sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "processed_at")
    op.drop_column("documents", "processing_result")
