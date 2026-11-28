from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    temporal_address: str
    temporal_namespace: str

    cors_origins: list[str] = ["http://localhost:4200"]

    # Research tools (app/shared/tools). Optional so the app starts without them; a tool
    # called without its key returns an error result, which the agent escalates.
    google_maps_api_key: SecretStr | None = None  # Places (New), Routes, Elevation
    serper_api_key: SecretStr | None = None
    osm_cache_path: Path = Path("data/osm/osm_cache.json.gz")  # built by tools/osm.py


settings = Settings()  # type: ignore[call-arg]
