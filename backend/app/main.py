from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import psycopg2

from app.api.v1 import proposals
from app.core.config import settings

app = FastAPI(
    title=settings.app_name, 
    version="1.0.0",
    debug=settings.debug
)

# Falls back to localhost, but allows setting comma-separated production domains in your .env
# Example in .env: ALLOWED_ORIGINS=https://proposalai.com,https://staging.proposalai.com
allowed_origins = [
    origin.strip() 
    for origin in getattr(settings, "allowed_origins", "http://localhost:3000").split(",")
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],  # Allows GET, POST, OPTIONS, etc.
    allow_headers=["*"],
    max_age=600,          # Caches pre-flight OPTIONS requests for 10 minutes to reduce noise
)

# Connect decoupled feature modules cleanly
app.include_router(proposals.router, prefix="/api/v1")


@app.get("/", tags=["Health"])
def read_root():
    """
    Root endpoint serving basic deployment info.
    """
    return {
        "status": "healthy",
        "app_name": settings.app_name,
        "environment": "development" if settings.debug else "production"
    }


@app.get("/healthz", tags=["Health"])
def health_check():
    """
    Deep health check endpoint for Docker/Kubernetes readiness probes.
    Verifies that the raw psycopg2 database connection is alive.
    """
    try:
        # Simple ping check to verify database readiness
        with psycopg2.connect(settings.database_url, connect_timeout=3) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1;")
        return {"database": "connected", "api": "healthy"}
    except Exception as e:
        # Returning a 500 status tells Docker/orchestrators that the container is unhealthy
        from fastapi import Response, status
        return Response(
            content=f"Database connection failed: {str(e)}", 
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        )
