# chess_mini_app.py – v7 (Groq Chat + Farben + Protokoll + Responsive)
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import logging
import random

logger = logging.getLogger(__name__)
app = FastAPI(title="Queen's Crystal Chess")

try:
    from chess_engine import get_llama_chess_move, get_llama_chat_reply
    ENGINE_AVAILABLE = True
    logger.info("✅ Chess Engine (Groq) geladen")
except Exception as e:
    ENGINE_AVAILABLE = False
    logger.warning(f"⚠️  Chess Engine nicht verfügbar: {e}")


class MoveRequest(BaseModel):
    fen: str

class ChatRequest(BaseModel):
    message: str
    fen: str


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Queen's Crystal Chess</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/chess.js/0.10.3/chess.min.js"></script>
<style>
/* ═══════════ RESET + BASE ═══════════ */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
    --bg-deep:    #050011;
    --bg-panel:   rgba(12, 4, 38, 0.97);
    --accent:     #aa66ff;
    --pink:       #ff00cc;
    --user-blue:  #87ceeb;   /* hellblau  – User-Figuren  */
    --llama-teal: #40e0d0;   /* helltürkis – Llama-Figuren */
    --glow-blue:  #5bc8f5;
    --glow-teal:  #20c8b8;
    --border:     1px solid var(--accent);
    --radius:     16px;
    --font:       system-ui, -apple-system, sans-serif;
}

html {
    background: radial-gradient(ellipse at 40% 30%, #2a0055 0%, var(--bg-deep) 70%);
    min-height: 100%;
}

body {
    font-family: var(--font);
    color: #e0ccff;
    min-height: 100vh;
    overflow-x: hidden;
    overflow-y: auto;
    padding: 8px;
    padding-bottom: 20px;
}

/* ═══════════ SCROLLBAR STYLING ═══════════ */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--accent); border-radius: 99px; }

/* ═══════════ TOP BAR ═══════════ */
#top-bar {
    position: sticky;
    top: 0;
    z-index: 100;
    display: flex;
    align-items: center;
    gap: 8px;
    background: rgba(10, 2, 30, 0.97);
    border: var(--border);
    border-radius: var(--radius);
    padding: 10px 14px;
    margin-bottom: 10px;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
}

#status {
    flex: 1;
    text-align: center;
    font-weight: 700;
    font-size: clamp(0.78rem, 2.5vw, 0.95rem);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.btn {
    background: linear-gradient(135deg, var(--pink), #aa00ff);
    color: #fff;
    border: none;
    padding: 9px 16px;
    border-radius: 999px;
    font-weight: 700;
    font-size: 0.85rem;
    cursor: pointer;
    white-space: nowrap;
    flex-shrink: 0;
    -webkit-tap-highlight-color: transparent;
}
.btn:active { opacity: 0.8; transform: scale(0.97); }

/* ═══════════ MAIN LAYOUT ═══════════ */
#main-grid {
    display: grid;
    gap: 10px;
    align-items: start;
}

/* Mobile: alles untereinander */
@media (max-width: 599px) {
    #main-grid {
        grid-template-columns: 1fr;
    }
}

/* Tablet Portrait ≥ 600px */
@media (min-width: 600px) {
    #main-grid {
        grid-template-columns: 1fr 260px;
    }
}

/* Tablet Landscape / groß ≥ 820px */
@media (min-width: 820px) {
    #main-grid {
        grid-template-columns: 1fr 300px;
    }
}

/* ═══════════ BOARD AREA ═══════════ */
#board-area {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
}

#board-wrap {
    width: 100%;
    max-width: 480px;
}

/* Koordinaten-Labels */
#coord-row, #coord-col {
    display: flex;
    justify-content: space-around;
    font-size: 0.7rem;
    color: #8866aa;
    padding: 0 2px;
}
#coord-row { flex-direction: column; position: absolute; left: -18px; top: 0; height: 100%; }

#board-container {
    position: relative;
    display: flex;
    align-items: center;
}

