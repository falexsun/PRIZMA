from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "local"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5000"

    database_url: str
    redis_url: str

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    vk_service_token: str = ""
    vk_user_token: str = ""
    youtube_api_key: str = ""
    tiktok_rapidapi_key: str = ""
    instagram_proxy: str = ""
    max_headless_enabled: bool = True
    max_session_path: str = "max_session.json"

    # Proxy routing: NON_RU for TikTok/Instagram/Telegram, RU for Dzen/OK
    non_ru_proxy: str = ""
    ru_proxy: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
