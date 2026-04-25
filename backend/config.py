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

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower().strip()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

USE_EMBEDDINGS = os.getenv("USE_EMBEDDINGS", "true").lower() in {"1", "true", "yes"}

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))


def active_model() -> str:
    return GROQ_MODEL if LLM_PROVIDER == "groq" else OPENAI_MODEL


def have_api_key() -> bool:
    if LLM_PROVIDER == "groq":
        return bool(GROQ_API_KEY) and GROQ_API_KEY != "your_groq_api_key_here"
    return bool(OPENAI_API_KEY) and OPENAI_API_KEY != "your_openai_api_key_here"
