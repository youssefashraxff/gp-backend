from pydantic_settings import BaseSettings,SettingsConfigDict
from dotenv import load_dotenv
import os
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    temporal_address: str
    temporal_namespace: str

settings = Settings()  # type: ignore[call-arg]