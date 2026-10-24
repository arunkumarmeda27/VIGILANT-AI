"""add_cross_document_consistency

Revision ID: 3f7d8fdf3df0
Revises: c31e8a6d904b
Create Date: 2026-10-24 21:13:56.001753

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f7d8fdf3df0'
down_revision: Union[str, None] = 'c31e8a6d904b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'document_consistency_results',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('application_id', sa.Integer(), sa.ForeignKey('applications.id', ondelete='CASCADE'), nullable=False),
        sa.Column('field', sa.String(100), nullable=False),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('val1', sa.String, nullable=True),
        sa.Column('val2', sa.String, nullable=True),
        sa.Column('norm1', sa.String, nullable=True),
        sa.Column('norm2', sa.String, nullable=True),
        sa.Column('doc1_id', sa.Integer(), sa.ForeignKey('documents.id'), nullable=False),
        sa.Column('doc2_id', sa.Integer(), sa.ForeignKey('documents.id'), nullable=False),
        sa.Column('explanation', sa.Text, nullable=False),
        sa.Column('human_review_recommended', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index(op.f('ix_document_consistency_results_id'), 'document_consistency_results', ['id'], unique=False)
    op.create_index(op.f('ix_document_consistency_results_application_id'), 'document_consistency_results', ['application_id'], unique=False)

def downgrade() -> None:
    op.drop_table('document_consistency_results')

