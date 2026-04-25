"""
Agent core: tool-calling loop using **Google Gemini** (google.genai SDK).

The model decides each turn whether to call tools (todo CRUD / memory) or reply
in natural language. Tool traces are returned for the UI.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types

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


def _system_prompt() -> str:
    return SYSTEM_PROMPT.format(today=datetime.now().strftime("%A, %B %d, %Y"))


_INT_PARAMS = {"todo_id", "limit"}


def _coerce_args(args: Any) -> dict[str, Any]:
    """Normalise: null → {}, string/float → int for id fields."""
    if args is None:
        return {}
    if not isinstance(args, dict):
        return {}
    out = dict(args)
    for k in list(out.keys()):
        if k in _INT_PARAMS and out[k] is not None:
            v = out[k]
            if isinstance(v, str):
                try:
                    out[k] = int(v)
                except ValueError:
                    pass
            elif isinstance(v, (float, int)) and not isinstance(v, bool):
                out[k] = int(v)
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


def _build_gemini_tools() -> list[types.Tool]:
    decls: list[types.FunctionDeclaration] = []
    for entry in TOOL_SCHEMAS:
        f = entry["function"]
        params = f.get("parameters")
        if not params:
            params = {"type": "object", "properties": {}}
        decls.append(
            types.FunctionDeclaration(
                name=f["name"],
                description=f.get("description", ""),
                parameters_json_schema=params,
            )
        )
    return [types.Tool(function_declarations=decls)]


def _client() -> genai.Client:
    if not config.GOOGLE_API_KEY or config.GOOGLE_API_KEY == "your_google_api_key_here":
        raise RuntimeError("GOOGLE_API_KEY is not set")
    return genai.Client(api_key=config.GOOGLE_API_KEY)


def _contents_from_history(
    history: list[dict[str, Any]], user_message: str
) -> list[types.Content]:
    out: list[types.Content] = []
    for m in history or []:
        if m.get("role") == "user":
            out.append(
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=m.get("content") or "")],
                )
            )
        elif m.get("role") == "assistant":
            out.append(
                types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=m.get("content") or "")],
                )
            )
    out.append(
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_message)],
        )
    )
    return out


def _reply_text_from_response(response: types.GenerateContentResponse) -> str:
    t = (response.text or "").strip()
    if t:
        return t
    if not response.candidates or not response.candidates[0].content:
        return ""
    for p in response.candidates[0].content.parts or []:
        if p.text and not p.thought:
            return (p.text or "").strip()
    return ""


def run_agent(
    user_message: str, history: Optional[List[Dict[str, Any]]] = None
) -> dict[str, Any]:
    client = _client()
    history = list(history or [])
    contents = _contents_from_history(history, user_message)
    base_cfg = types.GenerateContentConfig(
        system_instruction=_system_prompt(),
        tools=_build_gemini_tools(),
        temperature=0.3,
    )

    tool_trace: list[dict[str, Any]] = []
    model_id = config.GEMINI_MODEL
    MAX_STEPS = 5

    for _ in range(MAX_STEPS):
        response = client.models.generate_content(
            model=model_id,
            contents=contents,
            config=base_cfg,
        )

        if not response.candidates or not response.candidates[0].content:
            fb = ""
            if response.prompt_feedback is not None:
                fb = str(response.prompt_feedback)
            msg = f"I couldn't get a response from the model right now. {fb}".strip()
            new_h = history + [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": msg},
            ]
            return {"reply": msg, "tool_calls": tool_trace, "history": new_h}

        fcs = response.function_calls
        if fcs:
            cand = response.candidates[0]
            contents.append(cand.content)
            fr_parts: list[types.Part] = []
            for fc in fcs:
                name = (fc.name or "").strip()
                args = _coerce_args(fc.args)
                result = _dispatch_tool(name, args)
                tool_trace.append({"name": name, "args": args, "result": result})
                fr = types.FunctionResponse(
                    name=name,
                    response=result,
                    id=fc.id,
                )
                fr_parts.append(types.Part(function_response=fr))
            contents.append(types.Content(role="user", parts=fr_parts))
            continue

        reply_text = _reply_text_from_response(response) or "I'm not sure what to say."
        new_h = history + [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": reply_text},
        ]
        return {"reply": reply_text, "tool_calls": tool_trace, "history": new_h}

    # Safety: force a text-only follow-up
    no_tools = types.GenerateContentConfig(
        system_instruction=_system_prompt(),
        temperature=0.3,
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode=types.FunctionCallingConfigMode.NONE,
            )
        ),
    )
    response = client.models.generate_content(
        model=model_id,
        contents=contents
        + [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(
                        text="Please answer the user in plain, short speech. Do not use tools."
                    )
                ],
            )
        ],
        config=no_tools,
    )
    reply_text = _reply_text_from_response(response) or "Done."
    new_h = history + [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": reply_text},
    ]
    return {"reply": reply_text, "tool_calls": tool_trace, "history": new_h}
