from __future__ import annotations

from dataclasses import dataclass
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_api_base: str
    openai_model: str


def get_settings() -> Settings:
    # Load `backend/.env` when present.
    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY", "")
    api_base = os.getenv("OPENAI_API_BASE", "http://localhost:8000/v1")
    model = os.getenv("OPENAI_MODEL", "qwen")
    return Settings(openai_api_key=api_key, openai_api_base=api_base, openai_model=model)

