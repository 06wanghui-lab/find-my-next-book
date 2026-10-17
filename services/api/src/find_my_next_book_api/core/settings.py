from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[5]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="APP_",
        extra="ignore",
    )

    env: str = "development"
    log_level: str = "INFO"
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


class AgentSettings(BaseSettings):
    """Configuration for the terminal recommendation workflow.

    Environment variables deliberately have no application prefix so the official
    Google and Tavily integrations can use their conventional credential names.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        extra="ignore",
    )

    google_api_key: SecretStr | None = None
    tavily_api_key: SecretStr | None = None
    agent_model: str = "gemini-3.8-flash"
    agent_fallback_model: str | None = None
    agent_temperature: float = Field(default=1.0, ge=0.0, le=2.0)
    agent_llm_timeout_seconds: int = Field(default=60, ge=5, le=180)
    agent_llm_max_retries: int = Field(default=2, ge=0, le=3)
    agent_llm_retry_backoff_seconds: float = Field(default=1.0, ge=0.0, le=10.0)
    agent_initial_query_count: int = Field(default=2, ge=1, le=3)
    agent_max_search_attempts: int = Field(default=2, ge=1, le=2)
    agent_max_search_calls: int = Field(default=3, ge=1, le=6)
    agent_search_max_results: int = Field(default=5, ge=1, le=10)
    agent_max_reference_books: int = Field(default=3, ge=0, le=5)
    agent_max_verification_candidates: int = Field(default=5, ge=1, le=8)
    agent_min_candidates_for_verification: int = Field(default=3, ge=1, le=8)
    agent_min_recommendations: int = Field(default=3, ge=1, le=5)
    agent_max_recommendations: int = Field(default=5, ge=1, le=8)
    agent_session_dir: Path = PROJECT_ROOT / ".novelscout" / "sessions"

    @field_validator("agent_fallback_model", mode="before")
    @classmethod
    def empty_fallback_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("agent_session_dir", mode="after")
    @classmethod
    def resolve_session_dir(cls, value: Path) -> Path:
        return value if value.is_absolute() else PROJECT_ROOT / value

    @model_validator(mode="after")
    def validate_limits(self) -> "AgentSettings":
        if self.agent_max_search_calls < self.agent_initial_query_count:
            raise ValueError("AGENT_MAX_SEARCH_CALLS must cover the initial query count")
        if self.agent_min_recommendations > self.agent_max_recommendations:
            raise ValueError("AGENT_MIN_RECOMMENDATIONS cannot exceed AGENT_MAX_RECOMMENDATIONS")
        return self

    def missing_credentials(self) -> list[str]:
        missing: list[str] = []
        if self.google_api_key is None or not self.google_api_key.get_secret_value().strip():
            missing.append("GOOGLE_API_KEY")
        if self.tavily_api_key is None or not self.tavily_api_key.get_secret_value().strip():
            missing.append("TAVILY_API_KEY")
        return missing


@lru_cache
def get_agent_settings() -> AgentSettings:
    return AgentSettings()
