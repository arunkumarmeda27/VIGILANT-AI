"""add consistency runs and preserve result history

Revision ID: b8f5c2d91a44
Revises: 3f7d8fdf3df0
Create Date: 2026-10-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8f5c2d91a44"
down_revision: Union[str, None] = "3f7d8fdf3df0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "consistency_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="completed"),
        sa.Column("comparisons_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_consistency_runs_id", "consistency_runs", ["id"])
    op.create_index("ix_consistency_runs_application_id", "consistency_runs", ["application_id"])
    op.create_index("ix_consistency_runs_user_id", "consistency_runs", ["user_id"])

    op.add_column(
        "document_consistency_results",
        sa.Column("run_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "document_consistency_results",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    bind = op.get_bind()
    results = sa.table(
        "document_consistency_results",
        sa.column("id", sa.Integer()),
        sa.column("application_id", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("run_id", sa.Integer()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    applications = bind.execute(
        sa.select(results.c.application_id).distinct()
    ).scalars()
    for application_id in applications:
        result_rows = bind.execute(
            sa.select(results.c.id, results.c.created_at).where(
                results.c.application_id == application_id
            )
        ).all()
        created_at = min((row.created_at for row in result_rows if row.created_at), default=None)
        run_values = {
            "application_id": application_id,
            "status": "completed",
            "comparisons_count": len(result_rows),
        }
        if created_at is not None:
            run_values["created_at"] = created_at
            run_values["updated_at"] = created_at
        consistency_runs = sa.Table(
            "consistency_runs", sa.MetaData(), autoload_with=bind
        )
        run_id = bind.execute(
            sa.insert(consistency_runs).values(**run_values)
        ).inserted_primary_key[0]
        bind.execute(
            results.update()
            .where(results.c.application_id == application_id)
            .values(run_id=run_id, updated_at=created_at or sa.func.current_timestamp())
        )

    with op.batch_alter_table("document_consistency_results") as batch_op:
        batch_op.alter_column("run_id", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        )
        batch_op.create_foreign_key(
            "fk_document_consistency_results_run_id_consistency_runs",
            "consistency_runs",
            ["run_id"],
            ["id"],
        )
    op.create_index(
        "ix_document_consistency_results_run_id",
        "document_consistency_results",
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_consistency_results_run_id", table_name="document_consistency_results")
    with op.batch_alter_table("document_consistency_results") as batch_op:
        batch_op.drop_constraint(
            "fk_document_consistency_results_run_id_consistency_runs",
            type_="foreignkey",
        )
        batch_op.drop_column("run_id")
        batch_op.drop_column("updated_at")
    op.drop_index("ix_consistency_runs_user_id", table_name="consistency_runs")
    op.drop_index("ix_consistency_runs_application_id", table_name="consistency_runs")
    op.drop_index("ix_consistency_runs_id", table_name="consistency_runs")
    op.drop_table("consistency_runs")
