from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # Load a local .env when present; ignore unrelated keys so the app always boots.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AI Proposal Platform API"
    debug: bool = True
    # Default lets the mock contract / Swagger docs boot without a live DB.
    # The real proposals endpoint still requires a reachable database at request time.
    database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/rfp_proposal_db",
        validation_alias="DATABASE_URL",
    )

    # --- S3 / object storage (Story 2.2) ---
    use_localstack: bool = Field(default=True, validation_alias="USE_LOCALSTACK")
    localstack_endpoint: str = Field(
        default="http://localhost:4566", validation_alias="LOCALSTACK_ENDPOINT"
    )
    s3_bucket_name: str = Field(
        default="proposal-artifacts-local", validation_alias="S3_BUCKET_NAME"
    )
    aws_region: str = Field(default="us-east-1", validation_alias="AWS_DEFAULT_REGION")
    max_upload_bytes: int = Field(
        default=50 * 1024 * 1024, validation_alias="MAX_UPLOAD_BYTES"
    )  # 50 MB — mirrors the frontend drop-zone limit

    # --- Auth / JWT (Story 4.2, pulled forward) ---
    jwt_secret: str = Field(
        default="dev-insecure-change-me", validation_alias="JWT_SECRET"
    )
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(
        default=60 * 24, validation_alias="ACCESS_TOKEN_EXPIRE_MINUTES"
    )

    # --- Celery / Redis worker queue (Story 2.5) ---
    celery_broker_url: str = Field(
        default="redis://localhost:6379/0", validation_alias="CELERY_BROKER_URL"
    )
    celery_result_backend: str = Field(
        default="redis://localhost:6379/1", validation_alias="CELERY_RESULT_BACKEND"
    )
    # When true, tasks run inline (no broker) — used by the integration test.
    celery_task_always_eager: bool = Field(
        default=False, validation_alias="CELERY_TASK_ALWAYS_EAGER"
    )

    # --- Cache (Story 4.4) — separate Redis logical DB from the Celery broker ---
    cache_url: str = Field(default="redis://localhost:6379/2", validation_alias="CACHE_URL")
    cache_ttl_seconds: int = Field(default=60, validation_alias="CACHE_TTL_SECONDS")
    cache_enabled: bool = Field(default=True, validation_alias="CACHE_ENABLED")

settings = Settings()