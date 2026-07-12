# archive_mini_app.py – Internet Archive Mini App mit Download-Buttons (Render-Optimized)
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import json
import asyncio
import logging
import base64
from urllib.parse import quote

from archive_org_module import get_archive_client, ArchiveOrgClient

logger = logging.getLogger(__name__)

app = FastAPI(title="Archive.org Workspace")

# ── WebSocket Connection Manager ─────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        try:
            await websocket.send_text(message)
        except:
            pass

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                pass

manager = ConnectionManager()


# ── HTML Template mit Download-Integration ───────────────────────────────────
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Archive.org Workspace</title>
    <style>
        :root {
            --bg: #0a0a0f;
            --surface: #12121a;
            --surface-hover: #1a1a25;
            --border: #2a2a3a;
            --accent: #ff6b35;
            --accent-secondary: #4ecdc4;
            --text: #e0e0e0;
            --text-muted: #888;
            --success: #2ecc71;
            --error: #e74c3c;
            --warning: #f39c12;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            background: var(--bg);
            color: var(--text);
            font-family: 'Segoe UI', system-ui, sans-serif;
            height: 100vh;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }

        .header {
            background: var(--surface);
            border-bottom: 1px solid var(--border);
            padding: 12px 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-shrink: 0;
        }

        .header h1 {
            font-size: 1.2rem;
            background: linear-gradient(135deg, var(--accent), var(--accent-secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .status {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.85rem;
            color: var(--text-muted);
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--success);
            animation: pulse 2s infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        .main-container {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        /* ── OBERES FENSTER: Chat ── */
        .chat-section {
            flex: 1;
            display: flex;
            flex-direction: column;
            border-bottom: 2px solid var(--border);
            min-height: 0;
        }

        .chat-header {
            background: var(--surface);
            padding: 10px 20px;
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 0.9rem;
            color: var(--accent-secondary);
        }

        .chat-messages {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .message {
            max-width: 90%;
            padding: 12px 16px;
            border-radius: 12px;
            font-size: 0.9rem;
            line-height: 1.5;
            animation: fadeIn 0.3s ease;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .message.user {
            align-self: flex-end;
            background: linear-gradient(135deg, var(--accent), #ff8c5a);
            color: white;
        }

        .message.agent {
            align-self: flex-start;
            background: var(--surface);
            border: 1px solid var(--border);
        }

        .message.system {
            align-self: center;
            background: rgba(78, 205, 196, 0.1);
            border: 1px solid var(--accent-secondary);
            color: var(--accent-secondary);
            font-size: 0.85rem;
        }

        .message-time {
            font-size: 0.7rem;
            opacity: 0.6;
            margin-top: 4px;
        }

        /* Download Buttons im Chat */
        .download-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 8px;
            margin-top: 10px;
        }

        .download-btn {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 12px;
            background: rgba(46, 204, 113, 0.1);
            border: 1px solid var(--success);
            border-radius: 8px;
            color: var(--success);
            text-decoration: none;
            font-size: 0.8rem;
            transition: all 0.2s;
            cursor: pointer;
        }

        .download-btn:hover {
            background: rgba(46, 204, 113, 0.2);
            transform: translateY(-1px);
        }

        .download-btn .file-icon {
            font-size: 1.2rem;
        }

        .download-btn .file-info {
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        .download-btn .file-name {
            font-weight: 600;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .download-btn .file-meta {
            font-size: 0.7rem;
            opacity: 0.8;
        }

        .chat-input-area {
            padding: 15px 20px;
            background: var(--surface);
            border-top: 1px solid var(--border);
            display: flex;
            gap: 10px;
        }

        .chat-input {
            flex: 1;
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 10px 15px;
            color: var(--text);
            font-size: 0.9rem;
            outline: none;
            transition: border-color 0.2s;
        }

        .chat-input:focus {
            border-color: var(--accent);
        }

        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.9rem;
            font-weight: 600;
            transition: all 0.2s;
        }

        .btn-primary {
            background: linear-gradient(135deg, var(--accent), #ff8c5a);
            color: white;
        }

        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 15px rgba(255, 107, 53, 0.4);
        }

        .btn-secondary {
            background: var(--surface-hover);
            color: var(--text);
            border: 1px solid var(--border);
        }

        /* ── UNTERES FENSTER: API Workplace ── */
        .workplace-section {
            flex: 1;
            display: flex;
            flex-direction: column;
            min-height: 0;
        }

        .workplace-tabs {
            display: flex;
            background: var(--surface);
            border-bottom: 1px solid var(--border);
        }

        .tab {
            padding: 12px 24px;
            cursor: pointer;
            border: none;
            background: transparent;
            color: var(--text-muted);
            font-size: 0.85rem;
            border-bottom: 2px solid transparent;
            transition: all 0.2s;
        }

        .tab.active {
            color: var(--accent);
            border-bottom-color: var(--accent);
            background: rgba(255, 107, 53, 0.05);
        }

        .tab:hover {
            color: var(--text);
        }

        .workplace-content {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
        }

        .panel {
            display: none;
        }

        .panel.active {
            display: block;
            animation: fadeIn 0.3s ease;
        }

        .search-box {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }

        .search-input {
            flex: 1;
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 12px;
            color: var(--text);
            font-size: 0.9rem;
        }

        .results-grid {
            display: grid;
            gap: 12px;
        }

        .result-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 16px;
            cursor: pointer;
            transition: all 0.2s;
        }

        .result-card:hover {
            border-color: var(--accent);
            transform: translateX(5px);
        }

        .result-title {
            font-weight: 600;
            color: var(--accent);
            margin-bottom: 6px;
        }

        .result-meta {
            font-size: 0.8rem;
            color: var(--text-muted);
            display: flex;
            gap: 15px;
            margin-bottom: 8px;
        }

        .result-desc {
            font-size: 0.85rem;
            color: var(--text);
            line-height: 1.4;
        }

        .result-actions {
            display: flex;
            gap: 8px;
            margin-top: 10px;
        }

        .btn-small {
            padding: 6px 12px;
            font-size: 0.8rem;
        }

        .upload-zone {
            border: 2px dashed var(--border);
            border-radius: 12px;
            padding: 40px;
            text-align: center;
            cursor: pointer;
            transition: all 0.2s;
            margin-bottom: 20px;
        }

        .upload-zone:hover {
            border-color: var(--accent);
            background: rgba(255, 107, 53, 0.05);
        }

        .upload-zone.dragover {
            border-color: var(--accent);
            background: rgba(255, 107, 53, 0.1);
        }

        .metadata-form {
            display: grid;
            gap: 12px;
        }

        .form-group {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }

        .form-label {
            font-size: 0.85rem;
            color: var(--text-muted);
        }

        .form-input {
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 10px;
            color: var(--text);
            font-size: 0.9rem;
        }

        .details-header {
            display: flex;
            justify-content: space-between;
            align-items: start;
            margin-bottom: 20px;
        }

        .file-list {
            display: grid;
            gap: 8px;
        }

        .file-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px;
            background: var(--surface);
            border-radius: 6px;
            border: 1px solid var(--border);
        }

        .file-name {
            font-family: monospace;
            font-size: 0.85rem;
        }

        .file-size {
            color: var(--text-muted);
            font-size: 0.8rem;
        }

        .log-container {
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 15px;
            font-family: 'Courier New', monospace;
            font-size: 0.85rem;
            max-height: 300px;
            overflow-y: auto;
        }

        .log-entry {
            margin-bottom: 8px;
            padding-bottom: 8px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }

        .log-time {
            color: var(--accent-secondary);
            font-size: 0.75rem;
        }

        .log-info { color: var(--success); }
        .log-error { color: var(--error); }
        .log-warn { color: var(--warning); }

        .loading {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 2px solid var(--border);
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .typing-indicator {
            display: flex;
            gap: 4px;
            padding: 12px 16px;
        }

        .typing-indicator span {
            width: 8px;
            height: 8px;
            background: var(--accent);
            border-radius: 50%;
            animation: bounce 1.4s infinite ease-in-out both;
        }

        .typing-indicator span:nth-child(1) { animation-delay: -0.32s; }
        .typing-indicator span:nth-child(2) { animation-delay: -0.16s; }

        @keyframes bounce {
            0%, 80%, 100% { transform: scale(0); }
            40% { transform: scale(1); }
        }

        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: var(--bg); }
        ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: var(--accent); }
    </style>
</head>
<body>
    <div class="header">
        <h1>📚 Archive.org Workspace</h1>
        <div class="status">
            <div class="status-dot"></div>
            <span id="connection-status">Verbunden</span>
        </div>
    </div>

    <div class="main-container">
        <!-- ═══ OBERES FENSTER: LLM Chat mit Downloads ═══ -->
        <div class="chat-section">
            <div class="chat-header">
                <span>🤖</span>
                <span>LLM Agent – Archive.org Assistant</span>
            </div>
            <div class="chat-messages" id="chat-messages">
                <div class="message system">
                    Willkommen! Ich bin dein Archive.org Agent. Frag mich nach Büchern, Medien oder Items – ich zeige dir direkt Download-Links an!
                    <div class="message-time">Jetzt</div>
                </div>
            </div>
            <div class="chat-input-area">
                <input type="text" class="chat-input" id="chat-input" 
                       placeholder="Suche nach Büchern, Videos, Audio..." 
                       onkeypress="if(event.key==='Enter') sendMessage()">
                <button class="btn btn-primary" onclick="sendMessage()">Senden</button>
                <button class="btn btn-secondary" onclick="clearChat()">Clear</button>
            </div>
        </div>

        <!-- ═══ UNTERES FENSTER: API Workplace ═══ -->
        <div class="workplace-section">
            <div class="workplace-tabs">
                <button class="tab active" onclick="switchTab('search')">🔍 Suche</button>
                <button class="tab" onclick="switchTab('upload')">⬆️ Upload</button>
                <button class="tab" onclick="switchTab('details')">📋 Details</button>
                <button class="tab" onclick="switchTab('logs')">📜 Logs</button>
            </div>

            <div class="workplace-content">
                <!-- Search Panel -->
                <div class="panel active" id="panel-search">
                    <div class="search-box">
                        <input type="text" class="search-input" id="search-input" 
                               placeholder="Suche auf Archive.org..." 
                               onkeypress="if(event.key==='Enter') performSearch()">
                        <button class="btn btn-primary" onclick="performSearch()">Suchen</button>
                    </div>
                    <div class="results-grid" id="search-results">
                        <div class="result-card">
                            <div class="result-title">Tippe einen Suchbegriff ein</div>
                            <div class="result-desc">Zum Beispiel: 'python programming', 'old radio shows', 'nasa images'</div>
                        </div>
                    </div>
                </div>

                <!-- Upload Panel -->
                <div class="panel" id="panel-upload">
                    <div class="upload-zone" id="upload-zone" 
                         onclick="document.getElementById('file-input').click()"
                         ondrop="handleDrop(event)" ondragover="handleDragOver(event)" ondragleave="handleDragLeave(event)">
                        <div style="font-size: 2rem; margin-bottom: 10px;">📁</div>
                        <div>Dateien hierher ziehen oder klicken zum Auswählen</div>
                        <div style="color: var(--text-muted); font-size: 0.85rem; margin-top: 8px;">
                            Unterstützt: PDF, EPUB, Audio, Video, Bilder
                        </div>
                    </div>
                    <input type="file" id="file-input" style="display: none;" onchange="handleFileSelect(event)">

                    <div class="metadata-form">
                        <div class="form-group">
                            <label class="form-label">Item Identifier (eindeutig)</label>
                            <input type="text" class="form-input" id="upload-identifier" placeholder="mein-item-2024">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Titel</label>
                            <input type="text" class="form-input" id="upload-title" placeholder="Mein Dokument">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Beschreibung</label>
                            <input type="text" class="form-input" id="upload-desc" placeholder="Kurze Beschreibung...">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Mediatyp</label>
                            <select class="form-input" id="upload-mediatype">
                                <option value="data">Data</option>
                                <option value="texts">Texts</option>
                                <option value="audio">Audio</option>
                                <option value="movies">Movies</option>
                                <option value="software">Software</option>
                                <option value="image">Image</option>
                            </select>
                        </div>
                        <button class="btn btn-primary" onclick="performUpload()" style="margin-top: 10px;">
                            ⬆️ Zu Archive.org hochladen
                        </button>
                    </div>
                </div>

                <!-- Details Panel -->
                <div class="panel" id="panel-details">
                    <div class="search-box">
                        <input type="text" class="search-input" id="details-input" 
                               placeholder="Item ID eingeben..." 
                               onkeypress="if(event.key==='Enter') loadDetails()">
                        <button class="btn btn-primary" onclick="loadDetails()">Laden</button>
                    </div>
                    <div id="details-content">
                        <div class="result-card">
                            <div class="result-title">Item-Details</div>
                            <div class="result-desc">Gib eine Item-ID ein um Metadaten und Dateien zu sehen.</div>
                        </div>
                    </div>
                </div>

                <!-- Logs Panel -->
                <div class="panel" id="panel-logs">
                    <div class="log-container" id="log-container">
                        <div class="log-entry">
                            <span class="log-time">System</span>
                            <span class="log-info"> Workspace initialisiert. Bereit für API-Operationen.</span>
                        </div>
                    </div>
                    <button class="btn btn-secondary" onclick="clearLogs()" style="margin-top: 10px;">
                        Logs leeren
                    </button>
                </div>
            </div>
        </div>
    </div>

    <script>
        // ── WebSocket mit Render-kompatibler URL ──
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const ws = new WebSocket(`${wsProtocol}//${window.location.host}/archive/ws`);
        let currentFile = null;
        let currentDownloads = []; // Speichert aktuelle Downloads für den Chat

        ws.onopen = () => {
            log('WebSocket verbunden', 'info');
            updateStatus('Verbunden', true);
        };

        ws.onclose = () => {
            log('WebSocket getrennt', 'warn');
            updateStatus('Getrennt', false);
        };

        ws.onerror = (e) => {
            log('WebSocket Fehler', 'error');
            updateStatus('Fehler', false);
        };

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            handleMessage(data);
        };

        // ── Chat mit Download-Buttons ──
        function sendMessage() {
            const input = document.getElementById('chat-input');
            const text = input.value.trim();
            if (!text) return;

            addMessage(text, 'user');
            input.value = '';
            showTyping();

            ws.send(JSON.stringify({
                type: 'chat',
                message: text
            }));
        }

        function addMessage(text, sender, downloads = null) {
            const container = document.getElementById('chat-messages');
            const msg = document.createElement('div');
            msg.className = `message ${sender}`;
            const time = new Date().toLocaleTimeString('de-DE', {hour: '2-digit', minute: '2-digit'});

            let html = escapeHtml(text);

            // Füge Download-Buttons hinzu wenn vorhanden
            if (downloads && downloads.length > 0) {
                html += '<div class="download-grid">';
                downloads.forEach(dl => {
                    const icon = getFileIcon(dl.format);
                    html += `
                        <a href="${dl.url}" target="_blank" class="download-btn" download>
                            <span class="file-icon">${icon}</span>
                            <div class="file-info">
                                <span class="file-name">${escapeHtml(dl.name)}</span>
                                <span class="file-meta">${dl.format} | ${formatBytes(dl.size)}</span>
                            </div>
                        </a>
                    `;
                });
                html += '</div>';
            }

            html += `<div class="message-time">${time}</div>`;
            msg.innerHTML = html;
            container.appendChild(msg);
            container.scrollTop = container.scrollHeight;
        }

        function getFileIcon(format) {
            const icons = {
                'pdf': '📄', 'epub': '📖', 'txt': '📝', 'doc': '📘',
                'mp3': '🎵', 'wav': '🎶', 'ogg': '🎧', 'flac': '🎼',
                'mp4': '🎬', 'avi': '📹', 'mkv': '🎥', 'mov': '📽️',
                'jpg': '🖼️', 'png': '🎨', 'gif': '🎭', 'svg': '✨',
                'zip': '📦', 'rar': '🗜️', '7z': '🗃️',
                'py': '🐍', 'js': '⚡', 'html': '🌐', 'css': '🎨'
            };
            return icons[format.toLowerCase()] || '📎';
        }

        function showTyping() {
            const container = document.getElementById('chat-messages');
            const typing = document.createElement('div');
            typing.className = 'message agent typing-indicator';
            typing.id = 'typing';
            typing.innerHTML = '<span></span><span></span><span></span>';
            container.appendChild(typing);
            container.scrollTop = container.scrollHeight;
        }

        function hideTyping() {
            const typing = document.getElementById('typing');
            if (typing) typing.remove();
        }

        function clearChat() {
            document.getElementById('chat-messages').innerHTML = `
                <div class="message system">
                    Chat zurückgesetzt. Frag mich nach Büchern oder Medien – ich zeige dir direkt die Downloads!
                    <div class="message-time">Jetzt</div>
                </div>
            `;
        }

        // ── Workplace Tabs ──
        function switchTab(tab) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
            event.target.classList.add('active');
            document.getElementById(`panel-${tab}`).classList.add('active');
        }

        // ── Search ──
        function performSearch() {
            const query = document.getElementById('search-input').value.trim();
            if (!query) return;

            const results = document.getElementById('search-results');
            results.innerHTML = '<div class="loading"></div>';

            ws.send(JSON.stringify({
                type: 'search',
                query: query
            }));

            log(`Suche gestartet: "${query}"`, 'info');
        }

        function displaySearchResults(data) {
            const container = document.getElementById('search-results');
            if (!data.success) {
                container.innerHTML = `<div class="result-card"><div class="result-title" style="color: var(--error)">Fehler</div><div class="result-desc">${data.error}</div></div>`;
                return;
            }

            if (data.items.length === 0) {
                container.innerHTML = '<div class="result-card"><div class="result-title">Keine Ergebnisse</div></div>';
                return;
            }

            container.innerHTML = data.items.map(item => `
                <div class="result-card" onclick="selectItem('${item.identifier}')">
                    <div class="result-title">${escapeHtml(item.title)}</div>
                    <div class="result-meta">
                        <span>👤 ${escapeHtml(item.creator)}</span>
                        <span>📅 ${item.date}</span>
                        <span>⬇️ ${item.downloads} Downloads</span>
                    </div>
                    <div class="result-desc">${escapeHtml(item.description || '')}</div>
                    <div class="result-actions">
                        <button class="btn btn-secondary btn-small" onclick="event.stopPropagation(); quickDetails('${item.identifier}')">Details</button>
                        <button class="btn btn-primary btn-small" onclick="event.stopPropagation(); askInChat('${item.identifier}')">Im Chat öffnen</button>
                    </div>
                </div>
            `).join('');
        }

        function selectItem(identifier) {
            document.getElementById('details-input').value = identifier;
            switchTab('details');
            loadDetails();
        }

        function quickDetails(identifier) {
            ws.send(JSON.stringify({
                type: 'details',
                identifier: identifier
            }));
        }

        function askInChat(identifier) {
            document.getElementById('chat-input').value = `Zeige Details für ${identifier}`;
            sendMessage();
        }

        // ── Details ──
        function loadDetails() {
            const identifier = document.getElementById('details-input').value.trim();
            if (!identifier) return;

            document.getElementById('details-content').innerHTML = '<div class="loading"></div>';
            ws.send(JSON.stringify({
                type: 'details',
                identifier: identifier
            }));
        }

        function displayDetails(data) {
            const container = document.getElementById('details-content');
            if (!data.success) {
                container.innerHTML = `<div class="result-card"><div class="result-title" style="color: var(--error)">Fehler</div><div class="result-desc">${data.error}</div></div>`;
                return;
            }

            container.innerHTML = `
                <div class="details-header">
                    <div>
                        <h2 style="color: var(--accent); margin-bottom: 8px;">${escapeHtml(data.title)}</h2>
                        <div style="color: var(--text-muted); font-size: 0.9rem;">
                            ID: ${data.identifier} | Von: ${escapeHtml(data.creator)} | ${data.date}
                        </div>
                    </div>
                    <a href="https://archive.org/details/${data.identifier}" target="_blank" class="btn btn-primary btn-small">
                        Auf Archive.org öffnen ↗
                    </a>
                </div>
                <div style="margin-bottom: 20px; line-height: 1.6;">
                    ${escapeHtml(data.description)}
                </div>
                <h3 style="margin-bottom: 12px; color: var(--accent-secondary);">Dateien (${data.files_count})</h3>
                <div class="file-list">
                    ${data.files.map(f => `
                        <div class="file-item">
                            <div>
                                <div class="file-name">${escapeHtml(f.name)}</div>
                                <div class="file-size">${f.format} | ${formatBytes(f.size)}</div>
                            </div>
                            <a href="https://archive.org/download/${data.identifier}/${encodeURIComponent(f.name)}" 
                               target="_blank" class="btn btn-secondary btn-small" download>
                                ⬇️
                            </a>
                        </div>
                    `).join('')}
                </div>
            `;
        }

        // ── Upload ──
        function handleDragOver(e) {
            e.preventDefault();
            document.getElementById('upload-zone').classList.add('dragover');
        }

        function handleDragLeave(e) {
            e.preventDefault();
            document.getElementById('upload-zone').classList.remove('dragover');
        }

        function handleDrop(e) {
            e.preventDefault();
            document.getElementById('upload-zone').classList.remove('dragover');
            const files = e.dataTransfer.files;
            if (files.length > 0) handleFile(files[0]);
        }

        function handleFileSelect(e) {
            if (e.target.files.length > 0) handleFile(e.target.files[0]);
        }

        function handleFile(file) {
            currentFile = file;
            document.getElementById('upload-zone').innerHTML = `
                <div style="font-size: 2rem; margin-bottom: 10px;">✅</div>
                <div><strong>${escapeHtml(file.name)}</strong></div>
                <div style="color: var(--text-muted); font-size: 0.85rem;">
                    ${formatBytes(file.size)} | Bereit zum Upload
                </div>
            `;
            log(`Datei ausgewählt: ${file.name} (${formatBytes(file.size)})`, 'info');
        }

        function performUpload() {
            if (!currentFile) {
                alert('Bitte zuerst eine Datei auswählen');
                return;
            }

            const identifier = document.getElementById('upload-identifier').value.trim();
            const title = document.getElementById('upload-title').value.trim();

            if (!identifier || !title) {
                alert('Identifier und Titel sind erforderlich');
                return;
            }

            const reader = new FileReader();
            reader.onload = (e) => {
                const base64 = e.target.result.split(',')[1];
                ws.send(JSON.stringify({
                    type: 'upload',
                    identifier: identifier,
                    filename: currentFile.name,
                    file_data: base64,
                    title: title,
                    description: document.getElementById('upload-desc').value,
                    mediatype: document.getElementById('upload-mediatype').value
                }));
                log(`Upload gestartet: ${identifier}/${currentFile.name}`, 'info');
            };
            reader.readAsDataURL(currentFile);
        }

        // ── Logs ──
        function log(message, level = 'info') {
            const container = document.getElementById('log-container');
            const time = new Date().toLocaleTimeString('de-DE');
            const entry = document.createElement('div');
            entry.className = 'log-entry';
            entry.innerHTML = `<span class="log-time">[${time}]</span> <span class="log-${level}">${escapeHtml(message)}</span>`;
            container.appendChild(entry);
            container.scrollTop = container.scrollHeight;
        }

        function clearLogs() {
            document.getElementById('log-container').innerHTML = '';
        }

        // ── Status ──
        function updateStatus(text, connected) {
            const status = document.getElementById('connection-status');
            const dot = document.querySelector('.status-dot');
            status.textContent = text;
            dot.style.background = connected ? 'var(--success)' : 'var(--error)';
            dot.style.animation = connected ? 'pulse 2s infinite' : 'none';
        }

        // ── Message Handler ──
        function handleMessage(data) {
            switch(data.type) {
                case 'chat_response':
                    hideTyping();
                    addMessage(data.message, 'agent', data.downloads);
                    break;
                case 'search_results':
                    displaySearchResults(data);
                    break;
                case 'details_result':
                    displayDetails(data);
                    break;
                case 'upload_result':
                    handleUploadResult(data);
                    break;
                case 'error':
                    hideTyping();
                    addMessage('Fehler: ' + data.message, 'system');
                    log('Fehler: ' + data.message, 'error');
                    break;
                case 'log':
                    log(data.message, data.level || 'info');
                    break;
            }
        }

        function handleUploadResult(data) {
            if (data.success) {
                log(`Upload erfolgreich: ${data.url}`, 'info');
                addMessage(`✅ Upload erfolgreich!`, 'system');
            } else {
                log(`Upload fehlgeschlagen: ${data.error}`, 'error');
                addMessage(`❌ Upload fehlgeschlagen: ${data.error}`, 'system');
            }
        }

        // ── Utilities ──
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function formatBytes(bytes) {
            if (bytes === 0) return '0 Bytes';
            const k = 1024;
            const sizes = ['Bytes', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }

        // Enter-Taste im Chat
        document.getElementById('chat-input').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') sendMessage();
        });
    </script>
</body>
</html>
"""


# ── Routes ───────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def archive_workspace():
    return HTMLResponse(content=HTML_TEMPLATE)


# Proxy-Route für Downloads (um CORS zu vermeiden)
@app.get("/proxy/download/{identifier}/{filename:path}")
async def proxy_download(identifier: str, filename: str):
    """Proxy für Archive.org Downloads – ermöglicht direkte Downloads aus dem Chat."""
    client = get_archive_client()
    file_bytes = await client.download_file(identifier, filename)

    if not file_bytes:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Download fehlgeschlagen"}, status_code=404)

    from io import BytesIO
    return StreamingResponse(
        BytesIO(file_bytes),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


@app.websocket("/ws")
async def archive_websocket(websocket: WebSocket):
    await manager.connect(websocket)
    client = get_archive_client()

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            msg_type = message.get("type")

            # ── Chat mit LLM-Agent + Download-Buttons ──
            if msg_type == "chat":
                user_msg = message.get("message", "")
                await manager.send_personal_message(
                    json.dumps({"type": "log", "message": f"Chat-Anfrage: {user_msg[:50]}...", "level": "info"}),
                    websocket
                )

                # Intelligente Befehlserkennung
                lower_msg = user_msg.lower()

                # Suche nach Items
                if any(kw in lower_msg for kw in ["suche", "search", "finde", "find", "buch", "book", "video", "audio"]):
                    query = user_msg
                    for kw in ["suche", "search", "finde", "find", "nach", "for"]:
                        query = query.replace(kw, "", 1).strip()

                    result = await client.search(query, rows=5)

                    if result["success"] and result["items"]:
                        items = result["items"]
                        response = f"🔍 **{result['total']} Ergebnisse** für '{query}':\n\n"
                        downloads = []

                        for item in items:
                            response += f"📚 **{item['title']}**\n"
                            response += f"   ID: `{item['identifier']}`\n"
                            response += f"   👤 {item['creator']} | 📅 {item['date']}\n"
                            response += f"   ⬇️ {item['downloads']} Downloads\n\n"

                            # Erstelle Download-Links
                            downloads.append({
                                "name": item['title'][:40],
                                "url": f"https://archive.org/download/{item['identifier']}",
                                "format": "archive",
                                "size": 0
                            })

                        response += "Klicke auf die Buttons unten um direkt zu den Items zu gelangen!"

                        await manager.send_personal_message(
                            json.dumps({
                                "type": "chat_response", 
                                "message": response,
                                "downloads": downloads
                            }),
                            websocket
                        )
                    else:
                        await manager.send_personal_message(
                            json.dumps({
                                "type": "chat_response", 
                                "message": f"❌ Keine Ergebnisse für '{query}' gefunden.\n\nTipps:\n• Versuche allgemeinere Begriffe\n• Prüfe die Schreibweise\n• Nutze englische Begriffe für bessere Ergebnisse"
                            }),
                            websocket
                        )

                # Details für spezifisches Item
                elif any(kw in lower_msg for kw in ["details", "detail", "zeige", "show", "info"]):
                    # Extrahiere Identifier
                    words = user_msg.split()
                    identifier = None
                    for word in words:
                        if len(word) > 5 and not word.lower() in ["details", "detail", "zeige", "show", "info", "für", "for"]:
                            identifier = word.strip("`[](){}<>")
                            break

                    if identifier:
                        result = await client.get_metadata(identifier)

                        if result["success"]:
                            files = result["files"][:10]  # Top 10 Dateien
                            response = (
                                f"📋 **{result['title']}**\n\n"
                                f"ID: `{result['identifier']}`\n"
                                f"👤 {result['creator']} | 📅 {result['date']}\n"
                                f"📊 Typ: {result['mediatype']} | ⬇️ {result['downloads']} Downloads\n\n"
                                f"**Verfügbare Dateien:**\n"
                            )

                            downloads = []
                            for f in files:
                                size_mb = int(f['size']) / (1024*1024) if f['size'] else 0
                                response += f"  • {f['name']} ({f['format']}, {size_mb:.1f} MB)\n"
                                downloads.append({
                                    "name": f['name'],
                                    "url": f"https://archive.org/download/{identifier}/{f['name']}",
                                    "format": f['format'],
                                    "size": int(f['size']) if f['size'] else 0
                                })

                            response += f"\n[🔗 Auf Archive.org öffnen](https://archive.org/details/{identifier})"

                            await manager.send_personal_message(
                                json.dumps({
                                    "type": "chat_response",
                                    "message": response,
                                    "downloads": downloads
                                }),
                                websocket
                            )
                        else:
                            await manager.send_personal_message(
                                json.dumps({
                                    "type": "chat_response",
                                    "message": f"❌ Item `{identifier}` nicht gefunden.\n\nMögliche Gründe:\n• Falsche ID\n• Item wurde entfernt\n• Temporär nicht verfügbar"
                                }),
                                websocket
                            )
                    else:
                        await manager.send_personal_message(
                            json.dumps({
                                "type": "chat_response",
                                "message": "Bitte gib eine Item-ID an.\nBeispiel: 'Zeige Details für python_cookbook_2013'"
                            }),
                            websocket
                        )

                # Hilfe / Default
                else:
                    response = (
                        "🤖 **Archive.org Agent**\n\n"
                        "Ich kann dir helfen mit:\n\n"
                        "📚 **Suche**: *'Suche nach [Begriff]'*\n"
                        "   → Finde Bücher, Videos, Audio, Software\n\n"
                        "📋 **Details**: *'Zeige Details für [Item-ID]'*\n"
                        "   → Metadaten und alle verfügbaren Dateien\n\n"
                        "⬇️ **Downloads**: Die Dateien erscheinen als Buttons unter meiner Antwort!\n\n"
                        "Tippe einfach deine Anfrage..."
                    )
                    await manager.send_personal_message(
                        json.dumps({"type": "chat_response", "message": response}),
                        websocket
                    )

            # ── Direkte Suche ──
            elif msg_type == "search":
                query = message.get("query", "")
                result = await client.search(query, rows=20)
                await manager.send_personal_message(
                    json.dumps({"type": "search_results", **result}),
                    websocket
                )

            # ── Details laden ──
            elif msg_type == "details":
                identifier = message.get("identifier", "")
                result = await client.get_metadata(identifier)
                await manager.send_personal_message(
                    json.dumps({"type": "details_result", **result}),
                    websocket
                )

            # ── Upload ──
            elif msg_type == "upload":
                identifier = message.get("identifier")
                filename = message.get("filename")
                file_data = base64.b64decode(message.get("file_data", ""))
                title = message.get("title", filename)
                description = message.get("description", "")
                mediatype = message.get("mediatype", "data")

                metadata = {
                    "title": title,
                    "description": description,
                    "mediatype": mediatype,
                }

                result = await client.upload_file(identifier, file_data, filename, metadata)
                await manager.send_personal_message(
                    json.dumps({"type": "upload_result", **result}),
                    websocket
                )

            else:
                await manager.send_personal_message(
                    json.dumps({"type": "error", "message": "Unbekannter Nachrichtentyp"}),
                    websocket
                )

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket Fehler: {e}")
        try:
            await manager.send_personal_message(
                json.dumps({"type": "error", "message": str(e)}),
                websocket
            )
        except:
            pass
        manager.disconnect(websocket)
