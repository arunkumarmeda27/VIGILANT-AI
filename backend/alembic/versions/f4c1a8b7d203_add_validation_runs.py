"""add persisted application validation runs

Revision ID: f4c1a8b7d203
Revises: a71c9f4e2b36
Create Date: 2026-03-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4c1a8b7d203"
down_revision: Union[str, None] = "a71c9f4e2b36"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "validation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_status", sa.String(length=50), nullable=False),
        sa.Column("outcome", sa.String(length=50), nullable=False),
        sa.Column("stage_outcomes", sa.JSON(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("evaluated_rules_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("not_evaluated_rules_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("not_applicable_rules_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_validation_runs_id", "validation_runs", ["id"])
    op.create_index("ix_validation_runs_application_id", "validation_runs", ["application_id"])
    op.create_index("ix_validation_runs_user_id", "validation_runs", ["user_id"])

    op.create_table(
        "validation_run_assessments",
        sa.Column(
            "validation_run_id",
            sa.Integer(),
            sa.ForeignKey("validation_runs.id"),
            primary_key=True,
        ),
        sa.Column(
            "assessment_id",
            sa.Integer(),
            sa.ForeignKey("compliance_assessments.id"),
            primary_key=True,
        ),
    )

    op.add_column(
        "consistency_runs",
        sa.Column(
            "validation_run_id",
            sa.Integer(),
            sa.ForeignKey("validation_runs.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_consistency_runs_validation_run_id",
        "consistency_runs",
        ["validation_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_consistency_runs_validation_run_id", table_name="consistency_runs")
    op.drop_column("consistency_runs", "validation_run_id")
    op.drop_table("validation_run_assessments")
    op.drop_index("ix_validation_runs_user_id", table_name="validation_runs")
    op.drop_index("ix_validation_runs_application_id", table_name="validation_runs")
    op.drop_index("ix_validation_runs_id", table_name="validation_runs")
    op.drop_table("validation_runs")
