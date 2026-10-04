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

    # --- LLM fallback for hard-to-read receipts (optional) ---
    OPENAI_API_KEY: str | None = None  # leave empty to disable the fallback
    OPENAI_MODEL: str = "gpt-5.4-mini"
    LLM_FALLBACK_ENABLED: bool = True
    LLM_TIMEOUT_SECONDS: float = 20.0

    # --- Receipt image import (server-side OCR + vision fallback) ---
    MAX_UPLOAD_MB: int = 10  # largest receipt image accepted
    OCR_ENABLED: bool = True
    # Longest image side fed to OCR. 1000 px keeps the OCR engine around 350 MB of RAM
    # (fits Render's free 512 MB instance) and still reads PhonePe receipts reliably.
    OCR_MAX_IMAGE_SIDE: int = 1000
    OCR_MIN_CONFIDENCE: float = 0.80  # average line confidence needed to trust OCR alone
    VISION_FALLBACK_ENABLED: bool = True  # needs OPENAI_API_KEY
    OPENAI_VISION_MODEL: str = "gpt-5.4-mini"
    VISION_TIMEOUT_SECONDS: float = 30.0

    # --- Client IP detection ---
    # Behind Render (Cloudflare in front, X-Forwarded-For is appended to and spoofable),
    # read the header Cloudflare overwrites: "true-client-ip,cf-connecting-ip".
    # Empty = use the direct connection address (local development).
    CLIENT_IP_HEADERS: str = ""

    # --- Admin & account security ---
    ADMIN_SESSION_HOURS: int = 12  # admins must log in again after this
    ADMIN_IDLE_TIMEOUT_MINUTES: int = 60  # ...or after this long without activity
    LOCKOUT_THRESHOLD: int = 5  # failed passwords before an account is temporarily locked
    LOCKOUT_MINUTES: int = 15
    # Promote this EXISTING account to super admin at startup, only while no super admin exists.
    INITIAL_SUPER_ADMIN_EMAIL: str | None = None
    APP_VERSION: str = "1.3.0"

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
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024

    @property
    def client_ip_headers_list(self) -> list[str]:
        return [h.strip().lower() for h in self.CLIENT_IP_HEADERS.split(",") if h.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
