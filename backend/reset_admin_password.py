from getpass import getpass
import sys

from sqlalchemy import func, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_password_hash
from app.db.session import SessionLocal
from app.models.enums import UserRole
from app.models.models import User


ADMIN_EMAIL = "Admin@gmail.com"
MINIMUM_PASSWORD_LENGTH = 12
ADVISORY_LOCK_NAMESPACE = 1447640905
ADVISORY_LOCK_KEY = 1280134740


class ResetError(Exception):
    pass


def validate_database_target() -> None:
    if settings.APP_ENV.strip().lower() != "development":
        raise ResetError("Administrator password reset is allowed only in development.")

    try:
        database_url = make_url(settings.DATABASE_URL)
    except Exception:
        raise ResetError("The configured database target is invalid.") from None

    if (
        database_url.get_backend_name() != "postgresql"
        or (database_url.host or "").lower() not in {"localhost", "127.0.0.1"}
        or database_url.database != "vigilant_db"
        or database_url.port not in {None, 5432}
    ):
        raise ResetError(
            "Refusing to run: the configured target is not local development PostgreSQL."
        )


def find_admin(db: Session, *, lock_rows: bool = False) -> User:
    query = db.query(User).filter(
        func.lower(User.email) == ADMIN_EMAIL.lower(),
        User.role == UserRole.ADMIN.value,
    )
    if lock_rows:
        query = query.with_for_update()

    users = query.all()
    if len(users) != 1:
        raise ResetError(
            "Expected exactly one administrator for the configured email; no account was changed."
        )
    return users[0]


def prompt_new_password() -> str:
    password = getpass("New administrator password (minimum 12 characters): ")
    confirmation = getpass("Confirm new password: ")
    if password != confirmation:
        raise ResetError("Passwords do not match.")

    non_whitespace_characters = sum(not character.isspace() for character in password)
    if non_whitespace_characters < MINIMUM_PASSWORD_LENGTH:
        raise ResetError(
            f"Password must contain at least {MINIMUM_PASSWORD_LENGTH} non-whitespace characters."
        )
    return password


def reset_password(password: str) -> None:
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
                user = find_admin(db, lock_rows=True)
                db.execute(
                    text(
                        "UPDATE users SET password_hash = :password_hash "
                        "WHERE id = :user_id"
                    ),
                    {"password_hash": password_hash, "user_id": user.id},
                )
        except ResetError:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            raise ResetError(
                "Database operation failed; the administrator account was not changed."
            ) from None


def main() -> int:
    try:
        validate_database_target()
        with SessionLocal() as db:
            find_admin(db)

        password = prompt_new_password()
        reset_password(password)
        print("Administrator password updated successfully.")
        return 0
    except (ResetError, EOFError, KeyboardInterrupt) as exc:
        if isinstance(exc, ResetError):
            print(f"Password reset stopped: {exc}", file=sys.stderr)
        else:
            print("Password reset cancelled; no account was changed.", file=sys.stderr)
        return 1
    except Exception:
        print(
            "Password reset failed; no database details or credentials were displayed.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
