// -----------------------------------------------------------------------------
// Voice To-Do Agent — frontend controller
//   * Web Speech API for STT + TTS (no external keys needed)
//   * Talks to /api/chat for the agent loop
// -----------------------------------------------------------------------------

const API = {
  chat: "/api/chat",
  todos: "/api/todos",
  memories: "/api/memories",
  health: "/api/health",
};

const els = {
  conversation: document.getElementById("conversation"),
  hero: document.getElementById("hero"),
  micBtn: document.getElementById("mic-btn"),
  textForm: document.getElementById("text-form"),
  textInput: document.getElementById("text-input"),
  ttsToggle: document.getElementById("tts-toggle"),
  todoList: document.getElementById("todo-list"),
  memoryList: document.getElementById("memory-list"),
  todoCount: document.getElementById("todo-count"),
  memoryCount: document.getElementById("memory-count"),
  providerBadge: document.getElementById("provider-badge"),
  clearChat: document.getElementById("clear-chat"),
};

// Conversation state (sent back to the server each turn so the agent has memory-within-session)
let history = JSON.parse(sessionStorage.getItem("chat_history") || "[]");

// -----------------------------------------------------------------------------
// Speech Recognition (STT)
// -----------------------------------------------------------------------------
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let listening = false;

if (SR) {
  recognition = new SR();
  recognition.lang = "en-US";
  recognition.interimResults = true;
  recognition.continuous = false;

  let finalTranscript = "";

  recognition.onstart = () => {
    listening = true;
    els.micBtn.classList.add("listening");
    finalTranscript = "";
    els.textInput.placeholder = "Listening…";
  };
  recognition.onerror = (e) => {
    console.warn("Recognition error:", e.error);
    if (e.error === "not-allowed") {
      alert("Microphone permission denied. Please allow it in your browser settings.");
    }
  };
  recognition.onend = () => {
    listening = false;
    els.micBtn.classList.remove("listening");
    els.textInput.placeholder = "Or type a message…";
    if (finalTranscript.trim()) {
      sendMessage(finalTranscript.trim());
    }
  };
  recognition.onresult = (event) => {
    let interim = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const res = event.results[i];
      if (res.isFinal) finalTranscript += res[0].transcript + " ";
      else interim += res[0].transcript;
    }
    els.textInput.value = (finalTranscript + interim).trim();
  };
} else {
  els.micBtn.disabled = true;
  els.micBtn.title = "Speech recognition is not supported in this browser. Use Chrome, Edge, or Safari.";
}

els.micBtn.addEventListener("click", () => {
  if (!recognition) return;
  if (listening) recognition.stop();
  else {
    cancelSpeech();
    try { recognition.start(); } catch (_) { /* already running */ }
  }
});

// -----------------------------------------------------------------------------
// Speech Synthesis (TTS)
// -----------------------------------------------------------------------------
function speak(text) {
  if (!els.ttsToggle.checked) return;
  if (!("speechSynthesis" in window)) return;
  cancelSpeech();
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 1.03;
  u.pitch = 1.0;
  // Try to pick a pleasant English voice
  const voices = speechSynthesis.getVoices();
  const preferred = voices.find(v => /Google.*English|Samantha|Daniel|Karen|Microsoft.*English/i.test(v.name))
                 || voices.find(v => v.lang && v.lang.startsWith("en"));
  if (preferred) u.voice = preferred;
  speechSynthesis.speak(u);
}
function cancelSpeech() {
  if ("speechSynthesis" in window) speechSynthesis.cancel();
}

// Ensure voices are loaded
if ("speechSynthesis" in window) {
  speechSynthesis.onvoiceschanged = () => {};
}

// -----------------------------------------------------------------------------
// UI helpers
// -----------------------------------------------------------------------------
function hideHero() {
  if (els.hero && els.hero.parentNode) els.hero.remove();
}

function addMessage(role, text) {
  hideHero();
  const div = document.createElement("div");
  div.className = `message ${role}`;
  const roleLabel = document.createElement("div");
  roleLabel.className = "role";
  roleLabel.textContent = role === "user" ? "You" : role === "assistant" ? "Jarvis" : "tool";
  const body = document.createElement("div");
  body.textContent = text;
  div.appendChild(roleLabel);
  div.appendChild(body);
  els.conversation.appendChild(div);
  els.conversation.scrollTop = els.conversation.scrollHeight;
  return div;
}

function addToolTrace(calls) {
  if (!calls || !calls.length) return;
  calls.forEach(tc => {
    const div = document.createElement("div");
    div.className = "message tool";
    const ok = tc.result && tc.result.ok !== false;
    div.textContent = `🔧 ${tc.name}(${stringifyArgs(tc.args)}) → ${ok ? "ok" : "error"}`;
    els.conversation.appendChild(div);
  });
  els.conversation.scrollTop = els.conversation.scrollHeight;
}
function stringifyArgs(a) {
  if (!a || typeof a !== "object") return "";
  return Object.entries(a).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ");
}

