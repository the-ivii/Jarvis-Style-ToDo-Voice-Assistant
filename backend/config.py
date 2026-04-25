"""Centralised environment configuration for the voice agent."""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

TODOS_DB = DATA_DIR / "todos.db"
MEMORY_DB = DATA_DIR / "memory.db"

# Google AI Studio / Gemini — single LLM for this project
# https://aistudio.google.com/apikey
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", os.getenv("GEMINI_API_KEY", "")).strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()

USE_EMBEDDINGS = os.getenv("USE_EMBEDDINGS", "true").lower() in {"1", "true", "yes"}

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))


def active_model() -> str:
    return GEMINI_MODEL


def have_api_key() -> bool:
    k = GOOGLE_API_KEY
    if not k or k in {"your_google_api_key_here", "your_gemini_api_key_here"}:
        return False
    return True
