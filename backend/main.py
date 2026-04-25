"""FastAPI entrypoint for the voice to-do agent."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .agent import run_agent
from .database import init_db
from .tools import list_todos, list_memories

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
log = logging.getLogger("main")

app = FastAPI(title="Voice To-Do Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    log.info("DB ready. Gemini model: %s", config.active_model())
    if not config.have_api_key():
        log.warning(
            "No GOOGLE_API_KEY (or GEMINI_API_KEY) set. "
            "The UI will load but /api/chat will 503 until you add a key in .env."
        )


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

class ChatIn(BaseModel):
    message: str
    history: Optional[List[Dict[str, Any]]] = None


class ChatOut(BaseModel):
    reply: str
    tool_calls: List[Dict[str, Any]]
    history: List[Dict[str, Any]]


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": "gemini",
        "model": config.active_model(),
        "has_api_key": config.have_api_key(),
        "embeddings": config.USE_EMBEDDINGS,
    }


@app.post("/api/chat", response_model=ChatOut)
def chat(body: ChatIn) -> ChatOut:
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=400, detail="message is required")
    if not config.have_api_key():
        raise HTTPException(
            status_code=503,
            detail=(
                "No Google API key configured. Add GOOGLE_API_KEY to your .env "
                "(get one at https://aistudio.google.com/apikey) and restart."
            ),
        )
    try:
        result = run_agent(body.message, history=body.history or [])
    except Exception as e:
        log.exception("agent failed")
        raise HTTPException(status_code=500, detail=str(e))
    return ChatOut(**result)


@app.get("/api/todos")
def todos(filter: str = "all") -> dict[str, Any]:
    return list_todos(filter=filter)


@app.get("/api/memories")
def memories(limit: int = 50) -> dict[str, Any]:
    return list_memories(limit=limit)


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=config.HOST, port=config.PORT, reload=True)
