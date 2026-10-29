"""add_document_file_metadata

Revision ID: a7d2c1e9b460
Revises: 3820188fd198
Create Date: 2026-10-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7d2c1e9b460"
down_revision: Union[str, None] = "3820188fd198"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("sha256", sa.String(length=64), nullable=True))
    op.add_column("documents", sa.Column("file_size", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "file_size")
    op.drop_column("documents", "sha256")