function showTyping() {
  hideHero();
  const div = document.createElement("div");
  div.className = "message assistant";
  div.id = "typing-indicator";
  div.innerHTML = `<div class="role">Jarvis</div><div class="typing"><span></span><span></span><span></span></div>`;
  els.conversation.appendChild(div);
  els.conversation.scrollTop = els.conversation.scrollHeight;
}
function hideTyping() {
  const t = document.getElementById("typing-indicator");
  if (t) t.remove();
}

// -----------------------------------------------------------------------------
// Networking
// -----------------------------------------------------------------------------
async function sendMessage(text) {
  if (!text) return;
  els.textInput.value = "";
  addMessage("user", text);
  showTyping();

  try {
    const res = await fetch(API.chat, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history }),
    });
    hideTyping();

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      addMessage("assistant", `⚠️  ${err.detail || "Request failed"}`);
      return;
    }

    const data = await res.json();
    history = data.history || history;
    sessionStorage.setItem("chat_history", JSON.stringify(history));
    addToolTrace(data.tool_calls);
    addMessage("assistant", data.reply);
    speak(data.reply);

    // Refresh panels if tool calls touched data
    if (data.tool_calls && data.tool_calls.length) {
      refreshPanels();
    }
  } catch (e) {
    hideTyping();
    addMessage("assistant", `⚠️  Network error: ${e.message}`);
  }
}

els.textForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const val = els.textInput.value.trim();
  if (val) sendMessage(val);
});

els.clearChat.addEventListener("click", () => {
  history = [];
  sessionStorage.removeItem("chat_history");
  els.conversation.innerHTML = "";
  els.conversation.appendChild(els.hero || createHero());
  cancelSpeech();
});

function createHero() {
  const div = document.createElement("div");
  div.className = "hero";
  div.id = "hero";
  div.innerHTML = `
    <div class="orb"></div>
    <h2>Tap the mic and just talk</h2>
    <p>Try: <em>"Add buy groceries tomorrow as high priority"</em> ·
       <em>"What's on my list?"</em> ·
       <em>"Remember my sister's birthday is June 14"</em></p>`;
  return div;
}

// -----------------------------------------------------------------------------
// Sidebar panels
// -----------------------------------------------------------------------------
async function refreshPanels() {
  try {
    const [t, m] = await Promise.all([
      fetch(API.todos).then(r => r.json()),
      fetch(API.memories).then(r => r.json()),
    ]);
    renderTodos(t.todos || []);
    renderMemories(m.memories || []);
  } catch (e) {
    console.warn("panel refresh failed", e);
  }
}

function renderTodos(todos) {
  els.todoCount.textContent = todos.length;
  els.todoList.innerHTML = "";
  if (!todos.length) {
    els.todoList.innerHTML = `<li class="todo-item" style="text-align:center;color:var(--muted)">Nothing yet.</li>`;
    return;
  }
  todos.forEach(t => {
    const li = document.createElement("li");
    li.className = `todo-item ${t.status === "completed" ? "completed" : ""}`;
    li.innerHTML = `
      <div><strong>#${t.id}</strong> · ${escapeHtml(t.task)}</div>
      <div class="meta">
        <span class="pill pill-${t.priority}">${t.priority}</span>
        <span class="pill pill-${t.status}">${t.status.replace("_", " ")}</span>
        ${t.due_date ? `<span>⏰ ${escapeHtml(t.due_date)}</span>` : ""}
      </div>`;
    els.todoList.appendChild(li);
  });
}

function renderMemories(memories) {
  els.memoryCount.textContent = memories.length;
  els.memoryList.innerHTML = "";
  if (!memories.length) {
    els.memoryList.innerHTML = `<li class="memory-item" style="text-align:center;color:var(--muted)">No memories yet.</li>`;
    return;
  }
  memories.slice(0, 30).forEach(m => {
    const li = document.createElement("li");
    li.className = "memory-item";
    li.innerHTML = `
      <div>${escapeHtml(m.content)}</div>
      <div class="meta">
        <span class="pill pill-general">${escapeHtml(m.category || "general")}</span>
        <span>${escapeHtml((m.created_at || "").slice(0, 16))}</span>
      </div>`;
    els.memoryList.appendChild(li);
  });
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

// -----------------------------------------------------------------------------
// Health / provider badge
// -----------------------------------------------------------------------------
async function loadHealth() {
  try {
    const h = await fetch(API.health).then(r => r.json());
    if (h.has_api_key) {
      els.providerBadge.textContent = `${h.provider} · ${h.model}`;
      els.providerBadge.classList.add("ok");
    } else {
      els.providerBadge.textContent = `⚠ no ${h.provider} key`;
      els.providerBadge.classList.add("err");
    }
  } catch (_) {
    els.providerBadge.textContent = "offline";
    els.providerBadge.classList.add("err");
  }
}

// -----------------------------------------------------------------------------
// Boot
// -----------------------------------------------------------------------------
(async function boot() {
  await loadHealth();
  await refreshPanels();
  // Replay history into the view if any
  if (history.length) {
    hideHero();
    history.forEach(m => {
      if (m.role === "user" || m.role === "assistant") addMessage(m.role, m.content || "");
    });
  }
})();
