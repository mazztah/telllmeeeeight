
# V6 – Komplette Neubau für Android-Smartphones
# - Ausführen NUR per Button-Tap
# - Terminal kollabiert automatisch, lässt sich per Toggle minimieren
# - Datei-Upload funktioniert
# - Alles Touch-optimiert

# sandbox_mini_app.py – Queen's Code Sandbox Mini App (V6 – ANDROID OPTIMIERT)
import asyncio
import json
import logging
import os
import re
import time
from io import BytesIO
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse

from sandbox_runner import (
    EXAMPLE_TEMPLATES,
    generate_html_app,
    get_example_templates,
    run_sandboxed_code,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="Queen's Code Sandbox V6")

# ── HTML Template ──────────────────────────────────────────────────────────────
SANDBOX_HTML = r"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Queen's Code Sandbox</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/ace/1.32.0/ace.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/ace/1.32.0/mode-python.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/ace/1.32.0/mode-html.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/ace/1.32.0/theme-monokai.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0f0f1a;
            --surface: #1a1a2e;
            --surface2: #252540;
            --surface3: #2e2e50;
            --border: #2a2f3f;
            --border2: #3a3f55;
            --text: #e8ecf4;
            --text2: #b8bdd4;
            --muted: #7a8099;
            --accent: #a78bfa;
            --accent2: #00d4aa;
            --gold: #f5c242;
            --red: #ff3366;
            --green: #34d399;
            --orange: #fbbf24;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        html, body {
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            background: var(--bg);
            color: var(--text);
            height: 100%;
            width: 100%;
            overflow: hidden;
            -webkit-tap-highlight-color: transparent;
            touch-action: manipulation;
        }

        #app { display: flex; flex-direction: column; height: 100vh; width: 100vw; }

        /* ===== HEADER ===== */
        #header {
            background: linear-gradient(180deg, var(--surface), var(--surface2));
            border-bottom: 1px solid var(--border);
            padding: 10px 12px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            height: 52px;
            flex-shrink: 0;
            z-index: 10;
        }
        #header h1 {
            font-size: 1rem;
            font-weight: 700;
            color: var(--accent);
            display: flex;
            align-items: center;
            gap: 6px;
            white-space: nowrap;
        }
        .header-btns { display: flex; gap: 8px; align-items: center; }

        /* ===== BUTTONS ===== */
        .btn {
            border: none;
            border-radius: 10px;
            padding: 10px 16px;
            font-size: 0.9rem;
            font-weight: 700;
            font-family: inherit;
            cursor: pointer;
            transition: all 0.15s ease;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            white-space: nowrap;
            -webkit-tap-highlight-color: transparent;
            touch-action: manipulation;
            user-select: none;
            -webkit-user-select: none;
            min-height: 44px;
        }
        .btn:hover { filter: brightness(1.15); }
        .btn:active { transform: scale(0.95); }
        .btn-run {
            background: linear-gradient(135deg, var(--accent), var(--accent2));
            color: #fff;
            box-shadow: 0 4px 20px rgba(167, 139, 250, 0.4);
            font-size: 1rem;
            padding: 12px 20px;
        }
        .btn-run.running {
            background: linear-gradient(135deg, var(--orange), var(--gold));
            animation: pulse 1.5s ease-in-out infinite;
            pointer-events: none;
        }
        .btn-secondary {
            background: var(--surface3);
            color: var(--text2);
            border: 1px solid var(--border2);
        }
        .btn-secondary:hover { border-color: var(--accent); }
        .btn-gold {
            background: linear-gradient(135deg, var(--gold), var(--orange));
            color: #0f0f1a;
        }
        .btn-sm { padding: 8px 12px; font-size: 0.8rem; min-height: 36px; }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
        }

        /* ===== TOOLBAR ===== */
        #toolbar {
            background: var(--surface);
            border-bottom: 1px solid var(--border);
            padding: 8px 12px;
            display: flex;
            gap: 8px;
            align-items: center;
            flex-shrink: 0;
            overflow-x: auto;
            scrollbar-width: none;
            height: 48px;
            z-index: 10;
        }
        #toolbar::-webkit-scrollbar { display: none; }
        .toolbar-group { display: flex; gap: 6px; align-items: center; flex-shrink: 0; }
        .toolbar-sep { width: 1px; height: 20px; background: var(--border2); margin: 0 4px; flex-shrink: 0; }
        select {
            background: var(--surface2);
            color: var(--text);
            border: 1px solid var(--border2);
            border-radius: 8px;
            padding: 6px 10px;
            font-size: 0.85rem;
            font-family: inherit;
            cursor: pointer;
            outline: none;
            min-height: 36px;
        }

        /* ===== WORKSPACE ===== */
        #workspace { 
            display: flex; 
            flex: 1; 
            min-height: 0; 
            position: relative;
            overflow: hidden;
        }

        /* ===== EDITOR ===== */
        #editor-wrap {
            flex: 1;
            display: flex;
            flex-direction: column;
            min-width: 0;
            position: relative;
            background: var(--bg);
        }
        
        #editor-container {
            flex: 1;
            position: relative;
            overflow: hidden;
        }
        
        /* ACE Editor Customization */
        .ace_editor {
            font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace !important;
            font-size: 14px !important;
            line-height: 1.6 !important;
        }
        .ace_gutter {
            background: var(--bg) !important;
            border-right: 1px solid var(--border) !important;
            color: var(--muted) !important;
        }
        .ace_content {
            background: var(--bg) !important;
        }
        .ace_cursor {
            border-left: 2px solid var(--accent) !important;
        }
        .ace_selection {
            background: rgba(167, 139, 250, 0.3) !important;
        }
        .ace_active-line {
            background: rgba(26, 26, 46, 0.8) !important;
        }
        .ace_print-margin {
            display: none !important;
        }

        /* ===== OUTPUT PANEL ===== */
        #output-wrap {
            width: 100%;
            background: var(--surface);
            border-top: 2px solid var(--border);
            display: flex;
            flex-direction: column;
            position: relative;
            flex-shrink: 0;
            height: 40%;
            min-height: 200px;
            transition: height 0.3s ease;
        }
        #output-wrap.collapsed {
            height: 44px !important;
            min-height: 44px !important;
        }
        #output-wrap.collapsed .output-inner {
            display: none;
        }
        #output-wrap.collapsed #collapse-bar {
            border-bottom: none;
        }
        
        #collapse-bar {
            display: flex;
            align-items: center;
            justify-content: center;
            height: 44px;
            background: var(--surface2);
            border-bottom: 1px solid var(--border);
            cursor: pointer;
            gap: 8px;
            color: var(--muted);
            font-size: 0.85rem;
            font-weight: 600;
            -webkit-tap-highlight-color: transparent;
            touch-action: manipulation;
            user-select: none;
        }
        #collapse-bar:active { background: var(--surface3); }
        #collapse-bar .collapse-icon {
            transition: transform 0.3s ease;
        }
        #output-wrap.collapsed #collapse-bar .collapse-icon {
            transform: rotate(180deg);
        }

        .output-inner {
            display: flex;
            flex-direction: column;
            flex: 1;
            min-height: 0;
        }

        #output-tabs {
            display: flex;
            background: var(--surface2);
            border-bottom: 1px solid var(--border);
            flex-shrink: 0;
        }
        .output-tab {
            flex: 1;
            padding: 10px 4px;
            font-size: 0.85rem;
            color: var(--muted);
            cursor: pointer;
            border: none;
            background: transparent;
            border-bottom: 2px solid transparent;
            transition: all 0.15s;
            text-align: center;
            font-family: inherit;
            font-weight: 600;
            -webkit-tap-highlight-color: transparent;
            min-height: 40px;
        }
        .output-tab:hover { color: var(--text); background: rgba(255,255,255,0.03); }
        .output-tab.active { 
            color: var(--accent2); 
            border-bottom-color: var(--accent2); 
            background: rgba(0,212,170,0.05); 
        }

        .output-pane {
            flex: 1;
            overflow-y: auto;
            padding: 12px;
            display: none;
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            font-size: 0.85rem;
            line-height: 1.55;
        }
        .output-pane.active { display: block; }
        .output-pane::-webkit-scrollbar { width: 5px; }
        .output-pane::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 3px; }

        #terminal { color: var(--text); }
        .term-line { margin: 2px 0; word-break: break-word; }
        .term-time { color: var(--muted); font-size: 0.72rem; margin-right: 4px; }
        .term-output { color: var(--text); }
        .term-error { color: var(--red); }
        .term-success { color: var(--green); }
        .term-warn { color: var(--gold); }
        .term-info { color: var(--accent); }

        #plot-pane { align-items: center; justify-content: center; padding: 16px; }
        #plot-pane.active { display: flex; }
        #plot-pane img {
            max-width: 100%;
            max-height: 100%;
            border-radius: 10px;
            border: 1px solid var(--border);
        }

        #file-pane { align-items: center; justify-content: center; }
        #file-pane.active { display: flex; flex-direction: column; gap: 12px; }
        .file-card {
            background: var(--surface2);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 16px;
            display: flex;
            align-items: center;
            gap: 12px;
            cursor: pointer;
            transition: all 0.15s;
            width: 100%;
            max-width: 300px;
        }
        .file-card:hover { border-color: var(--accent); background: var(--surface3); }
        .file-icon { font-size: 2rem; }
        .file-info { flex: 1; }
        .file-name { font-weight: 600; color: var(--text); font-size: 0.95rem; }
        .file-meta { font-size: 0.78rem; color: var(--muted); margin-top: 2px; }

        /* Upload Area */
        .upload-area {
            border: 2px dashed var(--border2);
            border-radius: 12px;
            padding: 24px;
            text-align: center;
            color: var(--muted);
            cursor: pointer;
            transition: all 0.15s;
            width: 100%;
            max-width: 300px;
        }
        .upload-area:hover, .upload-area.dragover {
            border-color: var(--accent);
            background: rgba(167, 139, 250, 0.05);
            color: var(--text);
        }
        .upload-area input[type="file"] {
            display: none;
        }

        /* ===== STATUS BAR ===== */
        #status-bar {
            background: var(--surface2);
            border-top: 1px solid var(--border);
            padding: 6px 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.78rem;
            color: var(--muted);
            flex-shrink: 0;
            height: 34px;
            z-index: 10;
        }
        .status-item { display: flex; align-items: center; gap: 5px; }
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--green);
            flex-shrink: 0;
        }
        .status-dot.busy { background: var(--gold); animation: blink 1s infinite; }
        .status-dot.error { background: var(--red); }
        @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

        /* ===== MODAL ===== */
        #modal-overlay {
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.85);
            z-index: 1000;
            align-items: center;
            justify-content: center;
            padding: 16px;
        }
        #modal-overlay.show { display: flex; }
        .modal-box {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            max-width: 520px;
            width: 100%;
            max-height: 80vh;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            animation: modalIn 0.2s ease;
        }
        @keyframes modalIn {
            from { opacity: 0; transform: scale(0.95); }
            to { opacity: 1; transform: scale(1); }
        }
        .modal-header {
            padding: 16px 18px;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .modal-header h2 { margin: 0; font-size: 1.1rem; color: var(--accent); }
        .modal-close {
            background: none;
            border: none;
            color: var(--muted);
            font-size: 1.8rem;
            cursor: pointer;
            width: 40px;
            height: 40px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 8px;
            transition: all 0.15s;
        }
        .modal-close:hover { color: var(--red); background: rgba(255,51,102,0.1); }
        .modal-body {
            overflow-y: auto;
            padding: 14px;
        }
        .example-item {
            background: var(--surface2);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 14px;
            margin-bottom: 10px;
            cursor: pointer;
            transition: all 0.15s;
        }
        .example-item:hover { border-color: var(--accent); background: var(--surface3); }
        .example-item h3 { margin: 0 0 6px; font-size: 1rem; color: var(--text); }
        .example-item p { margin: 0; font-size: 0.85rem; color: var(--muted); }
        .example-item .tag {
            display: inline-block;
            background: rgba(167, 139, 250, 0.15);
            color: var(--accent);
            padding: 3px 10px;
            border-radius: 6px;
            font-size: 0.72rem;
            margin-top: 8px;
            font-weight: 600;
        }

        /* ===== TOAST ===== */
        #toast {
            position: fixed;
            bottom: 50px;
            left: 50%;
            transform: translateX(-50%) translateY(120px);
            background: var(--surface2);
            border: 1px solid var(--border);
            color: var(--text);
            padding: 12px 24px;
            border-radius: 12px;
            font-size: 0.9rem;
            z-index: 2000;
            opacity: 0;
            transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
            pointer-events: none;
            white-space: nowrap;
            box-shadow: 0 8px 32px rgba(0,0,0,0.4);
        }
        #toast.show { transform: translateX(-50%) translateY(0); opacity: 1; }
    </style>
