from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application configuration.

    Every setting is read from the environment with the RHMG_ prefix. Validation
    happens once, at startup: a malformed database URL should crash the process
    immediately rather than surface as a confusing error on the first request.
    """

    model_config = SettingsConfigDict(env_prefix="RHMG_", extra="ignore")

    env: Literal["local", "test", "prod"] = "local"
    log_level: str = "INFO"

    database_url: str
    redis_url: str

    telegram_bot_token: str = ""

    # Named here so Day 2+ code never hardcodes the stream/group identifiers.
    message_stream: str = "rhmg:messages"
    consumer_group: str = "rhmg-workers"

    db_pool_size: int = Field(default=5, ge=1)


@lru_cache
def get_settings() -> Settings:
    """Cached so the environment is parsed once per process, not per request."""
    return Settings()  # type: ignore[call-arg]
