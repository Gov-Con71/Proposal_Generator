from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # Load a local .env when present; ignore unrelated keys so the app always boots.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AI Proposal Platform API"
    debug: bool = True
    # Default lets the app / Swagger docs boot without a live DB; every
    # persistence-backed route still requires a reachable database at request time.
    database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/rfp_proposal_db",
        validation_alias="DATABASE_URL",
    )

    # --- LLM provider (decoupled via app/services/llm) ---
    # Swap AI platforms by changing llm_provider + implementing an adapter.
    llm_provider: str = Field(default="gemini", validation_alias="LLM_PROVIDER")
    # gemini-2.0-flash is listed by the API but serves 429 with `limit: 0` — it
    # carries no free-tier request quota, which stalled the whole ingestion
    # pipeline. 2.5-flash is the current generally-available flash model.
    llm_model: str = Field(default="gemini-2.5-flash", validation_alias="LLM_MODEL")
    # text-embedding-004 has been retired and now 404s. gemini-embedding-001 is
    # its replacement; it defaults to 3072 dims, so the adapter pins the output
    # to EMBED_DIM (768) to match historical_chunks.embedding.
    embedding_model: str = Field(
        default="gemini-embedding-001", validation_alias="EMBEDDING_MODEL"
    )
    # Per-request LLM timeout so a hung provider call can't pin a worker thread
    # indefinitely (the drafting agent fans out several concurrent calls).
    llm_request_timeout_seconds: int = Field(
        default=120, validation_alias="LLM_REQUEST_TIMEOUT_SECONDS"
    )
    # Upper bound on characters sent to the extractors in one call. Well under
    # gemini-2.5-flash's context, but guards against a huge RFP being silently
    # under-attended (tail requirements dropped). Over this, input is truncated
    # with a loud warning — chunked/map-reduce extraction is the real fix.
    max_extraction_chars: int = Field(
        default=600_000, validation_alias="MAX_EXTRACTION_CHARS"
    )
    # Retry a rate-limited/unavailable LLM call (HTTP 429/503) instead of failing
    # it outright — the drafting agent bursts many calls and would otherwise leave
    # empty sections when it briefly exceeds the provider's per-minute quota.
    llm_max_retries: int = Field(default=5, validation_alias="LLM_MAX_RETRIES")
    llm_retry_base_seconds: float = Field(
        default=2.0, validation_alias="LLM_RETRY_BASE_SECONDS"
    )
    # How many proposal sections draft concurrently. Higher is faster but bursts
    # more concurrent LLM calls — keep low on a constrained/free provider quota.
    draft_max_concurrency: int = Field(
        default=3, validation_alias="DRAFT_MAX_CONCURRENCY"
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
    # Refresh tokens outlive access tokens; rotation on every use bounds the
    # damage of a leaked one (see refresh_token_service).
    refresh_token_expire_days: int = Field(
        default=30, validation_alias="REFRESH_TOKEN_EXPIRE_DAYS"
    )

    # --- Auth rate limiting (GAP_ANALYSIS §2.3) ---
    # Counts failed attempts only, so a legitimate user is never throttled.
    rate_limit_enabled: bool = Field(default=True, validation_alias="RATE_LIMIT_ENABLED")
    # Per-account: the control that a rotating botnet cannot evade.
    login_max_failures_per_account: int = Field(
        default=10, validation_alias="LOGIN_MAX_FAILURES_PER_ACCOUNT"
    )
    # Per-IP: catches spraying one password across many accounts. Higher, since
    # an office NAT legitimately shares an address.
    login_max_failures_per_ip: int = Field(
        default=50, validation_alias="LOGIN_MAX_FAILURES_PER_IP"
    )
    login_failure_window_seconds: int = Field(
        default=900, validation_alias="LOGIN_FAILURE_WINDOW_SECONDS"
    )  # 15 minutes

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

    # --- Observability (Sprint 5) ---
    telemetry_enabled: bool = Field(default=True, validation_alias="TELEMETRY_ENABLED")
    sentry_dsn: str = Field(default="", validation_alias="SENTRY_DSN")
    environment: str = Field(default="development", validation_alias="ENVIRONMENT")

    # Comma-separated allowed CORS origins (set to the Vercel domain in prod).
    cors_origins: str = Field(
        default="http://localhost:3000", validation_alias="CORS_ORIGINS"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

settings = Settings()