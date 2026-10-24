from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Union
from pathlib import Path

_DEVELOPMENT_JWT_SECRET = "your-super-secret-key-change-me"


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://user:password@localhost:5432/vigilant_db"

    # Security
    JWT_SECRET_KEY: str = _DEVELOPMENT_JWT_SECRET
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # Uploaded documents are stored outside the frontend's public asset directory.
    DOCUMENT_STORAGE_DIR: Path = Path(__file__).resolve().parents[2] / "document_storage"
    DOCUMENT_MAX_SIZE_BYTES: int = 10 * 1024 * 1024
    DOCUMENT_PROCESSING_MAX_PAGES: int = 50
    DOCUMENT_PROCESSING_MAX_SECONDS: int = 60
    DOCUMENT_PROCESSING_MAX_TEXT_CHARS: int = 1_000_000
    DOCUMENT_OCR_PAGE_TIMEOUT_SECONDS: int = 12
    TESSERACT_CMD: str | None = None

    # API
    # We use Union to support both a comma-separated string from .env and a list in code
    CORS_ORIGINS: Union[str, List[str]] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    APP_ENV: str = "development"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def validate_jwt_secret(self):
        if self.APP_ENV.strip().lower() != "development":
            if (
                self.JWT_SECRET_KEY == _DEVELOPMENT_JWT_SECRET
                or len(self.JWT_SECRET_KEY.encode("utf-8")) < 32
            ):
                raise ValueError(
                    "JWT_SECRET_KEY must be configured with at least 32 characters "
                    "outside development"
                )
        return self


settings = Settings()

# Normalization: ensure CORS_ORIGINS is always a list of strings
if isinstance(settings.CORS_ORIGINS, str):
    settings.CORS_ORIGINS = [o.strip() for o in settings.CORS_ORIGINS.split(",")]
