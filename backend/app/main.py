from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1 import proposals
from app.core.config import settings

app = FastAPI(title=settings.app_name, version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Connect decoupled feature modules cleanly
app.include_router(proposals.router, prefix="/api/v1")

@app.get("/")
def read_root():
    return {"message": "Scalable FastAPI Architecture Online!"}