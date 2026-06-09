from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    app_name: str = "AI Proposal Platform API"
    debug: bool = True
    
    # Validation alias correctly intercepts DATABASE_URL from the system environment
    database_url: str = Field(..., validation_alias="DATABASE_URL")

    allowed_origins: str = "http://localhost:3000"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
