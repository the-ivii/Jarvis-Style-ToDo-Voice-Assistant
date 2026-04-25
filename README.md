# 🎙️ Jarvis-Todo — Voice-Based AI Agent with Memory & Tools

A complete voice-enabled AI assistant that manages a personal to-do list through
natural conversation and remembers important facts about you across sessions.

Built as a submission for the **Voice-Based AI Agent** assignment. Everything runs
on your machine or a single free Render instance — no paid APIs required.

---

## ✨ Features

| Requirement | Implementation |
|---|---|
| **Voice interface (STT + TTS)** | Browser's Web Speech API — no external keys, works on Chrome / Edge / Safari. |
| **Tool-based Todo CRUD** | 5 tools: `add_todo`, `list_todos`, `update_todo`, `delete_todo`, `clear_completed`. |
| **Memory system** | SQLite + `sentence-transformers` (all-MiniLM-L6-v2) for semantic recall. Keyword fallback when embeddings disabled. |
| **Agent behaviour** | LLM decides tool-call vs chat with well-engineered system prompt, multi-step tool loop (up to 5 hops). |
| **LLM** | **Google Gemini** via `google-genai` — default model `gemini-2.0-flash` (set `GEMINI_MODEL` in `.env`). |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────┐
│  Browser Frontend                           │
│  • Web Speech API: mic → text, text → voice │
│  • Modern single-page UI                    │
└──────────────┬──────────────────────────────┘
               │ /api/chat (JSON)
               ▼
┌─────────────────────────────────────────────┐
│  FastAPI Backend                            │
│  ┌──────────────────────────────────────┐   │
│  │  Agent core (function-calling loop)  │   │
│  └──────────────┬───────────────────────┘   │
│     ┌───────────┼─────────────┐             │
│     ▼           ▼             ▼             │
│  Todo tools  Memory tools  System prompt    │
│     │           │                           │
│     ▼           ▼                           │
│  todos.db    memory.db (SQLite + embeds)    │
└─────────────────────────────────────────────┘
```

### Project Layout
```
voice-todo-agent/
├── backend/
│   ├── main.py        FastAPI app + static serving
│   ├── agent.py       Agent loop, function-calling, system prompt
│   ├── tools.py       Todo CRUD & memory tools + schemas
│   ├── memory.py      Semantic memory store (sentence-transformers)
│   ├── database.py    SQLite setup
│   └── config.py      Env loader
├── frontend/
│   ├── index.html     Voice UI
│   ├── app.js         Web Speech API + chat logic
│   └── style.css      Modern dark theme
├── data/              SQLite files (auto-created)
├── requirements.txt
├── .env.example
├── render.yaml        One-click Render deploy config
└── Procfile
```

---

## 🚀 Quick Start (Local)

### 1. Clone & install
```bash
git clone https://github.com/<you>/voice-todo-agent.git
cd voice-todo-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Get a Google AI (Gemini) API key

1. Open [Google AI Studio](https://aistudio.google.com/apikey) and sign in with a Google account.
2. Create an API key and copy it.

### 3. Configure
```bash
cp .env.example .env
```
Edit `.env` and set `GOOGLE_API_KEY` to your key. Optional: change `GEMINI_MODEL` (default `gemini-2.0-flash`).

### 4. Run
```bash
./run.sh
```
Or manually: `source .venv/bin/activate && uvicorn backend.main:app --host 0.0.0.0 --port 8000`

Open **http://127.0.0.1:8000** in Chrome / Edge / Safari (use `127.0.0.1` or `localhost`, not `0.0.0.0`, so the microphone works) and hit the mic button.

If Google returns an error about a **leaked or revoked API key**, create a **new** key at [Google AI Studio](https://aistudio.google.com/apikey) and update `.env` only on your machine (never commit `.env`).

> First time you trigger the mic, the browser will ask for microphone permission — allow it.
> On first agent request with embeddings on, the `sentence-transformers` model downloads (~90 MB).

---

## 🎤 Example voice commands

**Todos**
- "Add buy groceries tomorrow as high priority."
- "What's on my list?"
- "Mark task 2 as completed."
- "Delete the one about groceries."
- "Clear everything I've finished."

**Memory**
- "Remember my sister's birthday is June 14th."
- "I'm allergic to peanuts — please remember that."
- "My wife's name is Priya."
- "Do you remember anything about my family?"
- "What food allergies did I mention?"

**Mixed**
- "Add a reminder to buy a birthday gift for my sister." *(agent should recall her birthday date)*
- "What do you know about me?"

---

## 🧠 Agent Design

The system prompt (`backend/agent.py`) explicitly instructs the agent when to
call tools vs. respond conversationally:

- **Todo CRUD** → always go through tools (never fabricate list contents).
- **Important personal facts** → call `save_memory` silently in-turn.
- **Questions about the past** → call `recall_memory` first, then answer.
- **Chit-chat / greetings / clarifications** → no tool, just reply.
- Responses are kept short & natural because they will be spoken.

The loop supports up to **5 sequential tool hops** per user turn — e.g. the agent
can `recall_memory → list_todos → add_todo` all in one turn when appropriate.

---

## 💾 Memory recall

1. On save, each memory is embedded with `all-MiniLM-L6-v2` (384-d) and stored
   as a `BLOB` in SQLite.
2. On recall, the query is embedded and cosine similarity is computed against
   all stored vectors. Hits with similarity > 0.25 are returned, sorted desc.
3. If the embedding model fails to load (offline, no disk) or
   `USE_EMBEDDINGS=false`, the store automatically falls back to a
   case-insensitive keyword LIKE search.

---

## 🌍 Deploying Live (Render.com — free tier)

1. Push this repo to GitHub.
2. Log in at https://render.com → **New → Blueprint** → select your repo.
3. Render reads `render.yaml` and provisions the web service.
4. In the service's **Environment** tab set `GOOGLE_API_KEY` (same key as local; never commit it to git).
5. Done. Render gives you a public URL like `https://voice-todo-agent.onrender.com`.

The blueprint sets `PYTHON_VERSION` to 3.11.x for a supported runtime. If the build fails, check Render’s build logs.

> The free tier sleeps after 15 min idle. First request after sleep takes ~30s.
> `USE_EMBEDDINGS=false` in `render.yaml` keeps memory fast without the 90MB
> embedding model download; flip it on if you want semantic recall in prod.

**Alternatives**: Railway, Fly.io, and Google Cloud Run all work identically
— just use the `Procfile` or the `startCommand` from `render.yaml`.

---

## 🔌 API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Provider, model, key status. |
| `POST` | `/api/chat` | `{ "message": str, "history": [...] }` → agent reply + tool trace. |
| `GET` | `/api/todos?filter=all\|pending\|...` | Raw todos list. |
| `GET` | `/api/memories?limit=N` | Raw memory list. |

---

## 🛠️ Tools exposed to the agent

```
add_todo(task, due_date?, priority?)
list_todos(filter?)                  # all | pending | in_progress | completed
update_todo(todo_id, task?, status?, priority?, due_date?)
delete_todo(todo_id)
clear_completed()
save_memory(content, category?)
recall_memory(query, limit?)
list_memories(limit?)
```

All schemas are declared in `backend/tools.py::TOOL_SCHEMAS` and are passed to
Gemini as JSON-schema function declarations.

---

## 📝 License

MIT — do whatever you like.
