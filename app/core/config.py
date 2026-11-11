"""Environment-bound configuration; source ETL is opt-in until mappings are verified."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    environment: str = "development"
    api_key: str = ""
    db_host: str = "mariadb"
    db_port: int = 3306
    db_name: str = "gambarte_reconciliation"
    db_user: str = "reconciliation"
    db_password: str = ""
    bolivia_db_host: str = ""
    bolivia_db_port: int = 3306
    bolivia_db_name: str = ""
    bolivia_db_user: str = ""
    bolivia_db_password: str = ""
    chile_db_host: str = ""
    chile_db_port: int = 3306
    chile_db_name: str = ""
    chile_db_user: str = ""
    chile_db_password: str = ""
    enable_source_etl: bool = False
    source_mapping_verified: bool = False
    sync_interval_seconds: int = 300
    reconcile_interval_seconds: int = 30
    backfill_days: int = 30
    overlap_days: int = 7
    max_source_age_minutes: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
