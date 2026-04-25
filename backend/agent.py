"""
Agent core: a tool-calling loop that works with both Groq and OpenAI
(their chat completion APIs are nearly identical, and both accept the OpenAI
function-calling schema format).

The agent decides on each turn whether to:
  - call one or more tools (todo CRUD / memory save/recall), or
  - respond directly to the user conversationally.

Transcript & tool traces are returned so the UI can show what happened.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from . import config
from .tools import TOOL_FUNCTIONS, TOOL_SCHEMAS

log = logging.getLogger("agent")


SYSTEM_PROMPT = """You are **Jarvis-Todo**, a friendly, concise voice assistant that helps the user manage a personal to-do list and remembers important things about them across sessions.

## Your tools
You have tools for todos (`add_todo`, `list_todos`, `update_todo`, `delete_todo`, `clear_completed`) and for long-term memory (`save_memory`, `recall_memory`, `list_memories`).

## When to use tools vs. chat
1. If the user asks to add / change / complete / remove / show todos → **use the relevant todo tool**. Never fabricate a todo list from the conversation; always call `list_todos` when the user asks what's on their list.
2. When the user shares something personal worth remembering long-term — names, birthdays, preferences, recurring commitments, goals, health/dietary info — call `save_memory` silently in the same turn, then continue the conversation naturally. Do NOT explicitly announce "I'll remember that" every single time; keep it natural. For truly important facts, a brief acknowledgement is fine.
3. When the user asks "do you remember…?", "what did I tell you about…?", "what do you know about me?", or when prior context would clearly help, call `recall_memory` first, then answer based on what you find.
4. Otherwise reply conversationally — greetings, small talk, clarifying questions, encouragement — without any tool call.

## Style (voice-first)
- Keep answers SHORT (1–3 sentences usually). They will be spoken aloud.
- No markdown, no bullet lists in spoken responses — just clean prose.
- When listing multiple todos, summarise naturally: "You have three pending tasks: buy milk, call mom, and finish the report."
- Always refer to todos by their short description, not raw ids, unless the user asks for ids.
- If a tool fails, explain the problem briefly and suggest a fix.
- Today's date is {today}. Use it for relative dates like "tomorrow" or "next Monday".

## Safety
- Confirm destructive actions (delete, clear_completed) only if the user's request is ambiguous. If they clearly said "delete task 3", just do it.
- Never invent todo ids; always fetch with `list_todos` first if you're unsure.
"""


def _build_client():
    if config.LLM_PROVIDER == "openai":
        from openai import OpenAI
        if not config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY not set")
        return OpenAI(api_key=config.OPENAI_API_KEY), config.OPENAI_MODEL
    # default: groq
    from groq import Groq
    if not config.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set")
    return Groq(api_key=config.GROQ_API_KEY), config.GROQ_MODEL


def _system_prompt() -> str:
    return SYSTEM_PROMPT.format(today=datetime.now().strftime("%A, %B %d, %Y"))


_INT_PARAMS = {"todo_id", "limit"}


def _coerce_args(args: Any) -> dict[str, Any]:
    """Defensive arg normalisation: null → {}, string ints → ints."""
    if args is None:
        return {}
    if not isinstance(args, dict):
        return {}
    out = dict(args)
    for k in list(out.keys()):
        if k in _INT_PARAMS and isinstance(out[k], str):
            try:
                out[k] = int(out[k])
            except ValueError:
                pass
    return out


def _dispatch_tool(name: str, args: Any) -> dict[str, Any]:
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return {"ok": False, "error": f"Unknown tool: {name}"}
    args = _coerce_args(args)
    try:
        return fn(**args)
    except TypeError as e:
        return {"ok": False, "error": f"Bad arguments for {name}: {e}"}
    except Exception as e:  # pragma: no cover
        log.exception("tool %s failed", name)
        return {"ok": False, "error": str(e)}


def run_agent(user_message: str, history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """
    Run one agent turn. Returns:
        {
            "reply": str,                         # final assistant text
            "tool_calls": [ {name, args, result} ],
            "history": [...]                      # updated full history for next turn
        }
    """
    client, model = _build_client()
    history = list(history or [])

    messages: list[dict[str, Any]] = [{"role": "system", "content": _system_prompt()}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    tool_trace: list[dict[str, Any]] = []

    # Let the model chain up to N tool calls before forcing a final answer.
    MAX_STEPS = 5
    for _ in range(MAX_STEPS):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            temperature=0.3,
        )
        msg = resp.choices[0].message

        # Record the assistant message exactly as returned (important for tool_calls roundtrip)
        assistant_entry: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant_entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_entry)

        if not msg.tool_calls:
            # Final response
            reply_text = (msg.content or "").strip()
            new_history = history + [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": reply_text},
            ]
            return {"reply": reply_text, "tool_calls": tool_trace, "history": new_history}

        # Execute each requested tool and append results
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = _dispatch_tool(name, args)
            tool_trace.append({"name": name, "args": args, "result": result})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": name,
                    "content": json.dumps(result),
                }
            )

    # Safety net: stopped due to MAX_STEPS. Ask the model for a final text answer.
    resp = client.chat.completions.create(
        model=model,
        messages=messages + [
            {
                "role": "system",
                "content": "Stop calling tools now and reply to the user in plain prose.",
            }
        ],
        temperature=0.3,
    )
    reply_text = (resp.choices[0].message.content or "").strip()
    new_history = history + [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": reply_text},
    ]
    return {"reply": reply_text, "tool_calls": tool_trace, "history": new_history}
