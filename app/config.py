from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    bot_token: str
    database_url: str
    app_base_url: str = ""
    port: int = 8080
    webhook_mode: bool = False
    log_level: str = "INFO"
    admin_ids: str = ""
    admin_id: str = ""
    groq_api_key: str = ""
    stt_model: str = "whisper-large-v3-turbo"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def admin_id_set(self) -> set[int]:
        raw = ",".join(v for v in (self.admin_ids, self.admin_id) if v)
        return {int(v.strip()) for v in raw.split(",") if v.strip()}

@lru_cache
def get_settings() -> Settings:
    return Settings()
