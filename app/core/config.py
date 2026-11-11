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
    bolivia_db_name: str = ""
    bolivia_db_user: str = ""
    bolivia_db_password: str = ""
    chile_db_host: str = ""
    chile_db_name: str = ""
    chile_db_user: str = ""
    chile_db_password: str = ""

@lru_cache
def get_settings() -> Settings:
    return Settings()
