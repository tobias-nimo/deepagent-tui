from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    langgraph_url: str = "http://localhost:2024"
    graph_id: str | None = None
    thread_id: str | None = None
    langsmith_api_key: str | None = None


settings = Settings()
