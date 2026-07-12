# papersearch_mini_app.py – FastAPI Mini App: Paper Search + AI Workspace + Chat
# Serves the web UI at /papersearch

import asyncio
import json
import logging
import os
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger(__name__)

app = FastAPI()

SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search"
SEMANTIC_SCHOLAR_PAPER = "https://api.semanticscholar.org/graph/v1/paper/"
SEMANTIC_SCHOLAR_KEY = os.getenv("SEMANTIC_SCHOLAR_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY") or os.getenv("XAI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# ── Semantic Scholar Proxy ────────────────────────────────────────────────────

@app.get("/papersearch/api/search")
async def api_search(query: str = "", limit: int = 10, sort: str = "relevance"):
    if not query:
        return JSONResponse({"error": "query required"}, status_code=400)

    params: dict[str, Any] = {
        "query": query,
        "limit": min(limit, 20),
        "fields": "paperId,title,year,abstract,authors,url,citationCount,externalIds,venue",
    }
    if sort == "citations":
        params["sort"] = "citationCount"
    elif sort == "date":
        params["sort"] = "publicationDate"

    headers = {}
    if SEMANTIC_SCHOLAR_KEY:
        headers["x-api-key"] = SEMANTIC_SCHOLAR_KEY

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(SEMANTIC_SCHOLAR_API, params=params, headers=headers)
            if resp.status_code == 200:
                return JSONResponse(resp.json())
            return JSONResponse({"error": f"API Error {resp.status_code}"}, status_code=resp.status_code)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/papersearch/api/paper/{paper_id}")
async def api_paper_detail(paper_id: str):
    params = {"fields": "paperId,title,year,abstract,authors,url,citationCount,references,citations,venue"}
    headers = {}
    if SEMANTIC_SCHOLAR_KEY:
        headers["x-api-key"] = SEMANTIC_SCHOLAR_KEY
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{SEMANTIC_SCHOLAR_PAPER}{paper_id}", params=params, headers=headers)
            if resp.status_code == 200:
                return JSONResponse(resp.json())
            return JSONResponse({"error": "Not found"}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── AI Chat Proxy (Groq) ──────────────────────────────────────────────────────

@app.post("/papersearch/api/chat")
async def api_chat(request: Request):
    try:
        body = await request.json()
        question = body.get("question", "").strip()
        papers = body.get("papers", [])

        if not question:
            return JSONResponse({"error": "question required"}, status_code=400)

        # Build paper context
        paper_ctx = []
        for i, p in enumerate(papers[:8], 1):
            title = p.get("title", "?")
            year = p.get("year", "?")
            authors = ", ".join(a.get("name", "") for a in p.get("authors", [])[:3])
            abstract = (p.get("abstract") or "")[:500]
            cit = p.get("citationCount", 0)
            paper_ctx.append(
                f"[Paper {i}] {title} ({year}) | {authors} | {cit} Zitate\n{abstract}"
            )

        context_text = "\n\n".join(paper_ctx) if paper_ctx else "Kein Workspace-Inhalt."

        system_prompt = (
            "Du bist ein wissenschaftlicher KI-Assistent für Paper-Analyse. "
            "Antworte präzise, strukturiert und auf Deutsch. "
            "Gib immer konkrete Lesetipps und 2-3 Suchvorschläge für verwandte Themen. "
            "Format: kurze Antwort, dann Lesetipps mit ●, dann Suchvorschläge mit 🔍."
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": f"Workspace ({len(papers)} Paper):\n{context_text}\n\nFrage: {question}",
                        },
                    ],
                    "max_tokens": 1024,
                    "temperature": 0.7,
                },
            )
            data = resp.json()
            answer = data.get("choices", [{}])[0].get("message", {}).get("content", "Keine Antwort.")
            return JSONResponse({"answer": answer})

    except Exception as e:
        logger.exception("Chat error")
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Send to Telegram ──────────────────────────────────────────────────────────

