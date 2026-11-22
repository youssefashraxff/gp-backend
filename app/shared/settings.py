from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    temporal_address: str
    temporal_namespace: str

    cors_origins: list[str] = ["http://localhost:4200"]


settings = Settings()  # type: ignore[call-arg]
