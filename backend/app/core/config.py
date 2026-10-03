"""Application settings, loaded from environment variables (or a local .env file).

Nothing secret is hard-coded here. Every secret must come from the environment.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- General ---
    ENVIRONMENT: str = "development"  # "development" | "production" | "test"
    APP_NAME: str = "Expense Tracker API"
    APP_TIMEZONE: str = "Asia/Kolkata"  # used for "today" and "this month" on the dashboard
    ENABLE_DOCS: bool = True  # serve Swagger UI at /docs

    # --- Database ---
    DATABASE_URL: str

    # --- Auth ---
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    ALLOW_REGISTRATION: bool = True  # turn off after creating your own account

    # --- HTTP ---
    CORS_ORIGINS: str = "http://localhost:5173"  # comma separated
    MAX_REQUEST_BYTES: int = 64 * 1024  # 64 KB is plenty for OCR text

    # --- Rate limits (requests per minute) ---
    IMPORT_RATE_LIMIT_PER_MINUTE: int = 30
    LOGIN_RATE_LIMIT_PER_MINUTE: int = 10

    @field_validator("DATABASE_URL")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        """Supabase/Render give `postgres://` or `postgresql://` URLs.
        SQLAlchemy needs to be told to use the psycopg (v3) driver."""
        value = value.strip()
        if value.startswith("postgres://"):
            value = "postgresql://" + value[len("postgres://"):]
        if value.startswith("postgresql://"):
            value = "postgresql+psycopg://" + value[len("postgresql://"):]
        return value

    @field_validator("JWT_SECRET")
    @classmethod
    def jwt_secret_must_be_strong(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters long")
        return value

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
