from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

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
    # "gemini" (default) or "featherless". For featherless, also set LLM_MODEL to a
    # chat model id (e.g. Qwen/Qwen2.5-72B-Instruct), EMBEDDING_MODEL to an
    # embedding model (e.g. Qwen/Qwen3-Embedding-8B), and FEATHERLESS_API_KEY.
    llm_provider: str = Field(default="gemini", validation_alias="LLM_PROVIDER")
    # Declared here so the keys load from .env like every other setting. The
    # adapters read os.getenv directly, which only ever sees *real* environment
    # variables — pydantic's env_file populates Settings without exporting into
    # os.environ. That works under compose (which passes real env vars) and
    # fails when running the backend on the host per DEPLOYMENT.md §4, where the
    # key exists only in backend/.env: every call then raises "GEMINI_API_KEY is
    # not set" and ingestion dies at the extract step.
    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")
    featherless_api_key: str = Field(default="", validation_alias="FEATHERLESS_API_KEY")
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
    # HyDE retrieval: embed a short hypothetical past-performance narrative
    # instead of the raw (imperative/regulatory) requirement text, closing the
    # register gap against the narrative prose the corpus is actually written
    # in. Costs one extra LLM call per requirement retrieved, so it's a
    # separate toggle from the rest of drafting — turn off if that latency/cost
    # isn't worth the retrieval-quality gain for a given deployment.
    draft_use_hyde: bool = Field(default=True, validation_alias="DRAFT_USE_HYDE")

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
    # Short by design. The access token now lives only in the client's memory
    # and is reissued from the refresh cookie, so a long lifetime buys nothing
    # and costs revocation latency: a deactivated user keeps working until their
    # current token expires. It was 24h when the token was persisted in
    # localStorage and a refresh round trip was something to avoid.
    access_token_expire_minutes: int = Field(
        default=15, validation_alias="ACCESS_TOKEN_EXPIRE_MINUTES"
    )
    # Refresh tokens outlive access tokens; rotation on every use bounds the
    # damage of a leaked one (see refresh_token_service).
    refresh_token_expire_days: int = Field(
        default=30, validation_alias="REFRESH_TOKEN_EXPIRE_DAYS"
    )

    # --- Refresh cookie (GAP_ANALYSIS §2.5) ---
    # The refresh token is delivered as an HttpOnly cookie so no script can read
    # it. Cookie attributes have to be configurable because the two supported
    # topologies differ:
    #
    #   dev        localhost:3000 → localhost:8000. Different ports are still
    #              *same-site*, so Lax works and Secure would break plain HTTP.
    #   production app.vercel.app → api.yourdomain.com are different registrable
    #              domains, i.e. cross-site: the cookie is dropped unless it is
    #              SameSite=None, and None is ignored without Secure. Set
    #              COOKIE_SAMESITE=none and COOKIE_SECURE=true there.
    #
    # Getting this wrong fails in one specific way — login succeeds, then every
    # refresh 401s because the cookie was never stored. See DEPLOYMENT.md §2.
    refresh_cookie_name: str = Field(
        default="proposalai_refresh", validation_alias="REFRESH_COOKIE_NAME"
    )
    cookie_secure: bool = Field(default=False, validation_alias="COOKIE_SECURE")
    cookie_samesite: str = Field(default="lax", validation_alias="COOKIE_SAMESITE")
    # Empty means "host-only", which is correct unless the API and app share a
    # parent domain and you want the cookie sent to both.
    cookie_domain: str = Field(default="", validation_alias="COOKIE_DOMAIN")

    # --- Password policy (GAP_ANALYSIS §2.4) ---
    # 12 rather than 8: length is the only dimension that reliably resists
    # offline cracking, and composition rules mostly produce P@ssw0rd1.
    password_min_length: int = Field(
        default=12, validation_alias="PASSWORD_MIN_LENGTH"
    )

    # --- SSE stream tickets (GAP_ANALYSIS §2.2) ---
    # EventSource cannot send an Authorization header, so the stream used to take
    # the access token in the query string, where it lands in server logs, proxy
    # logs and Referer headers. A ticket is single-use, scoped to one proposal,
    # and dead within this many seconds.
    stream_ticket_ttl_seconds: int = Field(
        default=30, validation_alias="STREAM_TICKET_TTL_SECONDS"
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
    # Registration is per-IP only — there is no account to key on yet, which is
    # exactly why it was left open (§2.3). Unlike login this counts *successes*
    # too: the abuse is bulk account creation, and every one of those succeeds.
    register_max_per_ip: int = Field(
        default=5, validation_alias="REGISTER_MAX_PER_IP"
    )
    register_window_seconds: int = Field(
        default=3600, validation_alias="REGISTER_WINDOW_SECONDS"
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

    # --- Startup checks ---
    # Whether a failed boot-time check stops the process. Defaults to on in
    # production, where a container that boots and cannot generate is worse than
    # one that refuses to start: the first fails for a user, the second fails in
    # the deploy pipeline. Off elsewhere so a developer with no API key can still
    # run the API. See app/core/startup_checks.py.
    # Unset means "decide from the environment"; an explicit value always wins.
    startup_checks_strict_setting: Optional[bool] = Field(
        default=None, validation_alias="STARTUP_CHECKS_STRICT"
    )

    @property
    def startup_checks_strict(self) -> bool:
        if self.startup_checks_strict_setting is not None:
            return self.startup_checks_strict_setting
        return self.environment.lower() == "production"

    # --- Observability (Sprint 5) ---
    telemetry_enabled: bool = Field(default=True, validation_alias="TELEMETRY_ENABLED")
    sentry_dsn: str = Field(default="", validation_alias="SENTRY_DSN")
    environment: str = Field(default="development", validation_alias="ENVIRONMENT")

    # --- Logging ---
    # INFO, not WARNING: the pipeline's progress lines ("Ingestion start",
    # "Ingestion complete: requirements=%d", per-section drafting) are all INFO,
    # and they are the trail you follow to a root cause. Dropping them is how
    # this application spent its life logging nothing.
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    # "json" | "console"; empty means decide from ENVIRONMENT (json in
    # production, console elsewhere). See app/core/logging.py.
    log_format: str = Field(default="", validation_alias="LOG_FORMAT")
    # Logged request/response bodies are the usual way secrets reach a log
    # aggregator, so this is off by default and never logs bodies — only the
    # request line, status, duration and identifiers.
    log_request_headers: bool = Field(
        default=False, validation_alias="LOG_REQUEST_HEADERS"
    )

    # Comma-separated allowed CORS origins (set to the Vercel domain in prod).
    cors_origins: str = Field(
        default="http://localhost:3000", validation_alias="CORS_ORIGINS"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

settings = Settings()