from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    log_level: str = "INFO"

    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    openai_timeout_seconds: float = Field(default=60, gt=0)
    openai_max_retries: int = Field(default=2, ge=0)
    max_sql_attempts_per_turn: int = Field(default=3, ge=1, le=3)

    analytics_db_auth: Literal["sql", "entra_interactive"] = "sql"
    analytics_db_host: str = ""
    analytics_db_port: int = Field(default=1433, ge=1, le=65535)
    analytics_db_name: str = ""
    analytics_db_user: str = ""
    analytics_db_password: str = ""
    analytics_db_driver: str = "ODBC Driver 18 for SQL Server"

    query_timeout_seconds: int = Field(default=600, gt=0)
    max_result_rows: int = Field(default=200, ge=1, le=200)

    def database_connection_string(self) -> str:
        required = {
            "ANALYTICS_DB_HOST": self.analytics_db_host,
            "ANALYTICS_DB_NAME": self.analytics_db_name,
            "ANALYTICS_DB_USER": self.analytics_db_user,
        }
        if self.analytics_db_auth == "sql":
            required["ANALYTICS_DB_PASSWORD"] = self.analytics_db_password

        missing = [
            name
            for name, value in required.items()
            if not value
        ]
        if missing:
            raise ValueError(f"Falta configuración de SQL Server: {', '.join(missing)}")

        server = f"{self.analytics_db_host},{self.analytics_db_port}"
        parts = [
            f"DRIVER={{{self.analytics_db_driver}}}",
            f"SERVER={server}",
            f"DATABASE={self.analytics_db_name}",
            f"UID={self.analytics_db_user}",
        ]
        if self.analytics_db_auth == "sql":
            parts.append(f"PWD={{{self.analytics_db_password}}}")
        else:
            parts.append("Authentication=ActiveDirectoryInteractive")
        parts.extend(
            (
                "Encrypt=yes",
                "TrustServerCertificate=no",
                "ApplicationIntent=ReadOnly",
            )
        )
        return ";".join(parts)


@lru_cache
def get_settings() -> Settings:
    return Settings()
