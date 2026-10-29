from getpass import getpass
import sys

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import func, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_password_hash
from app.db.session import SessionLocal
from app.models.enums import UserRole
from app.models.models import User


MINIMUM_PASSWORD_LENGTH = 12
ADVISORY_LOCK_NAMESPACE = 1447640905
ADVISORY_LOCK_KEY = 1280134740


class BootstrapError(Exception):
    pass


def validate_database_target() -> None:
    if settings.APP_ENV.strip().lower() != "development":
        raise BootstrapError("Administrator bootstrap is allowed only in development.")

    try:
        database_url = make_url(settings.DATABASE_URL)
    except Exception:
        raise BootstrapError("The configured database target is invalid.") from None

    if (
        database_url.get_backend_name() != "postgresql"
        or (database_url.host or "").lower() not in {"localhost", "127.0.0.1"}
        or database_url.database != "vigilant_db"
        or database_url.port not in {None, 5432}
    ):
        raise BootstrapError(
            "Refusing to run: the configured target is not local development PostgreSQL."
        )


def administrator_exists(db: Session) -> bool:
    return (
        db.query(User.id)
        .filter(User.role == UserRole.ADMIN.value)
        .first()
        is not None
    )


def email_exists(db: Session, email: str) -> bool:
    return (
        db.query(User.id)
        .filter(func.lower(User.email) == email)
        .first()
        is not None
    )


def prompt_identity() -> tuple[str, str, str]:
    full_name = input("Administrator name: ").strip()
    if not full_name or len(full_name) > 255:
        raise BootstrapError("Name must contain between 1 and 255 characters.")

    email_input = input("Administrator email: ").strip()
    try:
        email = str(TypeAdapter(EmailStr).validate_python(email_input)).lower()
    except ValidationError:
        raise BootstrapError("Enter a valid email address.") from None

    password = getpass("Administrator password (minimum 12 characters): ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise BootstrapError("Passwords do not match.")
    non_whitespace_characters = sum(not character.isspace() for character in password)
    if non_whitespace_characters < MINIMUM_PASSWORD_LENGTH:
        raise BootstrapError(
            f"Password must contain at least {MINIMUM_PASSWORD_LENGTH} non-whitespace characters."
        )

    return full_name, email, password


def create_first_administrator(full_name: str, email: str, password: str) -> None:
    password_hash = get_password_hash(password)

    with SessionLocal() as db:
        try:
            with db.begin():
                db.execute(
                    text("SELECT pg_advisory_xact_lock(:namespace, :lock_key)"),
                    {
                        "namespace": ADVISORY_LOCK_NAMESPACE,
                        "lock_key": ADVISORY_LOCK_KEY,
                    },
                )

                if administrator_exists(db):
                    raise BootstrapError(
                        "An administrator already exists; no account was created."
                    )
                if email_exists(db, email):
                    raise BootstrapError(
                        "That email is already in use; no account was created."
                    )

                db.add(
                    User(
                        full_name=full_name,
                        email=email,
                        password_hash=password_hash,
                        role=UserRole.ADMIN.value,
                        is_active=True,
                        institution_id=None,
                    )
                )
                db.flush()
        except BootstrapError:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            raise BootstrapError(
                "Database operation failed; no administrator was created."
            ) from None


def main() -> int:
    try:
        validate_database_target()

        with SessionLocal() as db:
            if administrator_exists(db):
                raise BootstrapError(
                    "An administrator already exists; bootstrap cannot run again."
                )

        full_name, email, password = prompt_identity()

        with SessionLocal() as db:
            if email_exists(db, email):
                raise BootstrapError(
                    "That email is already in use; no account was created."
                )

        create_first_administrator(full_name, email, password)
        print("Administrator account created successfully.")
        return 0
    except (BootstrapError, EOFError, KeyboardInterrupt) as exc:
        if isinstance(exc, BootstrapError):
            print(f"Bootstrap stopped: {exc}", file=sys.stderr)
        else:
            print("Bootstrap cancelled; no administrator was created.", file=sys.stderr)
        return 1
    except Exception:
        print(
            "Bootstrap failed; no database details or credentials were displayed.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
