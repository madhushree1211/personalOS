from functools import lru_cache

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "personalos-backend"
    environment: str = Field(default="development", validation_alias=AliasChoices("ENV", "ENVIRONMENT"))
    port: int = 4000
    database_url: str = "sqlite:///./personalos.db"
    cors_origins: str = "http://localhost:5173"
    seed_demo_data: bool = True
    demo_password: str
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "personalos_documents"
    llm_provider: str = "none"
    llm_api_key: str | None = None
    llm_model: str = "gemini-2.0-flash"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def validate_jwt_secret(self) -> "Settings":
        if self.environment.lower() != "test" and len(self.jwt_secret) < 32:
            raise ValueError("JWT_SECRET must contain at least 32 characters outside ENV=test")
        return self

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def cors_middleware_options(origins: list[str]) -> dict[str, object]:
    """Build CORS options without combining wildcard origins and credentials."""
    if "*" in origins:
        return {"allow_origins": ["*"], "allow_credentials": False}
    return {"allow_origins": origins, "allow_credentials": bool(origins)}
