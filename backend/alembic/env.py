from logging.config import fileConfig
from sqlalchemy import pool, create_engine
from alembic import context

# Import the app settings and models
from app.core.config import settings
from app.db.base import Base
from app.models.models import (
    User,
    Application,
    Document,
    Finding,
    FindingReview,
    ReviewComment,
    ComplianceRule,
    ComplianceAssessment,
    ComplianceAssessmentReview,
    AuditEvent,
)

config = context.config

if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except Exception:
        pass

# Set the SQLAlchemy model metadata for auto-generation
target_metadata = Base.metadata

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = settings.DATABASE_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    # Use create_engine directly to avoid the 'sqlalchemy.dialects:driver' plugin error
    connectable = create_engine(
        settings.DATABASE_URL,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