#chessboard {
    display: grid;
    grid-template-columns: repeat(8, 1fr);
    width: 100%;
    border: 4px solid var(--accent);
    border-radius: 14px;
    overflow: hidden;
    box-shadow:
        0 0 40px rgba(170, 100, 255, 0.5),
        0 0 80px rgba(170, 100, 255, 0.2);
    touch-action: none;
}

/* Felder */
.square {
    aspect-ratio: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    position: relative;
    transition: box-shadow 0.1s;
    -webkit-tap-highlight-color: transparent;
    user-select: none;
}

.square.light { background: #d4eeff; }
.square.dark  { background: #2d1560; }

/* Highlights */
.square.selected   { box-shadow: inset 0 0 0 5px var(--pink) !important; }
.square.possible   {
    background-image: radial-gradient(circle, rgba(0,255,140,0.45) 30%, transparent 70%);
}
.square.possible.occupied::after {
    content: '';
    position: absolute;
    inset: 0;
    border: 4px solid rgba(0,255,140,0.6);
    border-radius: 2px;
    pointer-events: none;
}
.square.last-move  { box-shadow: inset 0 0 0 4px rgba(0,220,255,0.6) !important; }
.square.in-check   { box-shadow: inset 0 0 0 5px #ff3333 !important; }

/* ═══════════ FIGUREN ═══════════ */
.piece {
    font-size: clamp(1.4rem, 5vw, 2.4rem);
    line-height: 1;
    pointer-events: none;
    display: block;
}

/* Hellblau = User (Weiß) */
.piece.user-piece {
    color: var(--user-blue);
    text-shadow:
        0 0 8px var(--glow-blue),
        0 0 20px rgba(135, 206, 235, 0.6);
    filter: drop-shadow(0 2px 4px rgba(0,0,0,0.6));
}

/* Helltürkis = Llama (Schwarz) */
.piece.llama-piece {
    color: var(--llama-teal);
    text-shadow:
        0 0 8px var(--glow-teal),
        0 0 20px rgba(64, 224, 208, 0.6);
    filter: drop-shadow(0 2px 4px rgba(0,0,0,0.6));
}

/* ═══════════ SIDE PANEL ═══════════ */
.side-panel {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

/* Auf Mobile: horizontales Scroll-Grid für Panels */
@media (max-width: 599px) {
    .side-panel {
        flex-direction: row;
        overflow-x: auto;
        scroll-snap-type: x mandatory;
        gap: 8px;
        padding-bottom: 6px;
    }
    .panel {
        min-width: min(85vw, 320px);
        scroll-snap-align: start;
        flex-shrink: 0;
        max-height: 280px;
    }
}

.panel {
    background: var(--bg-panel);
    border: var(--border);
    border-radius: var(--radius);
    padding: 12px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

/* Panel-Höhen auf Tablet */
@media (min-width: 600px) {
    #panel-protocol { max-height: 220px; }
    #panel-chat     { max-height: 280px; }
    #panel-think    { max-height: 180px; }
}

.panel-header {
    color: var(--pink);
    font-weight: 800;
    font-size: 0.85rem;
    margin-bottom: 8px;
    flex-shrink: 0;
    letter-spacing: 0.03em;
}

/* ═══════════ PROTOKOLL ═══════════ */
#protocol-content {
    overflow-y: auto;
    flex: 1;
    font-size: 0.82rem;
}

.proto-table {
    width: 100%;
    border-collapse: collapse;
    font-family: monospace;
}
.proto-table th {
    font-size: 0.75rem;
    padding: 2px 6px;
    text-align: left;
    border-bottom: 1px solid rgba(170,100,255,0.3);
    color: #9977bb;
    font-family: var(--font);
}
.proto-table td {
    padding: 3px 6px;
    border-radius: 4px;
}
.proto-num  { color: #6644aa; font-size: 0.75rem; }
.proto-user { color: var(--user-blue); font-weight: 600; }
.proto-llama{ color: var(--llama-teal); font-weight: 600; }
.proto-row:nth-child(odd) td { background: rgba(255,255,255,0.03); }

/* ═══════════ CHAT ═══════════ */
#chat-messages {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-height: 0;
}

.msg {
    padding: 8px 12px;
    border-radius: 12px;
    font-size: 0.86rem;
    line-height: 1.4;
    word-break: break-word;
}
.msg.user  { background: rgba(135,206,235,0.15); border-left: 3px solid var(--user-blue); }
.msg.llama { background: rgba(64,224,208,0.12);  border-left: 3px solid var(--llama-teal); }
.msg b     { display: block; font-size: 0.78rem; margin-bottom: 3px; opacity: 0.8; }

.chat-input-row {
    display: flex;
    gap: 6px;
    margin-top: 8px;
    flex-shrink: 0;
}
#chat-input {
    flex: 1;
    padding: 10px 14px;
    border-radius: 999px;
    background: rgba(255,255,255,0.07);
    border: var(--border);
    color: #fff;
    font-size: 0.88rem;
    outline: none;
}
#chat-input::placeholder { color: #8866aa; }
#chat-input:focus { border-color: var(--llama-teal); }
#send-btn {
    background: linear-gradient(135deg, var(--llama-teal), #20a0a0);
    color: #000;
    border: none;
    border-radius: 999px;
    padding: 10px 14px;
    font-weight: 700;
    cursor: pointer;
    font-size: 0.88rem;
}

/* ═══════════ THINK TANK ═══════════ */
#terminal-content {
    overflow-y: auto;
    flex: 1;
    font-family: monospace;
    font-size: 0.78rem;
    display: flex;
    flex-direction: column;
    gap: 2px;
}
.term-line { padding: 2px 0; }
.term-info  { color: #9988bb; }
.term-think { color: #ddccff; }
.term-move  { color: #00ffaa; font-weight: 600; }
.term-error { color: #ff6666; }

/* ═══════════ LEGEND ═══════════ */
#legend {
    display: flex;
    gap: 16px;
    font-size: 0.78rem;
    justify-content: center;
    margin-top: 4px;
    opacity: 0.85;
}
.legend-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px; vertical-align: middle; }
</style>
</head>
<body>

<!-- TOP BAR -->
<div id="top-bar">
    <button class="btn" onclick="newGame()">♻️ Neu</button>
    <div id="status">♔ Du bist am Zug</div>
    <button class="btn" onclick="closeTg()">✕</button>
</div>

<!-- MAIN GRID -->
<div id="main-grid">

    <!-- BOARD COLUMN -->
    <div id="board-area">
        <div id="board-wrap">
            <div id="board-container">
                <div id="chessboard"></div>
            </div>
        </div>

        <!-- Legende -->
        <div id="legend">
            <span><span class="legend-dot" style="background:var(--user-blue);box-shadow:0 0 6px var(--glow-blue)"></span>Du (Weiß)</span>
            <span><span class="legend-dot" style="background:var(--llama-teal);box-shadow:0 0 6px var(--glow-teal)"></span>Llama (Schwarz)</span>
        </div>
    </div>

    <!-- SIDE PANELS -->
    <div class="side-panel">

        <!-- Spielverlauf -->
        <div class="panel" id="panel-protocol">
            <div class="panel-header">📜 Spielverlauf</div>
            <div id="protocol-content">
                <table class="proto-table">
                    <thead>
                        <tr>
                            <th>#</th>
                            <th style="color:var(--user-blue)">♔ Du</th>
                            <th style="color:var(--llama-teal)">♛ Llama</th>
                        </tr>
                    </thead>
                    <tbody id="proto-body"></tbody>
                </table>
            </div>
        </div>

        <!-- Chat -->
        <div class="panel" id="panel-chat">
            <div class="panel-header">💬 Queen Llama Chat</div>
            <div id="chat-messages"></div>
            <div class="chat-input-row">
                <input id="chat-input" placeholder="Frag Llama etwas..."
                       onkeypress="if(event.key==='Enter') sendChat()">
                <button id="send-btn" onclick="sendChat()">➤</button>
            </div>
        </div>

        <!-- Think Tank -->
        <div class="panel" id="panel-think">
            <div class="panel-header">🧠 Think Tank</div>
            <div id="terminal-content"></div>
        </div>

    </div>
</div>

<script>
/* ═══════════════════════════════════════════
   STATE
═══════════════════════════════════════════ */
let chess      = new Chess();
let selected   = null;
let possible   = [];
let isThinking = false;
let lastFrom   = null, lastTo = null;

const PIECES = {
    'K':'♔','Q':'♕','R':'♖','B':'♗','N':'♘','P':'♙',
    'k':'♚','q':'♛','r':'♜','b':'♝','n':'♞','p':'♟'
};

/* ═══════════════════════════════════════════
   API-BASISPFAD (URL-Fix: relativ zum Mount)
═══════════════════════════════════════════ */
function apiBase() {
    // z.B. "/chess" wenn Seite unter /chess/ läuft
    return window.location.pathname.replace(/\/+$/, '');
}

/* ═══════════════════════════════════════════
   INIT
═══════════════════════════════════════════ */
function init() {
    try {
        if (window.Telegram && Telegram.WebApp) {
            Telegram.WebApp.ready();
            Telegram.WebApp.expand();
        }
    } catch(e) {}
    renderBoard();
    updateStatus();
    addTerm('info', 'Crystal Chess bereit ✨');
}

function closeTg() {
    try { Telegram.WebApp.close(); } catch(e) { window.close(); }
}

/* ═══════════════════════════════════════════
   RENDER BOARD
═══════════════════════════════════════════ */
function renderBoard() {
    const board = document.getElementById('chessboard');
    board.innerHTML = '';

    // König im Schach?
    let kingInCheck = null;
    if (chess.in_check()) {
        const turn = chess.turn();
        // König suchen
        for (let r = 7; r >= 0; r--) {
            for (let f = 0; f < 8; f++) {
                const sq = 'abcdefgh'[f] + (r + 1);
                const p = chess.get(sq);
                if (p && p.type === 'k' && p.color === turn) {
                    kingInCheck = sq;
                }
            }
        }
    }

    for (let r = 7; r >= 0; r--) {
        for (let f = 0; f < 8; f++) {
            const sq = 'abcdefgh'[f] + (r + 1);
            const div = document.createElement('div');
            const isLight = (r + f) % 2 !== 0;

            let cls = 'square ' + (isLight ? 'light' : 'dark');
            if (sq === selected)   cls += ' selected';
            if (sq === lastFrom || sq === lastTo) cls += ' last-move';
            if (sq === kingInCheck) cls += ' in-check';

            const piece = chess.get(sq);
            if (possible.includes(sq)) {
                cls += ' possible';
                if (piece) cls += ' occupied';
            }

            div.className = cls;
            div.dataset.sq = sq;
            div.addEventListener('click', () => handleClick(sq));
            div.addEventListener('touchend', (e) => { e.preventDefault(); handleClick(sq); }, { passive: false });

            if (piece) {
                const span = document.createElement('span');
                // ♟ Hellblau = User (Weiß), Helltürkis = Llama (Schwarz)
                span.className = 'piece ' + (piece.color === 'w' ? 'user-piece' : 'llama-piece');
                span.textContent = PIECES[piece.color === 'w'
                    ? piece.type.toUpperCase()
                    : piece.type.toLowerCase()];
                div.appendChild(span);
            }

            board.appendChild(div);
        }
    }
}

/* ═══════════════════════════════════════════
   KLICK / ZUG
═══════════════════════════════════════════ */
function handleClick(sq) {
    if (isThinking || chess.game_over()) return;
    if (chess.turn() !== 'w') return;

    if (selected) {
        if (possible.includes(sq)) {
            // Zug ausführen
            const result = chess.move({ from: selected, to: sq, promotion: 'q' });
            if (result) {
                lastFrom = selected;
                lastTo   = sq;
                addTerm('move', `♔ Du: ${selected}→${sq}  (${result.san})`);
            }
            selected = null;
            possible = [];
            renderBoard();
            updateProtocol();
            updateStatus();
            if (!chess.game_over() && chess.turn() === 'b') {
                setTimeout(llamaMove, 600);
            }
        } else {
            // Andere Figur wählen oder abwählen
            const p = chess.get(sq);
            if (p && p.color === 'w') {
                selected = sq;
                possible = chess.moves({ square: sq, verbose: true }).map(m => m.to);
            } else {
                selected = null;
                possible = [];
            }
            renderBoard();
        }
    } else {
        const p = chess.get(sq);
        if (p && p.color === 'w') {
            selected = sq;
            possible = chess.moves({ square: sq, verbose: true }).map(m => m.to);
            renderBoard();
        }
    }
}

/* ═══════════════════════════════════════════
   LLAMA ZUG
═══════════════════════════════════════════ */
async function llamaMove() {
    if (isThinking) return;
    isThinking = true;
    updateStatus('🧠 Llama denkt...');
    addTerm('think', '⏳ Berechne Zug...');

    const url = apiBase() + '/api/llama_move';
    try {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fen: chess.fen() })
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);

        const data = await res.json();
        addTerm('think', '💭 ' + (data.thought || '...'));

        const move = (data.move || '').toLowerCase().trim();
        let moved = false;

        if (move.length >= 4) {
            const from  = move.slice(0, 2);
            const to    = move.slice(2, 4);
            const promo = move.length === 5 ? move[4] : 'q';
            const result = chess.move({ from, to, promotion: promo });
            if (result) {
                lastFrom = from;
                lastTo   = to;
                addTerm('move', `♛ Llama: ${from}→${to}  (${result.san})`);
                moved = true;
            }
        }
        if (!moved) {
            addTerm('error', `⚠️  Ungültiger Zug "${move}" → Fallback`);
            doFallback();
        }

    } catch(e) {
        addTerm('error', '❌ ' + e.message + ' → Fallback');
        doFallback();
    }

    renderBoard();
    updateProtocol();
    updateStatus();
    isThinking = false;
}

function doFallback() {
    const moves = chess.moves({ verbose: true });
    if (!moves.length) return;
    const m = moves[Math.floor(Math.random() * moves.length)];
    chess.move(m);
    lastFrom = m.from;
    lastTo   = m.to;
    addTerm('move', `🎲 Fallback: ${m.from}→${m.to}  (${m.san})`);
}

/* ═══════════════════════════════════════════
   PROTOKOLL – User UND Llama abwechselnd
═══════════════════════════════════════════ */
function updateProtocol() {
    const hist = chess.history({ verbose: true });
    const tbody = document.getElementById('proto-body');
    tbody.innerHTML = '';
    for (let i = 0; i < hist.length; i += 2) {
        const num  = Math.floor(i / 2) + 1;
        const uSan = hist[i]   ? hist[i].san   : '';
        const lSan = hist[i+1] ? hist[i+1].san : '';
        const tr = document.createElement('tr');
        tr.className = 'proto-row';
        tr.innerHTML =
            `<td class="proto-num">${num}.</td>` +
            `<td class="proto-user">${uSan}</td>` +
            `<td class="proto-llama">${lSan}</td>`;
        tbody.appendChild(tr);
    }
    // Scrolle ans Ende
    const pc = document.getElementById('protocol-content');
    pc.scrollTop = pc.scrollHeight;
}

/* ═══════════════════════════════════════════
   STATUS
═══════════════════════════════════════════ */
function updateStatus(msg) {
    if (chess.in_checkmate()) {
        document.getElementById('status').textContent =
            chess.turn() === 'w' ? '☠️ Du hast verloren!' : '🏆 Du hast gewonnen!';
        return;
    }
    if (chess.in_stalemate()) {
        document.getElementById('status').textContent = '🤝 Patt – Remis!';
        return;
    }
    if (chess.in_draw()) {
        document.getElementById('status').textContent = '🤝 Remis!';
        return;
    }
    if (chess.in_check()) {
        const c = chess.turn() === 'w' ? '♔ Schach! Du bist am Zug' : '♛ Schach! Llama am Zug';
        document.getElementById('status').textContent = msg || c;
        return;
    }
    document.getElementById('status').textContent =
        msg || (chess.turn() === 'w' ? '♔ Du bist am Zug' : '♛ Llama am Zug');
}

/* ═══════════════════════════════════════════
   TERMINAL
═══════════════════════════════════════════ */
function addTerm(type, text) {
    const el = document.getElementById('terminal-content');
    const line = document.createElement('div');
    line.className = 'term-line term-' + type;
    const t = new Date().toLocaleTimeString('de-DE',
        { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    line.textContent = `[${t}] ${text}`;
    el.appendChild(line);
    el.scrollTop = el.scrollHeight;
}

/* ═══════════════════════════════════════════
   NEUES SPIEL
═══════════════════════════════════════════ */
function newGame() {
    chess.reset();
    selected = null;
    possible = [];
    lastFrom = lastTo = null;
    isThinking = false;
    document.getElementById('terminal-content').innerHTML = '';
    document.getElementById('chat-messages').innerHTML = '';
    document.getElementById('proto-body').innerHTML = '';
    renderBoard();
    updateStatus();
    addTerm('info', '♟ Neues Spiel gestartet!');
}

/* ═══════════════════════════════════════════
   CHAT (Groq – dynamisch)
═══════════════════════════════════════════ */
async function sendChat() {
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';

    const chat = document.getElementById('chat-messages');
    const uMsg = document.createElement('div');
    uMsg.className = 'msg user';
    uMsg.innerHTML = `<b>♔ Du</b>${escHtml(text)}`;
    chat.appendChild(uMsg);
    chat.scrollTop = chat.scrollHeight;

    // Waiting indicator
    const wait = document.createElement('div');
    wait.className = 'msg llama';
    wait.innerHTML = `<b>♛ Llama</b><span style="opacity:0.5">tippt...</span>`;
    chat.appendChild(wait);
    chat.scrollTop = chat.scrollHeight;

    const url = apiBase() + '/api/llama_chat';
    try {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text, fen: chess.fen() })
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        wait.innerHTML = `<b>♛ Llama</b>${escHtml(data.reply || '...')}`;
    } catch(e) {
        wait.innerHTML = `<b>♛ Llama</b><span style="color:#ff6666">Verbindungsfehler 😅</span>`;
    }
    chat.scrollTop = chat.scrollHeight;
}

function escHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

/* ═══════════════════════════════════════════
   START
═══════════════════════════════════════════ */
window.addEventListener('load', init);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def chess_root(request: Request):
    return HTMLResponse(HTML_TEMPLATE)


@app.post("/api/llama_move")
async def api_llama_move(data: MoveRequest):
    try:
        if ENGINE_AVAILABLE:
            result = await get_llama_chess_move(data.fen)
            return JSONResponse(content=result)
        else:
            from chess import Board
            b = Board(data.fen)
            legal = list(b.legal_moves)
            move = random.choice(legal).uci() if legal else "e2e4"
            return JSONResponse({"thought": "Engine nicht verfügbar – Zufallszug", "move": move})
    except Exception as e:
        logger.error(f"llama_move Fehler: {e}")
        return JSONResponse({"thought": f"Fehler: {e}", "move": "e2e4"})


@app.post("/api/llama_chat")
async def api_llama_chat(data: ChatRequest):
    """Chat direkt über Groq – kein chess-Modul nötig."""
    import os
    try:
        from groq import Groq

        # FEN-Infos ohne chess-Modul: Feld 2 = am Zug (w/b), Feld 6 = Zugnummer
        fen_parts = data.fen.split()
        turn      = "Weiß (Du)"   if len(fen_parts) > 1 and fen_parts[1] == "w" else "Schwarz (Llama)"
        move_num  = fen_parts[5]  if len(fen_parts) > 5 else "?"

        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        prompt = (
            f"Du bist Queen Llama – eine freche, witzige Schach-Großmeisterin mit viel Persönlichkeit.\n"
            f"Aktuelle Spielposition (FEN): {data.fen}\n"
            f"Am Zug: {turn}, Zugnummer: {move_num}\n"
            f"Der Spieler schreibt: {data.message}\n\n"
            f"Antworte auf Deutsch, kurz (1-3 Sätze), witzig und in deinem Charakter. "
            f"Beziehe dich auf die aktuelle Spielsituation wenn es passt."
        )
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=150,
        )
        reply = completion.choices[0].message.content.strip()
        return JSONResponse({"reply": reply})

    except Exception as e:
        logger.error(f"Chat-Groq-Fehler: {e}")
        return JSONResponse({"reply": f"Groq-Fehler: {type(e).__name__}: {e})"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)