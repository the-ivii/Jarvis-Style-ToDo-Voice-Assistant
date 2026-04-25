"""
All tool implementations the agent can call.

Each tool returns a small JSON-serialisable dict that the LLM reads back.
Keep responses concise — the agent summarises them for the user.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from .database import todos_conn
from .memory import memory_store


# ---------------------------------------------------------------------------
# Todo CRUD
# ---------------------------------------------------------------------------

VALID_PRIORITIES = {"low", "medium", "high"}
VALID_STATUSES = {"pending", "in_progress", "completed"}


def add_todo(
    task: str,
    due_date: Optional[str] = None,
    priority: str = "medium",
) -> dict[str, Any]:
    task = (task or "").strip()
    if not task:
        return {"ok": False, "error": "Task text is required."}

    priority = priority.lower().strip()
    if priority not in VALID_PRIORITIES:
        priority = "medium"

    with todos_conn() as c:
        cur = c.execute(
            """
            INSERT INTO todos (task, priority, due_date)
            VALUES (?, ?, ?)
            """,
            (task, priority, due_date),
        )
        todo_id = cur.lastrowid

    return {
        "ok": True,
        "message": f"Added todo #{todo_id}: {task}",
        "todo": {
            "id": todo_id,
            "task": task,
            "priority": priority,
            "due_date": due_date,
            "status": "pending",
        },
    }


def list_todos(filter: Optional[str] = None) -> dict[str, Any]:
    """filter: 'pending' | 'completed' | 'in_progress' | 'all' (default all)"""
    f = (filter or "all").lower().strip()
    query = "SELECT * FROM todos"
    params: tuple = ()
    if f in VALID_STATUSES:
        query += " WHERE status = ?"
        params = (f,)
    query += " ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, created_at DESC"

    with todos_conn() as c:
        rows = [dict(r) for r in c.execute(query, params).fetchall()]

    return {"ok": True, "count": len(rows), "todos": rows, "filter": f}


def update_todo(
    todo_id: int,
    task: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    due_date: Optional[str] = None,
) -> dict[str, Any]:
    fields, params = [], []

    if task is not None:
        fields.append("task = ?")
        params.append(task.strip())
    if status is not None:
        s = status.lower().strip().replace(" ", "_")
        if s not in VALID_STATUSES:
            return {"ok": False, "error": f"Invalid status. Use one of {sorted(VALID_STATUSES)}."}
        fields.append("status = ?")
        params.append(s)
    if priority is not None:
        p = priority.lower().strip()
        if p not in VALID_PRIORITIES:
            return {"ok": False, "error": f"Invalid priority. Use one of {sorted(VALID_PRIORITIES)}."}
        fields.append("priority = ?")
        params.append(p)
    if due_date is not None:
        fields.append("due_date = ?")
        params.append(due_date)

    if not fields:
        return {"ok": False, "error": "Nothing to update."}

    fields.append("updated_at = ?")
    params.append(datetime.utcnow().isoformat(timespec="seconds"))
    params.append(todo_id)

    with todos_conn() as c:
        cur = c.execute(
            f"UPDATE todos SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        if cur.rowcount == 0:
            return {"ok": False, "error": f"Todo #{todo_id} not found."}
        row = c.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()

    return {"ok": True, "message": f"Updated todo #{todo_id}.", "todo": dict(row)}


def delete_todo(todo_id: int) -> dict[str, Any]:
    with todos_conn() as c:
        cur = c.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
        if cur.rowcount == 0:
            return {"ok": False, "error": f"Todo #{todo_id} not found."}
    return {"ok": True, "message": f"Deleted todo #{todo_id}."}


def clear_completed() -> dict[str, Any]:
    with todos_conn() as c:
        cur = c.execute("DELETE FROM todos WHERE status = 'completed'")
    return {"ok": True, "message": f"Removed {cur.rowcount} completed todo(s)."}


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

def save_memory(content: str, category: str = "general") -> dict[str, Any]:
    content = (content or "").strip()
    if not content:
        return {"ok": False, "error": "Memory content is required."}
    mem_id = memory_store.save(content, category=category)
    return {"ok": True, "message": "Saved to memory.", "id": mem_id}


def recall_memory(query: str, limit: int = 5) -> dict[str, Any]:
    results = memory_store.recall(query, limit=limit)
    return {"ok": True, "count": len(results), "memories": results}


def list_memories(limit: int = 20) -> dict[str, Any]:
    results = memory_store.list_recent(limit=limit)
    return {"ok": True, "count": len(results), "memories": results}


# ---------------------------------------------------------------------------
# Tool schemas (OpenAI / Groq function-calling format)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "add_todo",
            "description": "Add a new todo item to the user's list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "What needs to be done."},
                    "due_date": {
                        "type": "string",
                        "description": "Optional natural-language or ISO date, e.g. 'tomorrow 5pm' or '2025-12-31'.",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "description": "Priority level. Defaults to medium.",
                    },
                },
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_todos",
            "description": "List all todos, optionally filtered by status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filter": {
                        "type": "string",
                        "enum": ["all", "pending", "in_progress", "completed"],
                        "description": "Which todos to list. Defaults to 'all'.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_todo",
            "description": "Update fields of an existing todo. Use this to mark todos complete or change their text/priority/due date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {"type": "integer", "description": "The numeric id of the todo."},
                    "task": {"type": "string"},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                    "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                    "due_date": {"type": "string"},
                },
                "required": ["todo_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_todo",
            "description": "Delete a todo by its id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {"type": "integer"},
                },
                "required": ["todo_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_completed",
            "description": "Remove all todos whose status is 'completed'.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": (
                "Persist an important personal fact, preference, or event the user mentions "
                "(e.g. birthdays, allergies, goals, names of family members, recurring habits). "
                "Only call this when the user shares information worth remembering long-term."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The fact or event in a single sentence."},
                    "category": {
                        "type": "string",
                        "description": "Optional label such as 'personal', 'work', 'health', 'preference', 'event'.",
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": (
                "Search stored long-term memories about the user using semantic similarity. "
                "Use this when the user asks 'do you remember...', 'what did I tell you about...', or when context would help."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for."},
                    "limit": {"type": "integer", "description": "Max number of memories (default 5)."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_memories",
            "description": "List the most recently saved memories.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Default 20."},
                },
            },
        },
    },
]


# Name -> callable dispatch table
TOOL_FUNCTIONS = {
    "add_todo": add_todo,
    "list_todos": list_todos,
    "update_todo": update_todo,
    "delete_todo": delete_todo,
    "clear_completed": clear_completed,
    "save_memory": save_memory,
    "recall_memory": recall_memory,
    "list_memories": list_memories,
}