</head>
<body>
    <div id="app">
        <div id="header">
            <h1><span>👑</span> Queen's Code Sandbox</h1>
            <div class="header-btns">
                <button class="btn btn-secondary btn-sm" id="btn-examples">📚</button>
                <button class="btn btn-secondary btn-sm" id="btn-clear">🗑️</button>
                <button class="btn btn-run" id="btn-run">
                    <span>▶️</span> <span id="run-text">Ausführen</span>
                </button>
            </div>
        </div>

        <div id="toolbar">
            <div class="toolbar-group">
                <select id="lang-select">
                    <option value="python">🐍 Python</option>
                    <option value="html">🌐 HTML</option>
                </select>
            </div>
            <div class="toolbar-sep"></div>
            <div class="toolbar-group">
                <button class="btn btn-secondary btn-sm btn-tpl" data-tpl="hello">👋 Hallo</button>
                <button class="btn btn-secondary btn-sm btn-tpl" data-tpl="plot">📊 Plot</button>
                <button class="btn btn-secondary btn-sm btn-tpl" data-tpl="dataframe">📋 Data</button>
                <button class="btn btn-secondary btn-sm btn-tpl" data-tpl="chart">📈 Chart</button>
                <button class="btn btn-secondary btn-sm btn-tpl" data-tpl="mini_app">🎨 App</button>
            </div>
            <div class="toolbar-sep"></div>
            <div class="toolbar-group">
                <button class="btn btn-secondary btn-sm" id="btn-save">💾</button>
                <button class="btn btn-gold btn-sm" id="btn-share">📤</button>
            </div>
        </div>

        <div id="workspace">
            <div id="editor-wrap">
                <div id="editor-container"></div>
            </div>

            <div id="output-wrap">
                <div id="collapse-bar">
                    <span class="collapse-icon">🔽</span>
                    <span id="collapse-text">Terminal minimieren</span>
                </div>
                <div class="output-inner">
                    <div id="output-tabs">
                        <button class="output-tab active" data-pane="terminal">🖥️ Terminal</button>
                        <button class="output-tab" data-pane="plot">📊 Plot</button>
                        <button class="output-tab" data-pane="file">📁 Datei</button>
                    </div>
                    <div id="terminal" class="output-pane active"></div>
                    <div id="plot-pane" class="output-pane"></div>
                    <div id="file-pane" class="output-pane">
                        <div class="upload-area" id="upload-area">
                            <input type="file" id="file-input" accept=".py,.txt,.csv,.json,.html,.js,.css">
                            <div style="font-size: 2rem; margin-bottom: 8px;">📁</div>
                            <div style="font-weight: 600; margin-bottom: 4px;">Datei hochladen</div>
                            <div style="font-size: 0.78rem;">Tippe zum Auswählen</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <div id="status-bar">
            <div class="status-item">
                <div class="status-dot" id="status-dot"></div>
                <span id="status-text">Bereit</span>
            </div>
            <div class="status-item">
                <span id="cursor-pos">Ln 1, Col 1</span>
            </div>
            <div class="status-item">
                <span id="exec-time"></span>
            </div>
        </div>
    </div>

    <div id="modal-overlay">
        <div class="modal-box">
            <div class="modal-header">
                <h2>📚 Code-Beispiele</h2>
                <button class="modal-close" id="modal-close">×</button>
            </div>
            <div class="modal-body" id="modal-body"></div>
        </div>
    </div>

    <div id="toast"></div>

    <script>
        // ===== STATE =====
        let editor = null;
        let templates = {};
        let isRunning = false;
        let outputCollapsed = false;
        let currentPane = 'terminal';

        // ===== DOM REFS =====
        const editorContainer = document.getElementById('editor-container');
        const terminal = document.getElementById('terminal');
        const plotPane = document.getElementById('plot-pane');
        const filePane = document.getElementById('file-pane');
        const outputWrap = document.getElementById('output-wrap');
        const collapseBar = document.getElementById('collapse-bar');
        const collapseText = document.getElementById('collapse-text');
        const runBtn = document.getElementById('btn-run');
        const runText = document.getElementById('run-text');
        const statusDot = document.getElementById('status-dot');
        const statusText = document.getElementById('status-text');
        const cursorPos = document.getElementById('cursor-pos');
        const execTime = document.getElementById('exec-time');
        const toast = document.getElementById('toast');
        const modalOverlay = document.getElementById('modal-overlay');
        const modalBody = document.getElementById('modal-body');
        const uploadArea = document.getElementById('upload-area');
        const fileInput = document.getElementById('file-input');

        // ===== TELEGRAM WEBAPP =====
        const tg = window.Telegram.WebApp;
        tg.expand();
        tg.ready();
        tg.setHeaderColor('#0f0f1a');
        tg.setBackgroundColor('#0f0f1a');

        // ===== ACE EDITOR INIT =====
        function initEditor() {
            editor = ace.edit('editor-container');
            editor.setTheme('ace/theme/monokai');
            editor.session.setMode('ace/mode/python');
            editor.setValue('# Willkommen in der Queen\'s Code Sandbox!\n# Tippe deinen Python-Code hier ein...\n\nprint("Hallo Welt! 👑")', -1);
            editor.setOptions({
                fontSize: 14,
                fontFamily: "'JetBrains Mono', 'Fira Code', 'Courier New', monospace",
                showPrintMargin: false,
                showGutter: true,
                highlightActiveLine: true,
                highlightSelectedWord: true,
                wrap: true,
                tabSize: 4,
                useSoftTabs: true,
                enableBasicAutocompletion: true,
                enableLiveAutocompletion: true,
                enableSnippets: true,
                behavioursEnabled: true,
            });
            
            editor.selection.on('changeCursor', function() {
                const pos = editor.getCursorPosition();
                cursorPos.textContent = 'Ln ' + (pos.row + 1) + ', Col ' + (pos.column + 1);
            });
            
            editor.focus();
        }

        if (typeof ace !== 'undefined') {
            initEditor();
        } else {
            window.addEventListener('load', initEditor);
        }

        // ===== EVENT LISTENERS =====
        document.getElementById('btn-run').addEventListener('click', runCode);
        document.getElementById('btn-examples').addEventListener('click', showExamples);
        document.getElementById('btn-clear').addEventListener('click', clearCode);
        document.getElementById('btn-save').addEventListener('click', saveToBrain);
        document.getElementById('btn-share').addEventListener('click', shareToTelegram);
        collapseBar.addEventListener('click', toggleOutput);
        document.getElementById('modal-close').addEventListener('click', hideExamples);
        modalOverlay.addEventListener('click', function(e) {
            if (e.target === this) hideExamples();
        });
        document.getElementById('lang-select').addEventListener('change', changeLanguage);

        document.querySelectorAll('.btn-tpl').forEach(btn => {
            btn.addEventListener('click', function() {
                loadTemplate(this.dataset.tpl);
            });
        });

        document.querySelectorAll('.output-tab').forEach(tab => {
            tab.addEventListener('click', function() {
                switchPane(this.dataset.pane);
            });
        });

        // File Upload
        uploadArea.addEventListener('click', function() {
            fileInput.click();
        });
        uploadArea.addEventListener('touchend', function(e) {
            e.preventDefault();
            fileInput.click();
        });
        fileInput.addEventListener('change', handleFileUpload);

        // ===== TEMPLATES =====
        async function loadTemplates() {
            try {
                const res = await fetch('/sandbox/api/templates');
                const data = await res.json();
                templates = data.templates || {};
                renderExamples();
            } catch(e) {
                console.error('Template load error:', e);
                log('Templates konnten nicht geladen', 'error');
            }
        }

        function renderExamples() {
            modalBody.innerHTML = '';
            const examples = [
                { key: 'hello', title: '👋 Hallo Welt', desc: 'Grundlegendes Python-Beispiel', tag: 'Einstieg' },
                { key: 'plot', title: '📊 Matplotlib Plot', desc: 'Dämpfte Schwingung als Plot', tag: 'Visualisierung' },
                { key: 'dataframe', title: '📋 Pandas DataFrame', desc: 'Datenanalyse mit CSV-Export', tag: 'Daten' },
                { key: 'chart', title: '📈 Balken-Chart', desc: 'Farbiger Chart mit Werten', tag: 'Visualisierung' },
                { key: 'mini_app', title: '🎨 Mini-App', desc: 'HTML-Mini-App generieren', tag: 'Web App' },
            ];
            examples.forEach(ex => {
                const div = document.createElement('div');
                div.className = 'example-item';
                div.innerHTML = '<h3>' + ex.title + '</h3><p>' + ex.desc + '</p><span class="tag">' + ex.tag + '</span>';
                div.addEventListener('click', function() { loadTemplate(ex.key); hideExamples(); });
                modalBody.appendChild(div);
            });
        }

        function loadTemplate(key) {
            if (!editor || !templates[key]) { showToast('Template nicht gefunden'); return; }
            editor.setValue(templates[key], -1);
            editor.focus();
            showToast('Template "' + key + '" geladen');
        }

        // ===== CODE EXECUTION =====
        async function runCode() {
            if (isRunning || !editor) return;

            const code = editor.getValue();
            if (!code.trim()) {
                showToast('Kein Code zum Ausführen');
                return;
            }

            isRunning = true;
            runBtn.classList.add('running');
            runText.textContent = 'Läuft...';
            setStatus('busy', 'Code wird ausgeführt...');

            // Auto-expand output
            if (outputCollapsed) {
                toggleOutput();
            }
            switchPane('terminal');

            plotPane.innerHTML = '';
            filePane.innerHTML = '';

            const startTime = Date.now();

            try {
                const res = await fetch('/sandbox/api/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        code: code, 
                        language: document.getElementById('lang-select').value 
                    })
                });

                const data = await res.json();
                const elapsed = ((Date.now() - startTime) / 1000).toFixed(2);
                execTime.textContent = '⏱️ ' + elapsed + 's';

                if (data.success) {
                    log('✅ Erfolg (' + elapsed + 's)', 'success');
                    if (data.output) log(data.output, 'output');
                    if (data.result && data.result !== '✅ Code erfolgreich ausgeführt.') {
                        log('Result: ' + data.result, 'info');
                    }

                    if (data.plot) {
                        plotPane.innerHTML = '<img src="data:image/png;base64,' + data.plot + '" alt="Plot">';
                        switchPane('plot');
                    }

                    if (data.file) {
                        filePane.innerHTML = '<div class="file-card" id="dl-card"><div class="file-icon">📄</div><div class="file-info"><div class="file-name">' + escapeHtml(data.file.name) + '</div><div class="file-meta">Klicken zum Download</div></div></div>';
                        document.getElementById('dl-card').addEventListener('click', function() {
                            downloadFile(data.file.name, data.file.data);
                        });
                        if (!data.plot) switchPane('file');
                    }

                    tg.HapticFeedback.impactOccurred('light');
                } else {
                    log('❌ Fehler bei der Ausführung', 'error');
                    if (data.error) log(data.error, 'error');
                    setStatus('error', 'Fehler aufgetreten');
                    tg.HapticFeedback.impactOccurred('heavy');
                }
            } catch(e) {
                log('Netzwerkfehler: ' + e.message, 'error');
                setStatus('error', 'Netzwerkfehler');
                console.error('Run error:', e);
            } finally {
                isRunning = false;
                runBtn.classList.remove('running');
                runText.textContent = 'Ausführen';
                setStatus('ready', 'Bereit');
            }
        }

        // ===== OUTPUT TOGGLE =====
        function toggleOutput() {
            outputCollapsed = !outputCollapsed;
            outputWrap.classList.toggle('collapsed', outputCollapsed);
            if (outputCollapsed) {
                collapseText.textContent = 'Terminal anzeigen';
            } else {
                collapseText.textContent = 'Terminal minimieren';
            }
            if (editor) {
                setTimeout(function() { editor.resize(); }, 350);
            }
        }

        // ===== PANE SWITCHING =====
        function switchPane(paneName) {
            currentPane = paneName;
            document.querySelectorAll('.output-tab').forEach(t => {
                t.classList.toggle('active', t.dataset.pane === paneName);
            });
            document.querySelectorAll('.output-pane').forEach(p => {
                p.classList.toggle('active', p.id === paneName + '-pane' || (paneName === 'terminal' && p.id === 'terminal'));
            });
        }

        // ===== FILE UPLOAD =====
        async function handleFileUpload(e) {
            const file = e.target.files[0];
            if (!file) return;

            showToast('📤 Lade ' + file.name + '...');

            const formData = new FormData();
            formData.append('file', file);
            formData.append('chat_id', 'sandbox');

            try {
                const res = await fetch('/sandbox/api/upload', {
                    method: 'POST',
                    body: formData
                });

                const data = await res.json();
                if (data.success) {
                    if (data.code) {
                        editor.setValue(data.code, -1);
                        showToast('✅ ' + file.name + ' geladen');
                        switchPane('terminal');
                        log('📁 Datei geladen: ' + file.name, 'success');
                    } else {
                        showToast('✅ ' + file.name + ' hochgeladen');
                        log('📁 Datei hochgeladen: ' + file.name, 'success');
                    }
                } else {
                    showToast('❌ Upload fehlgeschlagen');
                    log('Upload fehlgeschlagen: ' + (data.error || 'Unbekannter Fehler'), 'error');
                }
            } catch(err) {
                showToast('❌ Netzwerkfehler beim Upload');
                log('Upload-Fehler: ' + err.message, 'error');
            }

            fileInput.value = '';
        }

        // ===== TERMINAL LOGGING =====
        function log(message, type) {
            const line = document.createElement('div');
            line.className = 'term-line';
            const time = new Date().toLocaleTimeString('de-DE', { hour12: false });
            let content = '<span class="term-time">[' + time + ']</span> ';
            const safe = escapeHtml(String(message));
            
            if (type === 'error') content += '<span class="term-error">' + safe + '</span>';
            else if (type === 'success') content += '<span class="term-success">' + safe + '</span>';
            else if (type === 'warn') content += '<span class="term-warn">' + safe + '</span>';
            else if (type === 'info') content += '<span class="term-info">' + safe + '</span>';
            else content += '<span class="term-output">' + safe + '</span>';

            line.innerHTML = content;
            terminal.appendChild(line);
            terminal.scrollTop = terminal.scrollHeight;
        }

        // ===== UI ACTIONS =====
        function showExamples() {
            modalOverlay.classList.add('show');
        }
        function hideExamples() {
            modalOverlay.classList.remove('show');
        }
        function clearCode() {
            if (!editor) return;
            editor.setValue('', -1);
            showToast('Editor geleert');
        }
        function changeLanguage() {
            if (!editor) return;
            const lang = document.getElementById('lang-select').value;
            editor.session.setMode(lang === 'python' ? 'ace/mode/python' : 'ace/mode/html');
            showToast('Sprache: ' + lang);
        }
        function saveToBrain() {
            if (!editor) return;
            showToast('💾 Wird gespeichert...');
            fetch('/sandbox/api/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: editor.getValue(), name: 'sandbox_code' })
            }).then(r => r.json()).then(d => {
                showToast(d.message || 'Gespeichert!');
            }).catch(e => {
                showToast('Speichern fehlgeschlagen');
            });
        }
        function shareToTelegram() {
            if (!editor) return;
            tg.sendData(JSON.stringify({ action: 'share_code', code: editor.getValue() }));
            showToast('📤 Code geteilt');
        }
        function showToast(msg) {
            toast.textContent = msg;
            toast.classList.add('show');
            setTimeout(function() { toast.classList.remove('show'); }, 2500);
        }
        function setStatus(state, text) {
            statusDot.className = 'status-dot ' + state;
            statusText.textContent = text;
        }

        // ===== UTILS =====
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        function downloadFile(name, data) {
            const a = document.createElement('a');
            a.href = 'data:application/octet-stream;base64,' + data;
            a.download = name;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            showToast('📥 ' + name + ' heruntergeladen');
        }

        // ===== INIT =====
        loadTemplates();
        log('👑 Sandbox bereit', 'success');
        log('Tippe auf ▶️ Ausführen', 'info');
    </script>