@app.post("/papersearch/api/send-telegram")
async def api_send_telegram(request: Request):
    try:
        body = await request.json()
        chat_id = body.get("chat_id")
        text = body.get("text", "").strip()

        if not chat_id or not text:
            return JSONResponse({"error": "chat_id and text required"}, status_code=400)

        if not TELEGRAM_BOT_TOKEN:
            return JSONResponse({"error": "Bot token not configured"}, status_code=500)

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text[:4096],
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            if resp.status_code == 200:
                return JSONResponse({"ok": True})
            return JSONResponse({"error": resp.text}, status_code=resp.status_code)

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── HTML Mini App ─────────────────────────────────────────────────────────────

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Paper Workspace</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:ital,wght@0,400;0,700;1,400&family=DM+Serif+Display:ital@0;1&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0a0e14;
    --surface: #111722;
    --surface2: #1a2235;
    --border: #1e2d47;
    --accent: #00e5ff;
    --accent2: #7c3aed;
    --text: #c8d6ef;
    --muted: #4a6080;
    --paper-bg: #0d1520;
    --success: #00c896;
    --warn: #ffaa00;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Space Mono', monospace;
    font-size: 13px;
    min-height: 100vh;
    overflow-x: hidden;
  }
  /* Animated grid background */
  body::before {
    content: '';
    position: fixed; inset: 0;
    background-image:
      linear-gradient(var(--border) 1px, transparent 1px),
      linear-gradient(90deg, var(--border) 1px, transparent 1px);
    background-size: 40px 40px;
    opacity: 0.25;
    pointer-events: none;
    z-index: 0;
  }
  #app { position: relative; z-index: 1; display: flex; flex-direction: column; height: 100vh; }

  /* Header */
  header {
    background: linear-gradient(135deg, #0a0e14 0%, #111722 100%);
    border-bottom: 1px solid var(--border);
    padding: 10px 16px;
    display: flex; align-items: center; gap: 10px;
    flex-shrink: 0;
  }
  header .logo {
    font-family: 'DM Serif Display', serif;
    font-size: 18px;
    color: var(--accent);
    letter-spacing: -0.5px;
  }
  header .logo span { color: var(--muted); font-size: 12px; font-family: 'Space Mono', monospace; }

  /* Tabs */
  .tabs {
    display: flex;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }
  .tab {
    flex: 1; padding: 10px 4px; text-align: center;
    cursor: pointer; font-size: 11px; color: var(--muted);
    border-bottom: 2px solid transparent;
    transition: all 0.2s; letter-spacing: 0.5px; text-transform: uppercase;
  }
  .tab.active { color: var(--accent); border-bottom-color: var(--accent); }
  .tab-badge {
    display: inline-block; background: var(--accent); color: #000;
    border-radius: 8px; padding: 1px 6px; font-size: 10px; margin-left: 4px;
    font-weight: 700;
  }

  /* Panels */
  .panel { display: none; flex: 1; overflow: hidden; flex-direction: column; }
  .panel.active { display: flex; }

  /* Search Panel */
  .search-bar {
    padding: 12px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    display: flex; gap: 8px; flex-wrap: wrap;
    flex-shrink: 0;
  }
  .search-bar input {
    flex: 1; min-width: 160px;
    background: var(--paper-bg); border: 1px solid var(--border);
    color: var(--text); padding: 8px 12px; border-radius: 6px;
    font-family: inherit; font-size: 13px; outline: none;
    transition: border-color 0.2s;
  }
  .search-bar input:focus { border-color: var(--accent); }
  .search-bar select {
    background: var(--paper-bg); border: 1px solid var(--border);
    color: var(--text); padding: 8px; border-radius: 6px;
    font-family: inherit; font-size: 12px; cursor: pointer; outline: none;
  }
  .btn {
    padding: 8px 14px; border: none; border-radius: 6px;
    cursor: pointer; font-family: inherit; font-size: 12px;
    font-weight: 700; transition: all 0.2s; letter-spacing: 0.3px;
  }
  .btn-primary { background: var(--accent); color: #000; }
  .btn-primary:hover { background: #00c8e0; }
  .btn-primary:active { transform: scale(0.97); }
  .btn-secondary { background: var(--surface2); color: var(--text); border: 1px solid var(--border); }
  .btn-secondary:hover { border-color: var(--accent); color: var(--accent); }
  .btn-purple { background: var(--accent2); color: #fff; }
  .btn-sm { padding: 5px 10px; font-size: 11px; }
  .btn-tg { background: #2196F3; color: #fff; }
  .btn-tg:hover { background: #1976D2; }

  /* Results list */
  .results-scroll { flex: 1; overflow-y: auto; padding: 10px; }
  .paper-card {
    background: var(--paper-bg);
    border: 1px solid var(--border);
    border-radius: 8px; padding: 12px; margin-bottom: 10px;
    transition: border-color 0.2s, transform 0.15s;
    animation: slideIn 0.25s ease;
  }
  .paper-card:hover { border-color: #2a3d5a; transform: translateY(-1px); }
  .paper-card.in-workspace { border-color: var(--success); }
  @keyframes slideIn {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .paper-title {
    font-family: 'DM Serif Display', serif;
    font-size: 14px; color: #e0ecff; margin-bottom: 6px;
    line-height: 1.3;
  }
  .paper-title a { color: inherit; text-decoration: none; }
  .paper-title a:hover { color: var(--accent); }
  .paper-meta {
    color: var(--muted); font-size: 11px; margin-bottom: 6px;
    display: flex; flex-wrap: wrap; gap: 8px;
  }
  .paper-meta span { display: flex; align-items: center; gap: 3px; }
  .paper-abstract {
    color: #7a9bcc; font-size: 12px; line-height: 1.5;
    margin-bottom: 8px; max-height: 80px; overflow: hidden;
    position: relative;
  }
  .paper-abstract.expanded { max-height: none; }
  .paper-actions { display: flex; gap: 6px; flex-wrap: wrap; }

  /* Workspace Panel */
  .workspace-header {
    padding: 10px 12px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center; justify-content: space-between;
    flex-shrink: 0;
  }
  .workspace-title { font-family: 'DM Serif Display', serif; font-size: 15px; color: var(--accent); }
  .ws-actions { display: flex; gap: 6px; }
  .empty-state {
    flex: 1; display: flex; flex-direction: column;
    align-items: center; justify-content: center; color: var(--muted);
    gap: 10px; padding: 20px; text-align: center;
  }
  .empty-icon { font-size: 40px; }

  /* Chat Panel */
  .chat-container { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  .chat-messages { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 10px; }
  .msg { max-width: 88%; padding: 10px 12px; border-radius: 10px; font-size: 12px; line-height: 1.6; animation: slideIn 0.2s ease; }
  .msg-user { background: var(--accent2); color: #fff; align-self: flex-end; border-bottom-right-radius: 3px; }
  .msg-bot { background: var(--surface2); border: 1px solid var(--border); align-self: flex-start; border-bottom-left-radius: 3px; }
  .msg-bot .msg-header { color: var(--accent); font-size: 10px; margin-bottom: 4px; font-weight: 700; }
  .msg-bot pre { white-space: pre-wrap; }
  .msg-actions { display: flex; gap: 6px; margin-top: 6px; }
  .chat-input-area {
    padding: 10px 12px;
    background: var(--surface);
    border-top: 1px solid var(--border);
    display: flex; gap: 8px; flex-shrink: 0;
  }
  .chat-input-area textarea {
    flex: 1; background: var(--paper-bg); border: 1px solid var(--border);
    color: var(--text); padding: 8px 10px; border-radius: 6px;
    font-family: inherit; font-size: 12px; outline: none;
    resize: none; min-height: 40px; max-height: 100px;
    transition: border-color 0.2s;
  }
  .chat-input-area textarea:focus { border-color: var(--accent); }
  .quick-prompts {
    padding: 6px 12px;
    display: flex; gap: 6px; overflow-x: auto; flex-shrink: 0;
    border-bottom: 1px solid var(--border);
  }
  .quick-prompt {
    background: var(--surface2); border: 1px solid var(--border);
    color: var(--muted); padding: 4px 10px; border-radius: 20px;
    font-size: 11px; cursor: pointer; white-space: nowrap;
    transition: all 0.15s;
  }
  .quick-prompt:hover { border-color: var(--accent); color: var(--accent); }

  /* Loading */
  .loading { display: flex; align-items: center; gap: 8px; color: var(--muted); padding: 8px; }
  .dot-anim span { animation: blink 1.2s infinite; }
  .dot-anim span:nth-child(2) { animation-delay: 0.2s; }
  .dot-anim span:nth-child(3) { animation-delay: 0.4s; }
  @keyframes blink { 0%,80%,100% { opacity:0.2; } 40% { opacity:1; } }

  /* Snackbar */
  #snack {
    position: fixed; bottom: 80px; left: 50%; transform: translateX(-50%);
    background: var(--surface2); border: 1px solid var(--border);
    color: var(--text); padding: 8px 18px; border-radius: 20px;
    font-size: 12px; opacity: 0; transition: opacity 0.2s; z-index: 999;
    pointer-events: none; white-space: nowrap;
  }
  #snack.show { opacity: 1; }
  #snack.ok { border-color: var(--success); color: var(--success); }
  #snack.err { border-color: #ff4444; color: #ff4444; }

  /* Scrollbar */
  ::-webkit-scrollbar { width: 4px; }
  ::-webkit-scrollbar-track { background: var(--bg); }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
</style>
</head>
<body>
<div id="app">
  <header>
    <div class="logo">📡 Paper Workspace <span>/ AI Research Assistant</span></div>
  </header>

  <div class="tabs">
    <div class="tab active" onclick="switchTab('search')">🔍 Suche</div>
    <div class="tab" onclick="switchTab('workspace')" id="wsTab">
      📂 Workspace <span class="tab-badge" id="wsBadge" style="display:none">0</span>
    </div>
    <div class="tab" onclick="switchTab('chat')">💬 KI-Chat</div>
  </div>

  <!-- SEARCH PANEL -->
  <div class="panel active" id="panel-search">
    <div class="search-bar">
      <input type="text" id="searchInput" placeholder="Suchbegriff eingeben…" onkeydown="if(event.key==='Enter') doSearch()">
      <select id="sortSelect">
        <option value="relevance">Relevanz</option>
        <option value="citations">Zitate ↓</option>
        <option value="date">Datum ↓</option>
      </select>
      <button class="btn btn-primary" onclick="doSearch()">Suchen</button>
    </div>
    <div class="results-scroll" id="searchResults">
      <div class="empty-state">
        <div class="empty-icon">🔬</div>
        <div>Suche nach wissenschaftlichen Papern</div>
        <div style="color: var(--muted); font-size: 11px;">z.B. "machine learning", "CRISPR", "quantum computing"</div>
      </div>
    </div>
  </div>

  <!-- WORKSPACE PANEL -->
  <div class="panel" id="panel-workspace">
    <div class="workspace-header">
      <div class="workspace-title">📂 Mein Workspace</div>
      <div class="ws-actions">
        <button class="btn btn-secondary btn-sm" onclick="sendWorkspaceSummary()">📤 Senden</button>
        <button class="btn btn-secondary btn-sm" onclick="clearWorkspace()">🗑️ Leeren</button>
      </div>
    </div>
    <div class="results-scroll" id="workspaceList">
      <div class="empty-state">
        <div class="empty-icon">📭</div>
        <div>Workspace ist leer</div>
        <div style="color: var(--muted); font-size: 11px;">Füge Paper aus der Suche hinzu</div>
      </div>
    </div>
  </div>

  <!-- CHAT PANEL -->
  <div class="panel" id="panel-chat">
    <div class="chat-container">
      <div class="quick-prompts" id="quickPrompts">
        <div class="quick-prompt" onclick="usePrompt(this)">Fasse die Paper zusammen</div>
        <div class="quick-prompt" onclick="usePrompt(this)">Zeige Gemeinsamkeiten</div>
        <div class="quick-prompt" onclick="usePrompt(this)">Gib Lesetipps</div>
        <div class="quick-prompt" onclick="usePrompt(this)">Suchvorschläge</div>
        <div class="quick-prompt" onclick="usePrompt(this)">Welches Paper ist am wichtigsten?</div>
        <div class="quick-prompt" onclick="usePrompt(this)">Zeitliche Entwicklung zeigen</div>
      </div>
      <div class="chat-messages" id="chatMessages">
        <div class="msg msg-bot">
          <div class="msg-header">🤖 PAPER-KI</div>
          <div>Hallo! Ich bin dein wissenschaftlicher Assistent. Füge Paper zum Workspace hinzu und stelle mir dann Fragen dazu. Ich gebe dir Zusammenfassungen, Lesetipps und Suchvorschläge.</div>
        </div>
      </div>
      <div class="chat-input-area">
        <textarea id="chatInput" placeholder="Frage stellen…" rows="1" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendChat();}"></textarea>
        <button class="btn btn-primary" onclick="sendChat()">↑</button>
      </div>
    </div>
  </div>
</div>

<div id="snack"></div>

<script>
// ── State ──────────────────────────────────────────────────────────────────────
let workspace = JSON.parse(localStorage.getItem('ps_workspace') || '[]');
let tgChatId = null;

// Get Telegram chat_id from WebApp init data
try {
  const tg = window.Telegram?.WebApp;
  if (tg) {
    tg.expand();
    tg.ready();
    const initData = tg.initDataUnsafe;
    if (initData?.user?.id) tgChatId = initData.user.id;
  }
} catch(e) {}

// Also check URL param
const urlParams = new URLSearchParams(window.location.search);
if (urlParams.get('chat_id')) tgChatId = urlParams.get('chat_id');
const preQuery = urlParams.get('q');
if (preQuery) {
  document.getElementById('searchInput').value = preQuery;
  setTimeout(doSearch, 300);
}

// ── Tab switching ──────────────────────────────────────────────────────────────
function switchTab(name) {
  document.querySelectorAll('.tab').forEach((t, i) => {
    const panels = ['search','workspace','chat'];
    t.classList.toggle('active', panels[i] === name);
  });
  document.querySelectorAll('.panel').forEach(p => {
    p.classList.toggle('active', p.id === 'panel-' + name);
  });
  if (name === 'workspace') renderWorkspace();
}

// ── Workspace persistence ──────────────────────────────────────────────────────
function saveWS() { localStorage.setItem('ps_workspace', JSON.stringify(workspace)); updateBadge(); }
function updateBadge() {
  const badge = document.getElementById('wsBadge');
  if (workspace.length > 0) {
    badge.textContent = workspace.length;
    badge.style.display = 'inline';
  } else {
    badge.style.display = 'none';
  }
}
function isInWS(id) { return workspace.some(p => p.paperId === id); }
function addToWS(paper) {
  if (!isInWS(paper.paperId)) {
    workspace.push(paper);
    saveWS();
    snack('✅ Zum Workspace hinzugefügt', 'ok');
    return true;
  }
  snack('ℹ️ Bereits im Workspace');
  return false;
}
function removeFromWS(id) {
  workspace = workspace.filter(p => p.paperId !== id);
  saveWS();
  renderWorkspace();
}
function clearWorkspace() {
  if (!confirm('Workspace leeren?')) return;
  workspace = [];
  saveWS();
  renderWorkspace();
}

// ── Snackbar ───────────────────────────────────────────────────────────────────
function snack(msg, type='') {
  const el = document.getElementById('snack');
  el.textContent = msg;
  el.className = 'show ' + type;
  clearTimeout(snack._t);
  snack._t = setTimeout(() => el.className = '', 2500);
}

// ── Search ─────────────────────────────────────────────────────────────────────
async function doSearch() {
  const q = document.getElementById('searchInput').value.trim();
  if (!q) return;
  const sort = document.getElementById('sortSelect').value;
  const results = document.getElementById('searchResults');
  results.innerHTML = '<div class="loading">🔍 Suche läuft<div class="dot-anim"><span>.</span><span>.</span><span>.</span></div></div>';

  try {
    const resp = await fetch(`/papersearch/api/search?query=${encodeURIComponent(q)}&sort=${sort}&limit=10`);
    const data = await resp.json();
    if (data.error) { results.innerHTML = `<div class="empty-state"><div class="empty-icon">❌</div><div>${data.error}</div></div>`; return; }
    const papers = data.data || [];
    if (!papers.length) { results.innerHTML = '<div class="empty-state"><div class="empty-icon">🤷</div><div>Keine Ergebnisse</div></div>'; return; }
    results.innerHTML = papers.map(p => renderPaperCard(p, true)).join('');
    updateBadge();
  } catch(e) {
    results.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><div>Fehler: ${e.message}</div></div>`;
  }
}

function renderPaperCard(p, showAdd) {
  const inWS = isInWS(p.paperId);
  const authors = (p.authors||[]).slice(0,3).map(a=>a.name).join(', ') + ((p.authors||[]).length > 3 ? ' et al.' : '');
  const abstract = p.abstract ? (p.abstract.length > 300 ? p.abstract.slice(0,300)+'…' : p.abstract) : '';
  const addBtn = showAdd
    ? `<button class="btn btn-sm ${inWS ? 'btn-secondary' : 'btn-primary'}" onclick='addToWS(${JSON.stringify(p).replace(/'/g,"&#39;")}); this.textContent="✓ Im Workspace"; this.disabled=true;'>${inWS ? '✓ Im Workspace' : '➕ Workspace'}</button>`
    : `<button class="btn btn-sm btn-secondary" onclick="removeFromWS('${p.paperId}')">🗑️ Entfernen</button>`;

  return `<div class="paper-card ${inWS ? 'in-workspace' : ''}" id="card-${p.paperId}">
    <div class="paper-title">${p.url ? `<a href="${p.url}" target="_blank">${p.title||'Kein Titel'}</a>` : (p.title||'Kein Titel')}</div>
    <div class="paper-meta">
      <span>📅 ${p.year||'?'}</span>
      <span>👤 ${authors||'Unbekannt'}</span>
      <span>🔗 ${p.citationCount||0} Zitate</span>
      ${p.venue ? `<span>📰 ${p.venue}</span>` : ''}
    </div>
    ${abstract ? `<div class="paper-abstract">${abstract}</div>` : ''}
    <div class="paper-actions">
      ${addBtn}
      <button class="btn btn-sm btn-secondary" onclick="askAboutPaper('${p.paperId}', \`${(p.title||'').replace(/`/g,'')}\`)">💬 KI fragen</button>
      ${tgChatId ? `<button class="btn btn-sm btn-tg" onclick='sendPaperToTelegram(${JSON.stringify(p).replace(/'/g,"&#39;")})'>📤 Telegram</button>` : ''}
    </div>
  </div>`;
}

// ── Workspace render ───────────────────────────────────────────────────────────
function renderWorkspace() {
  const el = document.getElementById('workspaceList');
  if (!workspace.length) {
    el.innerHTML = '<div class="empty-state"><div class="empty-icon">📭</div><div>Workspace ist leer</div><div style="color:var(--muted);font-size:11px">Füge Paper aus der Suche hinzu</div></div>';
    return;
  }
  el.innerHTML = workspace.map(p => renderPaperCard(p, false)).join('');
}

// ── Chat ───────────────────────────────────────────────────────────────────────
function usePrompt(el) { document.getElementById('chatInput').value = el.textContent; }

async function sendChat() {
  const input = document.getElementById('chatInput');
  const question = input.value.trim();
  if (!question) return;

  if (!workspace.length) {
    appendMsg('bot', '⚠️ Dein Workspace ist leer! Gehe zur Suche und füge Paper hinzu.');
    return;
  }

  appendMsg('user', question);
  input.value = '';
  const loadId = appendLoading();

  try {
    const resp = await fetch('/papersearch/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ question, papers: workspace })
    });
    const data = await resp.json();
    removeLoading(loadId);
    const answer = data.answer || data.error || 'Keine Antwort.';
    appendMsg('bot', answer, true);
  } catch(e) {
    removeLoading(loadId);
    appendMsg('bot', '❌ Fehler: ' + e.message);
  }
}

async function askAboutPaper(paperId, title) {
  const paper = workspace.find(p => p.paperId === paperId) ||
                (document.querySelectorAll('.paper-card'), null);
  switchTab('chat');
  document.getElementById('chatInput').value = `Was sind die wichtigsten Erkenntnisse aus dem Paper "${title}"? Gib Lesetipps und weiterführende Suchvorschläge.`;
}

function appendMsg(type, text, canSend=false) {
  const msgs = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = `msg msg-${type}`;
  if (type === 'bot') {
    let actions = '';
    if (canSend && tgChatId) {
      const safe = text.replace(/'/g, "\\'");
      actions = `<div class="msg-actions"><button class="btn btn-sm btn-tg" onclick="sendTextToTelegram('${safe}')">📤 An Telegram</button></div>`;
    }
    div.innerHTML = `<div class="msg-header">🤖 PAPER-KI</div><pre>${escHtml(text)}</pre>${actions}`;
  } else {
    div.textContent = text;
  }
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return div;
}

let _loadCount = 0;
function appendLoading() {
  const id = 'load-' + (++_loadCount);
  const msgs = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.id = id;
  div.className = 'loading';
  div.innerHTML = '🤖 Analysiere<div class="dot-anim"><span>.</span><span>.</span><span>.</span></div>';
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return id;
}
function removeLoading(id) { document.getElementById(id)?.remove(); }

// ── Telegram Send ──────────────────────────────────────────────────────────────
function escHtml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

async function sendTextToTelegram(text) {
  if (!tgChatId) { snack('⚠️ Keine Telegram Chat-ID gefunden', 'err'); return; }
  try {
    const resp = await fetch('/papersearch/api/send-telegram', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ chat_id: tgChatId, text })
    });
    const data = await resp.json();
    if (data.ok) snack('✅ An Telegram gesendet!', 'ok');
    else snack('❌ Fehler: ' + (data.error || 'Unbekannt'), 'err');
  } catch(e) { snack('❌ ' + e.message, 'err'); }
}

async function sendPaperToTelegram(paper) {
  const authors = (paper.authors||[]).slice(0,3).map(a=>a.name).join(', ');
  const text = `📄 <b>${paper.title||'?'}</b>\n` +
    `👤 ${authors} | 📅 ${paper.year||'?'} | 🔗 ${paper.citationCount||0} Zitate\n\n` +
    (paper.abstract ? paper.abstract.slice(0, 500) + '\n\n' : '') +
    (paper.url ? `🌐 ${paper.url}` : '');
  await sendTextToTelegram(text);
}

async function sendWorkspaceSummary() {
  if (!workspace.length) { snack('Workspace leer!'); return; }
  if (!tgChatId) {
    snack('⚠️ Öffne den Workspace aus dem Telegram-Chat', 'err');
    return;
  }
  switchTab('chat');
  document.getElementById('chatInput').value = 'Erstelle eine strukturierte Zusammenfassung für alle Paper im Workspace mit Lesetipps und Suchvorschlägen.';
  await sendChat();
}

// ── Init ───────────────────────────────────────────────────────────────────────
updateBadge();
</script>
</body>
</html>"""


@app.get("/papersearch", response_class=HTMLResponse)
async def papersearch_page():
    return HTMLResponse(content=HTML_PAGE)
