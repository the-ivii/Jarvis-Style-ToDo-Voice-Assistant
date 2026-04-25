"""
Long-term memory store.

- Stores each memory with an optional embedding vector (sentence-transformers).
- Recall uses cosine similarity when embeddings are available, otherwise falls
  back to case-insensitive keyword LIKE search.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Optional

import numpy as np

from . import config
from .database import memory_conn

log = logging.getLogger("memory")


class MemoryStore:
    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()
        self._embed_enabled = config.USE_EMBEDDINGS

    # -- embedding model loaded lazily so cold start is fast ----------------
    def _get_model(self):
        if not self._embed_enabled:
            return None
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                try:
                    from sentence_transformers import SentenceTransformer
                    log.info("Loading embedding model 'all-MiniLM-L6-v2'...")
                    self._model = SentenceTransformer("all-MiniLM-L6-v2")
                except Exception as e:  # pragma: no cover
                    log.warning("Embedding model unavailable, falling back to keyword search: %s", e)
                    self._embed_enabled = False
                    self._model = None
        return self._model

    def _embed(self, text: str) -> Optional[bytes]:
        model = self._get_model()
        if model is None:
            return None
        vec = model.encode([text], normalize_embeddings=True)[0].astype(np.float32)
        return vec.tobytes()

    # -- public API ---------------------------------------------------------
    def save(self, content: str, category: str = "general") -> int:
        emb = self._embed(content)
        with memory_conn() as c:
            cur = c.execute(
                "INSERT INTO memories (content, category, embedding) VALUES (?, ?, ?)",
                (content, category, emb),
            )
            return cur.lastrowid

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with memory_conn() as c:
            rows = c.execute(
                "SELECT id, content, category, created_at FROM memories ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def recall(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []

        model = self._get_model()
        if model is not None:
            # semantic search
            q_vec = model.encode([query], normalize_embeddings=True)[0].astype(np.float32)
            with memory_conn() as c:
                rows = c.execute(
                    "SELECT id, content, category, embedding, created_at FROM memories"
                ).fetchall()
            scored: list[tuple[float, dict[str, Any]]] = []
            for r in rows:
                if r["embedding"] is None:
                    continue
                vec = np.frombuffer(r["embedding"], dtype=np.float32)
                sim = float(np.dot(q_vec, vec))
                scored.append(
                    (
                        sim,
                        {
                            "id": r["id"],
                            "content": r["content"],
                            "category": r["category"],
                            "created_at": r["created_at"],
                            "similarity": round(sim, 3),
                        },
                    )
                )
            scored.sort(key=lambda t: t[0], reverse=True)
            top = [item for sim, item in scored[:limit] if sim > 0.25]
            if top:
                return top
            # else: fall through to keyword search so we never return empty when data exists

        # keyword fallback
        like = f"%{query.lower()}%"
        with memory_conn() as c:
            rows = c.execute(
                """
                SELECT id, content, category, created_at FROM memories
                WHERE LOWER(content) LIKE ? OR LOWER(category) LIKE ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (like, like, limit),
            ).fetchall()
        return [dict(r) for r in rows]


memory_store = MemoryStore()
