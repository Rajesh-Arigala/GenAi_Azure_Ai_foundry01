/* ── State ────────────────────────────────────────────────────── */
let isStreaming   = false;
let currentCard   = null;   // agent card DOM element
let currentTextEl = null;   // .agent-content inside that card
let currentText   = '';     // accumulated raw text

/* ── DOM refs ─────────────────────────────────────────────────── */
const messagesEl = document.getElementById('messages');
const welcomeEl  = document.getElementById('welcome');
const inputEl    = document.getElementById('chat-input');
const sendBtn    = document.getElementById('send-btn');
const resetBtn   = document.getElementById('reset-btn');

/* ── Event listeners ──────────────────────────────────────────── */
sendBtn.addEventListener('click', () => {
  const text = inputEl.value.trim();
  if (text && !isStreaming) submit(text);
});

inputEl.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    const text = inputEl.value.trim();
    if (text && !isStreaming) submit(text);
  }
});

inputEl.addEventListener('input', () => {
  inputEl.style.height = 'auto';
  inputEl.style.height = Math.min(inputEl.scrollHeight, 140) + 'px';
});

resetBtn.addEventListener('click', async () => {
  if (isStreaming) return;
  await fetch('/reset', { method: 'POST' });
  messagesEl.innerHTML = '';
  welcomeEl.style.display = 'flex';
  inputEl.value = '';
  inputEl.style.height = 'auto';
});

document.querySelectorAll('.prompt-chip').forEach(chip => {
  chip.addEventListener('click', () => {
    if (isStreaming) return;
    inputEl.value = chip.dataset.prompt;
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 140) + 'px';
    inputEl.focus();
  });
});

/* ── Core submit ──────────────────────────────────────────────── */
async function submit(text) {
  isStreaming = true;
  sendBtn.disabled = true;
  inputEl.disabled = true;
  inputEl.value    = '';
  inputEl.style.height = 'auto';

  welcomeEl.style.display = 'none';

  addUserMessage(text);
  startAgentMessage();

  try {
    const res = await fetch('/chat', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ message: text }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      handleEvent({ type: 'error', message: err.error || `HTTP ${res.status}` });
      return;
    }

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();           // keep partial line for next chunk
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          handleEvent(JSON.parse(line.slice(6)));
        } catch (_) {}
      }
    }
  } catch (err) {
    handleEvent({ type: 'error', message: 'Connection error: ' + err.message });
  } finally {
    isStreaming = false;
    sendBtn.disabled = false;
    inputEl.disabled = false;
    inputEl.focus();
  }
}

/* ── Event dispatcher ─────────────────────────────────────────── */
function handleEvent(ev) {
  switch (ev.type) {
    case 'status':     setStatus(ev.message);       break;
    case 'tools_used': showBadges(ev.tools);         break;
    case 'text_chunk': appendChunk(ev.content);      break;
    case 'image':      insertImage(ev.url);          break;
    case 'done':       finalise();                   break;
    case 'error':      showError(ev.message);        break;
  }
}

/* ── Message builders ─────────────────────────────────────────── */
function addUserMessage(text) {
  const el = createElement(`
    <div class="message user-message">
      <div class="user-bubble">
        <div class="avatar avatar-user">👤</div>
        <div class="user-content">${escHtml(text)}</div>
      </div>
    </div>`);
  messagesEl.appendChild(el);
  scrollDown();
}

function startAgentMessage() {
  currentText = '';
  const uid = 'msg-' + Date.now();
  const el  = createElement(`
    <div class="message agent-message" id="${uid}">
      <div class="agent-bubble">
        <div class="avatar avatar-agent">✈️</div>
        <div class="agent-card">
          <div class="tool-badges" id="badges-${uid}"></div>
          <div class="status-area" id="status-${uid}">
            <div class="typing-dots"><span></span><span></span><span></span></div>
            <span class="status-text">Connecting…</span>
          </div>
          <div class="agent-content" id="content-${uid}"></div>
        </div>
      </div>
    </div>`);
  messagesEl.appendChild(el);
  currentCard   = document.getElementById(uid);
  currentTextEl = document.getElementById(`content-${uid}`);
  scrollDown();
}

