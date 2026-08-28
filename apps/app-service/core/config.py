from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

CURRENT_DIR = Path(__file__).resolve().parent
APP_DIR = CURRENT_DIR.parent
ENV_PATH = APP_DIR / ".env"


class Settings(BaseSettings):

    BACKEND_CORS_ORIGINS: list[str] = Field(default=...)

    model_config = SettingsConfigDict(
        env_file=ENV_PATH, env_ignore_empty=True, extra="ignore"
    )


settings = Settings()