</body>
</html>"""


# ── API Endpoints ──────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def sandbox_home():
    return HTMLResponse(SANDBOX_HTML)


@app.get("/api/templates")
async def get_templates():
    return {"templates": get_example_templates()}


@app.post("/api/run")
async def run_code_endpoint(request: Request):
    try:
        data = await request.json()
        code = data.get("code", "").strip()
        language = data.get("language", "python")
        chat_id = data.get("chat_id")

        if not code:
            return JSONResponse({"success": False, "error": "Kein Code angegeben"}, status_code=400)

        if language == "html":
            buffer, filename = generate_html_app(code, "Sandbox App")
            import base64
            return {
                "success": True,
                "output": "✅ HTML Mini-App generiert",
                "file": {
                    "name": filename,
                    "data": base64.b64encode(buffer.getvalue()).decode("utf-8"),
                },
                "plot": None,
                "error": None,
                "execution_time": 0.1,
            }

        result = await run_sandboxed_code(code, chat_id=chat_id)

        plot_b64 = None
        if result.get("plot"):
            import base64
            plot_b64 = base64.b64encode(result["plot"].getvalue()).decode("utf-8")

        file_data = None
        if result.get("file"):
            import base64
            buf, fname = result["file"]
            file_data = {
                "name": fname,
                "data": base64.b64encode(buf.getvalue()).decode("utf-8"),
            }

        return {
            "success": result["success"],
            "output": result["output"],
            "error": result["error"],
            "plot": plot_b64,
            "file": file_data,
            "result": str(result["result"]) if result["result"] is not None else None,
            "execution_time": result["execution_time"],
        }

    except Exception as e:
        logger.exception("Sandbox API Fehler")
        return JSONResponse(
            {"success": False, "error": f"Server-Fehler: {str(e)}"},
            status_code=500,
        )


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...), chat_id: str = Form("sandbox")):
    """Datei-Upload Endpoint – lädt Datei ins Editor oder Brain"""
    try:
        content = await file.read()
        
        # Wenn es eine Textdatei ist, gib den Code zurück
        text_extensions = ['.py', '.txt', '.csv', '.json', '.html', '.js', '.css', '.md']
        file_ext = os.path.splitext(file.filename)[1].lower()
        
        if file_ext in text_extensions:
            try:
                code = content.decode('utf-8')
                return {
                    "success": True,
                    "code": code,
                    "filename": file.filename,
                    "message": f"✅ {file.filename} geladen"
                }
            except UnicodeDecodeError:
                pass
        
        # Sonst speichere als Binärdatei
        import base64
        encoded = base64.b64encode(content).decode('utf-8')
        return {
            "success": True,
            "filename": file.filename,
            "data": encoded,
            "message": f"✅ {file.filename} hochgeladen"
        }
        
    except Exception as e:
        logger.exception("Upload Fehler")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


@app.post("/api/save")
async def save_code_endpoint(request: Request):
    try:
        data = await request.json()
        code = data.get("code", "")
        name = data.get("name", "sandbox_code")
        chat_id = data.get("chat_id")

        if not chat_id:
            return {"success": False, "message": "Keine chat_id angegeben"}

        from brain import save_text
        result = await save_text(chat_id, code, title=f"Sandbox: {name}")

        return {"success": "ID:" in result, "message": result}

    except Exception as e:
        logger.exception("Brain-Save Fehler")
        return {"success": False, "message": f"Fehler: {str(e)}"}


@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "sandbox": "ready",
        "version": "6.0.0-android",
        "features": ["python", "html", "matplotlib", "pandas", "numpy", "file-upload"],
    }


with open('/mnt/agents/output/sandbox_mini_app_v6.py', 'w', encoding='utf-8') as f:
    f.write(v6_code)

print("✅ sandbox_mini_app_v6.py erstellt!")
print(f"Länge: {len(v6_code)} Zeichen")