/* ── Update helpers ───────────────────────────────────────────── */
function setStatus(msg) {
  const el = currentCard?.querySelector('.status-text');
  if (el) el.textContent = msg;
}

function showBadges(tools) {
  const el = currentCard?.querySelector('.tool-badges');
  if (!el) return;
  el.innerHTML = tools.map(t =>
    `<span class="tool-badge"
       style="background:${t.color}22;color:${t.color};border:1px solid ${t.color}44">
       ${toolIcon(t.type)} ${t.label}
     </span>`
  ).join('');
}

function appendChunk(chunk) {
  if (!currentTextEl) return;
  currentText += chunk;
  currentTextEl.textContent = currentText;   // plain during streaming
  scrollDown();
}

function insertImage(url) {
  if (!currentCard) return;
  const card = currentCard.querySelector('.agent-card');
  const wrap = createElement(`
    <div class="chart-wrapper">
      <img src="${url}" class="chart-img" alt="Generated chart"
           onload="this.style.opacity=1" style="opacity:0">
      <a href="${url}" download class="download-btn">⬇️ Download Chart</a>
    </div>`);
  card.appendChild(wrap);
  scrollDown();
}

function finalise() {
  /* render markdown on accumulated text */
  if (currentTextEl && currentText) {
    currentTextEl.innerHTML = renderMarkdown(currentText);
  }
  /* hide the status / typing indicator */
  const statusEl = currentCard?.querySelector('.status-area');
  if (statusEl) statusEl.style.display = 'none';
  scrollDown();
  currentCard = currentTextEl = null;
  currentText = '';
}

function showError(msg) {
  const dots = currentCard?.querySelector('.typing-dots');
  const text = currentCard?.querySelector('.status-text');
  if (dots) dots.style.display = 'none';
  if (text) { text.textContent = '❌ ' + msg; text.style.color = '#f87171'; }
}

/* ── Utilities ────────────────────────────────────────────────── */
function scrollDown() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function createElement(html) {
  const div = document.createElement('div');
  div.innerHTML = html.trim();
  return div.firstElementChild;
}

function escHtml(str) {
  return str
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function toolIcon(type) {
  return { file_search:'📄', code_interpreter:'🐍', bing_grounding:'🌐', function:'⚙️' }[type] || '🔧';
}

/* ── Markdown renderer ────────────────────────────────────────── */
function renderMarkdown(raw) {
  /* 1. escape HTML so user content cannot inject tags */
  let s = escHtml(raw);

  /* 2. headers */
  s = s.replace(/^### (.+)$/gm, '<h5>$1</h5>');
  s = s.replace(/^## (.+)$/gm,  '<h4>$1</h4>');
  s = s.replace(/^# (.+)$/gm,   '<h3>$1</h3>');

  /* 3. bold / italic */
  s = s.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
  s = s.replace(/\*\*(.+?)\*\*/g,     '<strong>$1</strong>');
  s = s.replace(/\*(.+?)\*/g,         '<em>$1</em>');

  /* 4. inline code */
  s = s.replace(/`([^`\n]+)`/g, '<code>$1</code>');

  /* 5. horizontal rule */
  s = s.replace(/^-{3,}$/gm, '<hr>');

  /* 6. list items (simple conversion — no nesting) */
  s = s.replace(/^[-*•] (.+)$/gm,    '<li>$1</li>');
  s = s.replace(/^\d+\. (.+)$/gm,    '<li>$1</li>');
  /* wrap consecutive <li> blocks */
  s = s.replace(/(<li>[\s\S]*?<\/li>\n?)+/g, m => `<ul>${m}</ul>`);

  /* 7. paragraphs — split on blank lines */
  s = s
    .split(/\n{2,}/)
    .map(p => p.trim())
    .filter(Boolean)
    .map(p => (p.startsWith('<h') || p.startsWith('<ul') || p.startsWith('<hr')
               ? p : `<p>${p}</p>`))
    .join('');

  /* 8. remaining single newlines → <br> */
  s = s.replace(/\n/g, '<br>');

  return s;
}
