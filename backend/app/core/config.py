from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    app_name: str = "AI Proposal Platform API"
    debug: bool = True
    database_url: str = Field(..., validation_alias="DATABASE_URL")

settings = Settings()