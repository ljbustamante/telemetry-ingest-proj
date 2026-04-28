
import os
from dotenv import load_dotenv

load_dotenv()

def get_env(name: str, default: str | None = None) -> str:
    v = os.getenv(name, default)
    if v is None:
        raise RuntimeError(f"Missing environment variable: {name}")
    return v

class Settings:
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    TELEMETRY_QUEUE_URL = get_env("TELEMETRY_QUEUE_URL")
    DB_HOST = get_env("DB_HOST")
    DB_PORT = int(get_env("DB_PORT", "5432"))
    DB_NAME = get_env("DB_NAME")
    DB_USER = get_env("DB_USER")
    DB_PASSWORD = get_env("DB_PASSWORD")
