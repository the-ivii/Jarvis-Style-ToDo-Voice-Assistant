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
  stt: "/api/stt",
  tts: "/api/tts",
};

const els = {
  conversation: document.getElementById("conversation"),
  hero: document.getElementById("hero"),
  micHostBanner: document.getElementById("mic-host-banner"),
  micCurrentOrigin: document.getElementById("mic-current-origin"),
  linkVoice127: document.getElementById("link-voice-127"),
  linkVoiceLocalhost: document.getElementById("link-voice-localhost"),
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

// Conversation state
let history = JSON.parse(sessionStorage.getItem("chat_history") || "[]");

// -----------------------------------------------------------------------------
// Deepgram Speech-to-Text (STT) via Backend
// -----------------------------------------------------------------------------
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream);
    audioChunks = [];

    mediaRecorder.ondataavailable = (event) => {
      audioChunks.push(event.data);
    };

    mediaRecorder.onstop = async () => {
      const audioBlob = new Blob(audioChunks, { type: "audio/webm" });
      processSTT(audioBlob);
      // Stop all tracks to release mic
      stream.getTracks().forEach(track => track.stop());
    };

    mediaRecorder.start();
    isRecording = true;
    els.micBtn.classList.add("listening");
    els.textInput.placeholder = "Listening (Deepgram)...";
  } catch (err) {
    console.error("Mic error:", err);
    alert("Could not access microphone: " + err.message);
  }
}

function stopRecording() {
  if (mediaRecorder && isRecording) {
    mediaRecorder.stop();
    isRecording = false;
    els.micBtn.classList.remove("listening");
    els.textInput.placeholder = "Processing...";
  }
}

async function processSTT(blob) {
  const formData = new FormData();
  formData.append("file", blob, "rec.webm");

  try {
    const res = await fetch(API.stt, {
      method: "POST",
      body: formData,
    });
    const data = await res.json();
    if (data.ok && data.transcript) {
      els.textInput.value = data.transcript;
      sendMessage(data.transcript);
    } else {
      els.textInput.placeholder = "Or type a message...";
    }
  } catch (e) {
    console.error("STT failed", e);
    els.textInput.placeholder = "STT Error.";
  }
}

els.micBtn.addEventListener("click", () => {
  if (isRecording) stopRecording();
  else {
    cancelSpeech();
    startRecording();
  }
});

// -----------------------------------------------------------------------------
// Deepgram Text-to-Speech (TTS) via Backend
// -----------------------------------------------------------------------------
const audioPlayer = new Audio();

async function speak(text) {
  if (!els.ttsToggle.checked) return;
  cancelSpeech();

  try {
    // We use a URL with the text query param
    const ttsUrl = `${API.tts}?text=${encodeURIComponent(text)}`;
    audioPlayer.src = ttsUrl;
    await audioPlayer.play();
  } catch (e) {
    console.warn("TTS playback failed", e);
  }
}

function cancelSpeech() {
  audioPlayer.pause();
  audioPlayer.currentTime = 0;
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
// Mic: 0.0.0.0 vs real hostname (browser security)
// Rebuilds any URL (port, path, ?query, #hash) for 127.0.0.1 / localhost.
// -----------------------------------------------------------------------------
/**
 * @param {string} newHostname e.g. "127.0.0.1" or "localhost"
 * @returns {string}
 */
function sameAppUrlWithHostname(newHostname) {
  try {
    const u = new URL(window.location.href);
    u.hostname = newHostname;
    return u.href;
  } catch (_) {
    return `http://${newHostname}/`;
  }
}

function fillVoiceLinkAnchor(el, hostLabel) {
  if (!el) return;
  const u = sameAppUrlWithHostname(hostLabel);
  el.href = u;
  el.textContent = u;
}

function setupMicHostBanner() {
  if (els.micCurrentOrigin) {
    els.micCurrentOrigin.textContent = window.location.origin || window.location.href;
  }
  fillVoiceLinkAnchor(els.linkVoice127, "127.0.0.1");
  fillVoiceLinkAnchor(els.linkVoiceLocalhost, "localhost");

  if (els.micHostBanner) {
    els.micHostBanner.hidden = location.hostname !== "0.0.0.0";
  }
}

function showMicPermissionHelp() {
  const h = location.hostname;
  const v4 = sameAppUrlWithHostname("127.0.0.1");
  const loc = sameAppUrlWithHostname("localhost");

  let msg = "Microphone access was blocked.\n\n";
  if (h === "0.0.0.0") {
    msg +=
      "0.0.0.0 is not a valid host for the microphone in most browsers. Open the same page at:\n\n" +
      `${v4}\n` +
      `or\n${loc}\n\n`;
  } else {
    msg += `You are on: ${window.location.origin}\n\n`;
  }
  msg +=
    "Allow the microphone when asked, or: lock icon → Site settings → Microphone → Allow.\n\n" +
    "On Mac: System Settings → Privacy & Security → Microphone → enable for your browser.";
  alert(msg);
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
  setupMicHostBanner();
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
