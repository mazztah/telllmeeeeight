/* ======================================================
   Queen's Code Sandbox – JavaScript V8
   DYNAMISCHES 3-BEREICH-LAYOUT + HTML-PREVIEW + PARSER
   + PERMISSIONS + COPY + DRAG&DROP + BRAIN-INTEGRATION
   ====================================================== */

// ── STATE ────────────────────────────────────────────────
let editor = null;
let templates = {};
let isRunning = false;
let outputCollapsed = false;
let chatOpen = false;
let currentPane = 'terminal';
let chatHistory = [];
let isChatLoading = false;
let sectionSizes = { editor: 1, output: 1, chat: 0.8 }; // relative flex weights
let mobilePanelIndex = 0; // 0=editor, 1=terminal, 2=chat (nur Mobile)
let isMobile = false;

// ── TELEGRAM WEBAPP ──────────────────────────────────────
const tg = (window.Telegram && window.Telegram.WebApp) ? window.Telegram.WebApp : null;
if (tg) {
    tg.expand();
    tg.ready();
    try { tg.setHeaderColor('#0f0f1a'); } catch(e) {}
    try { tg.setBackgroundColor('#0f0f1a'); } catch(e) {}
}
function haptic(type) {
    try { if (tg) tg.HapticFeedback.impactOccurred(type || 'light'); } catch(e) {}
}

// ── BUILTIN TEMPLATES ────────────────────────────────────
const BUILTIN_TEMPLATES = {
    "hello": `# Hallo Welt
print("Hallo aus der Sandbox! 🚀")
print("Mathe:", 2 + 2)
print("NP Array:", [1, 2, 3] * 2)`,

    "plot": `import numpy as np
import matplotlib.pyplot as plt

x = np.linspace(0, 10, 100)
y = np.sin(x) * np.exp(-x/3)

plt.figure(figsize=(10, 5))
plt.plot(x, y, color='#a78bfa', linewidth=2)
plt.fill_between(x, y, alpha=0.3, color='#a78bfa')
plt.title('Dämpfte Schwingung', color='white', fontsize=14)
plt.xlabel('Zeit', color='#7a8099')
plt.ylabel('Amplitude', color='#7a8099')
plt.grid(True, alpha=0.2)
plt.tight_layout()
print("Plot erstellt! 📊")`,

    "dataframe": `import pandas as pd
import numpy as np

df = pd.DataFrame({
    "Name": ["Alice", "Bob", "Charlie", "Diana"],
    "Alter": [25, 30, 35, 28],
    "Stadt": ["Berlin", "München", "Hamburg", "Köln"],
    "Score": np.random.randint(60, 100, 4)
})

print(df.to_string())
print(f"\nDurchschnittsalter: {df['Alter'].mean():.1f}")
print(f"Durchschnittsscore: {df['Score'].mean():.1f}")

# Als Datei exportieren
result_file = (df.to_csv(index=False).encode('utf-8'), "daten.csv")`,

    "chart": `import numpy as np
import matplotlib.pyplot as plt

categories = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun"]
values = np.random.randint(20, 100, 6)
colors = ['#a78bfa', '#00d4aa', '#f5c242', '#ff3366', '#3b82f6', '#22c55e']

fig, ax = plt.subplots(figsize=(10, 6))
bars = ax.bar(categories, values, color=colors, edgecolor='white', linewidth=1.5)

for bar, val in zip(bars, values):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 2,
            str(val), ha='center', va='bottom', color='white', fontweight='bold')

ax.set_title('Monatliche Performance', color='white', fontsize=16, fontweight='bold')
ax.set_ylabel('Wert', color='#7a8099')
ax.set_facecolor('#1a1a2e')
fig.patch.set_facecolor('#0f0f1a')
ax.tick_params(colors='#7a8099')
ax.spines['bottom'].set_color('#2a2f3f')
ax.spines['left'].set_color('#2a2f3f')
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)

plt.tight_layout()
print("Chart erstellt! 📊")`,

    "mini_app": `html = """
<div style="text-align:center; padding:40px 20px; font-family:sans-serif;">
    <h1 style="color:#a78bfa; font-size:2rem; margin-bottom:20px;">🚀 Meine Mini-App</h1>
    <p style="color:#7a8099; margin-bottom:30px;">Erstellt mit der Sandbox</p>
    <button onclick="alert('Hallo!')"
            style="background:linear-gradient(135deg,#a78bfa,#00d4aa); color:#0f0f1a;
                   border:none; padding:14px 28px; border-radius:12px; font-size:1rem;
                   font-weight:700; cursor:pointer;">
        Klick mich!
    </button>
    <div id="cnt" style="margin-top:30px; font-size:3rem; color:#f5c242; font-weight:700;">0</div>
    <button onclick="document.getElementById('cnt').innerText++" 
            style="background:#1a1a2e; color:#00d4aa; border:2px solid #00d4aa;
                   padding:10px 20px; border-radius:8px; margin-top:10px; cursor:pointer;">+1</button>
</div>
"""

print(html)
# Mini-App als Datei exportieren
result_file = (html.encode('utf-8'), "mini_app.html")
print("Mini-App erstellt! 🎨")`
};

// ── DOM REFS ─────────────────────────────────────────────
const editorSection = document.getElementById('editor-section');
const outputSection = document.getElementById('output-section');
const chatSection   = document.getElementById('chat-section');
const terminal      = document.getElementById('terminal');
const plotPane      = document.getElementById('plot-pane');
const filePane      = document.getElementById('file-pane');
const htmlPreviewPane = document.getElementById('html-preview-pane');
const parserPane    = document.getElementById('parser-pane');
const runBtn        = document.getElementById('btn-run');
const runText       = document.getElementById('run-text');
const statusDot     = document.getElementById('status-dot');
const statusText    = document.getElementById('status-text');
const cursorPos     = document.getElementById('cursor-pos');
const execTime      = document.getElementById('exec-time');
const toastEl       = document.getElementById('toast');
const modalOverlay  = document.getElementById('modal-overlay');
const modalBody     = document.getElementById('modal-body');
const uploadArea    = document.getElementById('upload-area');
const fileInput     = document.getElementById('file-input');
const chatMessages  = document.getElementById('chat-messages');
const chatInput     = document.getElementById('chat-input');
const chatSend      = document.getElementById('chat-send');

// ── ACE EDITOR ───────────────────────────────────────────
function initEditor() {
    editor = ace.edit('editor-container');
    editor.setTheme('ace/theme/monokai');
    editor.session.setMode('ace/mode/python');
    editor.setValue('# Willkommen in der Queen\'s Code Sandbox! 👑\n# Tippe deinen Python-Code hier ein...\n\nprint("Hallo Welt! 🚀")', -1);
    editor.setOptions({
        fontSize: '13px',
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
        scrollPastEnd: 0.3,
    });
    editor.renderer.setScrollMargin(0, 0);
    editor.setShowScrollbars && editor.setShowScrollbars(true);

    editor.selection.on('changeCursor', function() {
        const pos = editor.getCursorPosition();
        cursorPos.textContent = 'Ln ' + (pos.row + 1) + ', Col ' + (pos.column + 1);
    });

    // Change-Listener für Live-HTML-Preview
    editor.session.on('change', function() {
        if (currentPane === 'html-preview') {
            debouncedHtmlPreview();
        }
    });

    editor.commands.addCommand({
        name: 'runCode',
        bindKey: { win: 'Ctrl-Enter', mac: 'Cmd-Enter' },
        exec: runCode
    });
    editor.commands.addCommand({
        name: 'saveCode',
        bindKey: { win: 'Ctrl-S', mac: 'Cmd-S' },
        exec: saveToBrain
    });

    editor.focus();
}

if (typeof ace !== 'undefined') {
    initEditor();
} else {
    window.addEventListener('load', initEditor);
}

// ── EVENT LISTENERS ──────────────────────────────────────
runBtn.addEventListener('click', runCode);
document.getElementById('btn-examples').addEventListener('click', showExamples);
document.getElementById('btn-clear').addEventListener('click', clearCode);
document.getElementById('btn-save').addEventListener('click', saveToBrain);
document.getElementById('btn-share').addEventListener('click', shareToTelegram);
document.getElementById('btn-copy').addEventListener('click', copyCode);
document.getElementById('btn-equalize').addEventListener('click', equalizeSections);
document.getElementById('btn-download').addEventListener('click', downloadCode);
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
    tab.addEventListener('click', function(e) {
        e.stopPropagation();
        switchPane(this.dataset.pane);
    });
});

uploadArea.addEventListener('click', function(e) {
    e.preventDefault();
    fileInput.click();
});
fileInput.addEventListener('change', handleFileUpload);

// Drag & Drop
document.addEventListener('dragover', function(e) {
    e.preventDefault();
    if (e.target.closest('.upload-area')) {
        e.target.closest('.upload-area').classList.add('dragover');
    }
});
document.addEventListener('dragleave', function(e) {
    if (e.target.closest('.upload-area')) {
        e.target.closest('.upload-area').classList.remove('dragover');
    }
});
document.addEventListener('drop', function(e) {
    e.preventDefault();
    const area = e.target.closest('.upload-area');
    if (area) {
        area.classList.remove('dragover');
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFileUpload({ target: { files: files } });
        }
    }
});

// Chat Toggle
document.getElementById('chat-toggle').addEventListener('click', function() {
    chatOpen = !chatOpen;
    chatSection.classList.toggle('collapsed', !chatOpen);
    document.getElementById('chat-toggle-arrow').textContent = chatOpen ? '▼' : '▲';
    if (chatOpen) {
        setTimeout(function() { chatInput.focus(); }, 300);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }
    if (editor) setTimeout(function() { editor.resize(); }, 350);
    haptic('light');
});

// Output Collapse
document.getElementById('collapse-bar').addEventListener('click', function(e) {
    if (!e.target.closest('.output-tab') && !e.target.closest('#output-tabs')) {
        toggleOutput();
    }
});

// HTML Preview Buttons
document.getElementById('btn-refresh-html').addEventListener('click', function() {
    updateHtmlPreview();
    showToast('🌐 HTML-Preview aktualisiert');
});
document.getElementById('btn-open-html').addEventListener('click', function() {
    const code = editor ? editor.getValue() : '';
    const win = window.open('', '_blank');
    win.document.write(code);
    win.document.close();
});

// Parser Button
document.getElementById('btn-refresh-parser').addEventListener('click', function() {
    parseCode();
    showToast('🔍 Code analysiert');
});

// Permissions Button
document.getElementById('btn-request-perms').addEventListener('click', checkPermissions);

// Chat Input
chatInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendChatMessage();
    }
});
chatInput.addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 90) + 'px';
});
chatSend.addEventListener('click', sendChatMessage);

// ── DYNAMIC 3-PANE RESIZE ───────────────────────────────
(function initResizers() {
    function setupResize(handleId, sectionAId, sectionBId) {
        const handle = document.getElementById(handleId);
        const sectionA = document.getElementById(sectionAId);
        const sectionB = document.getElementById(sectionBId);
        if (!handle || !sectionA || !sectionB) return;

        let dragging = false;
        let startY = 0;
        let startFlexA = 0;
        let startFlexB = 0;
        let totalFlex = 0;

        function onStart(e) {
            if (sectionA.classList.contains('collapsed') || sectionB.classList.contains('collapsed')) {
                return; // Don't resize if one is collapsed
            }
            dragging = true;
            startY = e.touches ? e.touches[0].clientY : e.clientY;
            const aFlex = parseFloat(getComputedStyle(sectionA).flexGrow) || 1;
            const bFlex = parseFloat(getComputedStyle(sectionB).flexGrow) || 1;
            startFlexA = aFlex;
            startFlexB = bFlex;
            totalFlex = aFlex + bFlex;
            handle.classList.add('dragging');
            document.body.style.cursor = 'ns-resize';
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onEnd);
            document.addEventListener('touchmove', onMove, { passive: false });
            document.addEventListener('touchend', onEnd);
            e.preventDefault();
        }

        function onMove(e) {
            if (!dragging) return;
            const y = e.touches ? e.touches[0].clientY : e.clientY;
            const delta = y - startY;
            const workspace = document.getElementById('workspace');
            const totalHeight = workspace.offsetHeight;
            const deltaFlex = (delta / totalHeight) * 3; // scale factor

            let newA = Math.max(0.2, startFlexA + deltaFlex);
            let newB = Math.max(0.2, startFlexB - deltaFlex);
            const ratio = totalFlex / (newA + newB);
            newA *= ratio;
            newB *= ratio;

            sectionA.style.flex = newA + ' 1 0';
            sectionB.style.flex = newB + ' 1 0';
            if (editor) editor.resize();
            e.preventDefault();
        }

        function onEnd() {
            dragging = false;
            handle.classList.remove('dragging');
            document.body.style.cursor = '';
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onEnd);
            document.removeEventListener('touchmove', onMove);
            document.removeEventListener('touchend', onEnd);
        }

        handle.addEventListener('mousedown', onStart);
        handle.addEventListener('touchstart', onStart, { passive: false });
    }

    setupResize('resize-handle-1', 'editor-section', 'output-section');
    setupResize('resize-handle-2', 'output-section', 'chat-section');
})();

// ── EQUALIZE SECTIONS ───────────────────────────────────
function equalizeSections() {
    const sections = ['editor-section', 'output-section', 'chat-section'];
    const visible = sections.filter(id => !document.getElementById(id).classList.contains('collapsed'));
    const flex = visible.length > 0 ? (3 / visible.length) : 1;
    sections.forEach(id => {
        const el = document.getElementById(id);
        if (!el.classList.contains('collapsed')) {
            el.style.flex = flex + ' 1 0';
        }
    });
    if (editor) editor.resize();
    showToast('⚖️ Bereiche ausgeglichen');
    haptic('light');
}

// ── TEMPLATES ────────────────────────────────────────────
async function loadTemplates() {
    templates = Object.assign({}, BUILTIN_TEMPLATES);
    try {
        const res = await fetch('/sandbox/api/templates');
        if (res.ok) {
            const data = await res.json();
            if (data.templates && Object.keys(data.templates).length > 0) {
                templates = data.templates;
            }
        }
    } catch(e) {}
    renderExamples();
}

function renderExamples() {
    if (!modalBody) return;
    modalBody.innerHTML = '';
    const examples = [
        { key: 'hello',     title: '👋 Hallo Welt',       desc: 'Grundlegendes Python-Beispiel',   tag: 'Einstieg' },
        { key: 'plot',      title: '📊 Matplotlib Plot',   desc: 'Dämpfte Schwingung als Plot',      tag: 'Visualisierung' },
        { key: 'dataframe', title: '📋 Pandas DataFrame',  desc: 'Datenanalyse mit CSV-Export',      tag: 'Daten' },
        { key: 'chart',     title: '📈 Balken-Chart',      desc: 'Farbiger Chart mit Labels',        tag: 'Visualisierung' },
        { key: 'mini_app',  title: '🎨 Mini-App',          desc: 'HTML-Mini-App generieren',         tag: 'Web App' },
    ];
    examples.forEach(ex => {
        const div = document.createElement('div');
        div.className = 'example-item';
        div.innerHTML = `<h3>${ex.title}</h3><p>${ex.desc}</p><span class="tag">${ex.tag}</span>`;
        div.addEventListener('click', function() { loadTemplate(ex.key); hideExamples(); });
        modalBody.appendChild(div);
    });
}

function loadTemplate(key) {
    if (!editor) { showToast('Editor nicht bereit'); return; }
    const code = templates[key] || BUILTIN_TEMPLATES[key];
    if (!code) { showToast('Template nicht gefunden'); return; }
    editor.setValue(code, -1);
    editor.focus();
    showToast('✅ Template geladen');
    haptic('light');
    // Auto-parse after load
    setTimeout(parseCode, 100);
}

// ── CODE EXECUTION ───────────────────────────────────────
async function runCode() {
    if (isRunning || !editor) return;

    const code = editor.getValue();
    if (!code.trim()) { showToast('Kein Code zum Ausführen'); return; }

    isRunning = true;
    runBtn.classList.add('running');
    runText.textContent = 'Läuft...';
    setStatus('busy', 'Wird ausgeführt...');
    haptic('light');

    if (outputCollapsed) toggleOutput();
    switchPane('terminal');
    plotPane.innerHTML = '';
    resetFilePane();

    const startTime = Date.now();

    try {
        const res = await fetch('/sandbox/api/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                code: code,
                language: document.getElementById('lang-select').value,
                chat_id: tg ? tg.initDataUnsafe?.user?.id?.toString() : 'sandbox'
            })
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);

        const data = await res.json();
        const elapsed = ((Date.now() - startTime) / 1000).toFixed(2);
        execTime.textContent = '⏱️ ' + elapsed + 's';

        if (data.success) {
            log('✅ Erfolg (' + elapsed + 's)', 'success');
            if (data.output) log(data.output, 'output');
            if (data.result && data.result !== '✅ Code erfolgreich ausgeführt.') {
                log('▶ ' + data.result, 'info');
            }

            if (data.plot) {
                plotPane.innerHTML = `<img src="data:image/png;base64,${data.plot}" alt="Plot" style="max-width:100%;border-radius:8px;">`;
                switchPane('plot');
            }

            if (data.file) {
                filePane.innerHTML = `
                    <div class="file-card" id="dl-card">
                        <div class="file-icon">📄</div>
                        <div>
                            <div class="file-name">${escapeHtml(data.file.name)}</div>
                            <div class="file-meta">Tippen zum Herunterladen • ${formatBytes(data.file.data.length * 0.75)}</div>
                        </div>
                    </div>`;
                document.getElementById('dl-card').addEventListener('click', function() {
                    downloadFile(data.file.name, data.file.data);
                    haptic('light');
                });
                if (!data.plot) switchPane('file');
            }

            // Auto-update parser
            parseCode();
            haptic('light');
            setStatus('ready', 'Bereit');
        } else {
            log('❌ Fehler bei der Ausführung', 'error');
            if (data.error) log(data.error, 'error');
            setStatus('error', 'Fehler aufgetreten');
            haptic('heavy');
        }
    } catch(e) {
        log('🔌 Netzwerkfehler: ' + e.message, 'error');
        setStatus('error', 'Netzwerkfehler');
        haptic('heavy');
    } finally {
        isRunning = false;
        runBtn.classList.remove('running');
        runText.textContent = 'Run';
        if (statusText.textContent === 'Wird ausgeführt...') setStatus('ready', 'Bereit');
    }
}

function resetFilePane() {
    filePane.innerHTML = `
        <div class="upload-area" id="upload-area">
            <input type="file" id="file-input" accept=".py,.txt,.csv,.json,.html,.js,.css,.md" style="display:none">
            <div class="upload-icon">📁</div>
            <div class="upload-title">Datei hochladen</div>
            <div class="upload-sub">Tippen zum Auswählen – oder per Drag & Drop</div>
        </div>
        <div id="upload-permissions">
            <div class="perm-title">🔐 Berechtigungen</div>
            <div id="perm-list">
                <div class="perm-item" data-perm="file">
                    <span class="perm-icon">📄</span>
                    <span class="perm-label">Dateizugriff</span>
                    <span class="perm-status" id="perm-file">⏳</span>
                </div>
                <div class="perm-item" data-perm="clipboard">
                    <span class="perm-icon">📋</span>
                    <span class="perm-label">Zwischenablage</span>
                    <span class="perm-status" id="perm-clipboard">⏳</span>
                </div>
                <div class="perm-item" data-perm="notifications">
                    <span class="perm-icon">🔔</span>
                    <span class="perm-label">Benachrichtigungen</span>
                    <span class="perm-status" id="perm-notifications">⏳</span>
                </div>
            </div>
            <button class="btn btn-secondary btn-sm" id="btn-request-perms" style="margin-top:8px; width:100%;">🔐 Berechtigungen prüfen & anfordern</button>
        </div>`;
    document.getElementById('upload-area').addEventListener('click', function(e) {
        e.preventDefault();
        document.getElementById('file-input').click();
    });
    document.getElementById('file-input').addEventListener('change', handleFileUpload);
    document.getElementById('btn-request-perms').addEventListener('click', checkPermissions);
}

// ── OUTPUT TOGGLE ────────────────────────────────────────
function toggleOutput() {
    outputCollapsed = !outputCollapsed;
    outputSection.classList.toggle('collapsed', outputCollapsed);
    collapseText.textContent = outputCollapsed ? 'Output' : 'Output';
    if (editor) setTimeout(function() { editor.resize(); }, 350);
}

// ── PANE SWITCHING ───────────────────────────────────────
function switchPane(paneName) {
    currentPane = paneName;
    document.querySelectorAll('.output-tab').forEach(t => {
        t.classList.toggle('active', t.dataset.pane === paneName);
    });
    document.querySelectorAll('.output-pane').forEach(p => {
        p.classList.toggle('active', p.id === paneName + '-pane');
    });

    if (paneName === 'html-preview') {
        updateHtmlPreview();
    } else if (paneName === 'parser') {
        parseCode();
    }
}

// ── HTML PREVIEW ─────────────────────────────────────────
let htmlPreviewTimeout = null;
function debouncedHtmlPreview() {
    clearTimeout(htmlPreviewTimeout);
    htmlPreviewTimeout = setTimeout(updateHtmlPreview, 500);
}

function updateHtmlPreview() {
    const frame = document.getElementById('html-preview-frame');
    const status = document.getElementById('html-preview-status');
    if (!frame || !editor) return;

    const code = editor.getValue();
    const lang = document.getElementById('lang-select').value;

    if (lang !== 'html') {
        frame.srcdoc = `<div style="padding:20px; color:#7a8099; font-family:sans-serif; text-align:center;">
            <div style="font-size:2rem; margin-bottom:10px;">🌐</div>
            <div>Wechsle zu <b>HTML</b> im Dropdown oben, um die Live-Vorschau zu sehen.</div>
            <div style="margin-top:10px; font-size:0.8rem;">Aktuell: ${lang.toUpperCase()}</div>
        </div>`;
        status.textContent = 'N/A – Wechsle zu HTML';
        return;
    }

    // Wrap in sandbox with base styles
    const sandboxHtml = `
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
    body { margin:0; padding:10px; font-family:system-ui,sans-serif; background:#fff; color:#333; }
    * { box-sizing:border-box; }
</style>
</head>
<body>
${code}
</body>
</html>`;

    frame.srcdoc = sandboxHtml;
    status.textContent = 'Aktualisiert';
}

// ── CODE PARSER (Python + HTML) ──────────────────────────
async function parseCode() {
    const content = document.getElementById('parser-content');
    const status = document.getElementById('parser-status');
    if (!content || !editor) return;

    const code = editor.getValue();
    const lang = document.getElementById('lang-select').value;

    status.textContent = 'Analysiere...';

    try {
        // Nutze Server-Parser fuer bessere Ergebnisse
        const res = await fetch('/sandbox/api/parse', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code: code, language: lang })
        });
        const data = await res.json();

        if (data.error) {
            content.innerHTML = `<div style="color:var(--muted); text-align:center; padding:20px;">
                <div style="font-size:2rem; margin-bottom:10px;">⚠️</div>
                <div>${escapeHtml(data.error)}</div>
            </div>`;
            status.textContent = 'Fehler';
            return;
        }

        if (!data.elements || data.elements.length === 0) {
            content.innerHTML = `<div style="color:var(--muted); text-align:center; padding:20px;">
                <div style="font-size:2rem; margin-bottom:10px;">🔍</div>
                <div>Keine Struktur erkannt. Schreibe ${lang.toUpperCase()}-Code...</div>
            </div>`;
            status.textContent = 'Keine Elemente';
            return;
        }

        // Render tree
        let html = '<ul class="parser-tree">';
        data.elements.forEach(function(node) {
            html += renderParserNodeServer(node);
        });
        html += '</ul>';

        // Stats anzeigen
        const stats = data.stats || {};
        const statParts = [];
        if (stats.imports !== undefined) statParts.push(`${stats.imports} Imports`);
        if (stats.classes !== undefined) statParts.push(`${stats.classes} Klassen`);
        if (stats.functions !== undefined) statParts.push(`${stats.functions} Funktionen`);
        if (stats.variables !== undefined) statParts.push(`${stats.variables} Variablen`);
        if (stats.tags !== undefined) statParts.push(`${stats.tags} Tags`);
        if (stats.unique_tags !== undefined) statParts.push(`${stats.unique_tags} Unique`);

        content.innerHTML = html;
        status.textContent = data.elements.length + ' Elemente • ' + statParts.join(' | ');

    } catch (e) {
        // Fallback: clientseitiger Parser
        status.textContent = 'Fallback-Parser';
        clientSideParse(code, lang, content, status);
    }
}

function renderParserNodeServer(node) {
    let detail = node.detail ? `<span class="detail">${escapeHtml(node.detail)}</span>` : '';
    let children = '';
    if (node.children && node.children.length > 0) {
        children = '<ul>' + node.children.map(function(c) { return renderParserNodeServer(c); }).join('') + '</ul>';
    }
    var typeClass = node.type;
    var typeLabel = node.type;
    if (node.type === 'tag') typeLabel = 'html';
    if (node.type === 'loop') typeLabel = 'loop';

    return `<li>
        <div class="parser-node ${typeClass}">
            <span class="type">${typeLabel}</span>
            <span class="name">${escapeHtml(node.name)}</span>
            ${detail}
            <span style="color:var(--muted); font-size:0.7rem; margin-left:auto;">:${node.line}</span>
        </div>
        ${children}
    </li>`;
}

function clientSideParse(code, lang, content, status) {
    if (lang === 'html') {
        // Einfacher HTML-Tag-Parser
        const tagPattern = /<([a-zA-Z][a-zA-Z0-9]*)[^>]*?>/g;
        const tree = [];
        let match;
        while ((match = tagPattern.exec(code)) !== null) {
            const line = code.substring(0, match.index).split('\n').length;
            tree.push({ type: 'tag', name: match[1], line: line });
        }
        if (tree.length === 0) {
            content.innerHTML = '<div style="color:var(--muted); text-align:center; padding:20px;">Keine HTML-Tags erkannt.</div>';
            return;
        }
        let html = '<ul class="parser-tree">';
        tree.slice(0, 50).forEach(function(n) { html += renderParserNodeServer(n); });
        html += '</ul>';
        content.innerHTML = html;
        status.textContent = tree.length + ' HTML-Tags';
        return;
    }

    // Fallback Python Parser
    const lines = code.split('\n');
    const tree = [];
    lines.forEach(function(line, idx) {
        var stripped = line.trim();
        if (!stripped) return;

        var importMatch = stripped.match(/^(?:from\s+(\S+)\s+import|import\s+(\S+))/);
        if (importMatch) {
            tree.push({ type: 'import', name: importMatch[1] || importMatch[2], line: idx + 1 });
            return;
        }
        var classMatch = stripped.match(/^class\s+(\w+)/);
        if (classMatch) {
            tree.push({ type: 'class', name: classMatch[1], line: idx + 1, detail: '', children: [] });
            return;
        }
        var funcMatch = stripped.match(/^def\s+(\w+)\s*\(([^)]*)\)/);
        if (funcMatch) {
            tree.push({ type: 'function', name: funcMatch[1], line: idx + 1, detail: funcMatch[2] || '' });
            return;
        }
    });

    var html = '<ul class="parser-tree">';
    tree.forEach(function(n) { html += renderParserNodeServer(n); });
    html += '</ul>';
    if (tree.length === 0) {
        html = '<div style="color:var(--muted); text-align:center; padding:20px;">Keine Struktur erkannt.</div>';
    }
    content.innerHTML = html;
    status.textContent = tree.length + ' Elemente (Fallback)';
}

// ── PERMISSIONS ──────────────────────────────────────────
async function checkPermissions() {
    const perms = [
        { name: 'file', api: null }, // File access is implicit via input
        { name: 'clipboard-read', dom: 'clipboard' },
        { name: 'notifications', dom: 'notifications' }
    ];

    for (const perm of perms) {
        const el = document.getElementById('perm-' + (perm.dom || perm.name));
        if (!el) continue;

        if (!navigator.permissions || !perm.api) {
            // Fallback for file or unsupported APIs
            if (perm.name === 'file') {
                el.textContent = '✅';
                el.className = 'perm-status granted';
            } else {
                el.textContent = '❓';
                el.className = 'perm-status unknown';
            }
            continue;
        }

        try {
            const result = await navigator.permissions.query({ name: perm.api });
            if (result.state === 'granted') {
                el.textContent = '✅';
                el.className = 'perm-status granted';
            } else if (result.state === 'denied') {
                el.textContent = '❌';
                el.className = 'perm-status denied';
            } else {
                el.textContent = '⏳';
                el.className = 'perm-status unknown';
            }
        } catch(e) {
            el.textContent = '❓';
            el.className = 'perm-status unknown';
        }
    }

    // Try to request clipboard permission explicitly
    try {
        if (navigator.clipboard && navigator.clipboard.readText) {
            await navigator.clipboard.readText();
            const el = document.getElementById('perm-clipboard');
            if (el) { el.textContent = '✅'; el.className = 'perm-status granted'; }
        }
    } catch(e) {}

    showToast('🔐 Berechtigungen geprüft');
}

// ── FILE UPLOAD ──────────────────────────────────────────
async function handleFileUpload(e) {
    const file = e.target.files[0];
    if (!file) return;

    showToast('📤 Lade ' + file.name + '...');
    const formData = new FormData();
    formData.append('file', file);
    formData.append('chat_id', tg ? tg.initDataUnsafe?.user?.id?.toString() : 'sandbox');

    try {
        const res = await fetch('/sandbox/api/upload', { method: 'POST', body: formData });
        const data = await res.json();
        if (data.success) {
            if (data.code) {
                editor.setValue(data.code, -1);
                showToast('✅ ' + file.name + ' geladen');
                switchPane('terminal');
                log('📁 Datei geladen: ' + file.name, 'success');
                parseCode();
            } else {
                showToast('✅ ' + file.name + ' hochgeladen');
                log('📁 Hochgeladen: ' + file.name, 'success');
            }
        } else {
            showToast('❌ Upload fehlgeschlagen');
            log('Upload: ' + (data.error || 'Fehler'), 'error');
        }
    } catch(err) {
        showToast('❌ Netzwerkfehler');
        log('Upload-Fehler: ' + err.message, 'error');
    }
    e.target.value = '';
}

// ── TERMINAL LOG ─────────────────────────────────────────
function log(message, type) {
    const line = document.createElement('div');
    line.className = 'term-line';
    const time = new Date().toLocaleTimeString('de-DE', { hour12: false });
    let content = `<span class="term-time">[${time}]</span> `;
    const safe = escapeHtml(String(message));
    const cls = type === 'error' ? 'term-error' : type === 'success' ? 'term-success' :
                type === 'warn' ? 'term-warn' : type === 'info' ? 'term-info' : 'term-output';
    content += `<span class="${cls}">${safe}</span>`;
    line.innerHTML = content;
    terminal.appendChild(line);
    terminal.scrollTop = terminal.scrollHeight;
}

// ── UI ACTIONS ───────────────────────────────────────────
function showExamples() { modalOverlay.classList.add('show'); haptic('light'); }
function hideExamples() { modalOverlay.classList.remove('show'); }
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
    parseCode();
}
async function saveToBrain() {
    if (!editor) return;
    showToast('💾 Speichere ins Brain...');
    try {
        const res = await fetch('/sandbox/api/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                code: editor.getValue(),
                name: 'sandbox_code',
                chat_id: tg ? tg.initDataUnsafe?.user?.id?.toString() : 'sandbox'
            })
        });
        const d = await res.json();
        showToast(d.message || '✅ Gespeichert!');
        if (d.success) {
            log('💾 Im Brain gespeichert', 'success');
        }
    } catch(e) {
        showToast('❌ Speichern fehlgeschlagen');
    }
}
function shareToTelegram() {
    if (!editor) return;
    if (tg) {
        tg.sendData(JSON.stringify({ action: 'share_code', code: editor.getValue() }));
        showToast('📤 Code geteilt');
    } else {
        showToast('Nur in Telegram verfügbar');
    }
}
async function copyCode() {
    if (!editor) return;
    const code = editor.getValue();
    try {
        await navigator.clipboard.writeText(code);
        showToast('📋 Code kopiert!');
        haptic('light');
    } catch(e) {
        // Fallback
        const ta = document.createElement('textarea');
        ta.value = code;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        showToast('📋 Code kopiert (Fallback)');
    }
}
function showToast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.add('show');
    clearTimeout(toastEl._t);
    toastEl._t = setTimeout(function() { toastEl.classList.remove('show'); }, 2500);
}
function setStatus(state, text) {
    statusDot.className = 'status-dot' + (state !== 'ready' ? ' ' + state : '');
    statusText.textContent = text;
}

// ── UTILS ────────────────────────────────────────────────
function escapeHtml(text) {
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
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
function formatBytes(base64Len) {
    const bytes = base64Len * 0.75;
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024*1024) return (bytes/1024).toFixed(1) + ' KB';
    return (bytes/(1024*1024)).toFixed(1) + ' MB';
}

// ── MARKDOWN RENDERER ────────────────────────────────────
function renderMarkdown(text) {
    if (!text) return '';
    let out = escapeHtml(text);
    out = out.replace(/```(\w*)\n?([\s\S]*?)```/g, function(_, lang, code) {
        return `<pre><code>${code.trim()}</code></pre>`;
    });
    out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
    out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    out = out.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    out = out.replace(/\n/g, '<br>');
    return out;
}

// ── AI CHAT ──────────────────────────────────────────────
async function sendChatMessage() {
    if (isChatLoading) return;
    const msg = chatInput.value.trim();
    if (!msg) return;

    appendChatMsg('user', msg);
    chatHistory.push({ role: 'user', content: msg });
    chatInput.value = '';
    chatInput.style.height = 'auto';
    haptic('light');

    const typingEl = appendChatTyping();
    isChatLoading = true;
    chatSend.classList.add('loading');
    chatSend.innerHTML = '⏳';

    try {
        const currentCode = editor ? editor.getValue() : '';
        const res = await fetch('/sandbox/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: msg,
                code: currentCode,
                history: chatHistory.slice(-8),
                chat_id: tg ? tg.initDataUnsafe?.user?.id?.toString() : 'sandbox'
            })
        });

        const data = await res.json();
        if (typingEl && typingEl.parentNode) typingEl.parentNode.removeChild(typingEl);

        if (data.error) {
            appendChatMsg('assistant', '❌ ' + data.error);
        } else {
            const reply = data.reply || 'Keine Antwort erhalten.';
            appendChatMsg('assistant', reply, true);
            chatHistory.push({ role: 'assistant', content: reply });

            // Nutze server-extrahierten Code falls vorhanden
            const codeToInsert = data.code || null;
            if (codeToInsert) {
                offerCodeInsertion(codeToInsert);
            }
        }
        haptic('light');
    } catch(e) {
        if (typingEl && typingEl.parentNode) typingEl.parentNode.removeChild(typingEl);
        appendChatMsg('assistant', '❌ Verbindungsfehler: ' + e.message);
        haptic('heavy');
    } finally {
        isChatLoading = false;
        chatSend.classList.remove('loading');
        chatSend.innerHTML = '➤';
    }
}

function appendChatMsg(role, text, markdown) {
    const div = document.createElement('div');
    div.className = 'chat-msg ' + role;
    const avatar = document.createElement('div');
    avatar.className = 'chat-avatar';
    avatar.textContent = role === 'user' ? '🧑' : '🤖';
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    if (markdown) {
        bubble.innerHTML = renderMarkdown(text);
    } else {
        bubble.textContent = text;
    }
    div.appendChild(avatar);
    div.appendChild(bubble);
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return div;
}

function appendChatTyping() {
    const div = document.createElement('div');
    div.className = 'chat-msg assistant chat-typing';
    div.innerHTML = `
        <div class="chat-avatar">🤖</div>
        <div class="chat-bubble">
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
        </div>`;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return div;
}

function offerCodeInsertion(code) {
    const lastMsg = chatMessages.lastElementChild;
    if (!lastMsg) return;
    const bubble = lastMsg.querySelector('.chat-bubble');
    if (!bubble) return;

    // Container für die Buttons
    const btnContainer = document.createElement('div');
    btnContainer.style.cssText = 'display:flex; gap:6px; margin-top:10px; flex-wrap:wrap;';

    // "Code übernehmen" Button (ersetzt Editor-Inhalt)
    const btnReplace = document.createElement('button');
    btnReplace.className = 'btn btn-run btn-sm';
    btnReplace.style.cssText = 'font-size:0.75rem; min-height:32px; padding:6px 12px;';
    btnReplace.textContent = '📋 Code übernehmen';
    btnReplace.addEventListener('click', function() {
        if (editor) {
            editor.setValue(code, -1);
            showToast('✅ Code übernommen');
            haptic('light');
            parseCode();
            // Auf Editor-Panel wechseln auf Mobile
            if (isMobile) {
                const workspace = document.getElementById('workspace');
                const dots = document.querySelectorAll('.nav-dot');
                workspace.scrollTo({ left: 0, behavior: 'smooth' });
                dots.forEach(function(d, i) { d.classList.toggle('active', i === 0); });
                mobilePanelIndex = 0;
            }
        }
        btnContainer.remove();
    });

    // "Anhängen" Button (fügt Code am Ende hinzu)
    const btnAppend = document.createElement('button');
    btnAppend.className = 'btn btn-secondary btn-sm';
    btnAppend.style.cssText = 'font-size:0.75rem; min-height:32px; padding:6px 12px;';
    btnAppend.textContent = '➕ Anhängen';
    btnAppend.addEventListener('click', function() {
        if (editor) {
            var current = editor.getValue();
            var sep = current && !current.endsWith('\n') ? '\n\n' : '\n';
            editor.setValue(current + sep + code, -1);
            editor.gotoLine(editor.session.getLength(), 0);
            showToast('✅ Code angehängt');
            haptic('light');
            parseCode();
        }
        btnContainer.remove();
    });

    // "Ignorieren" Button
    const btnDismiss = document.createElement('button');
    btnDismiss.className = 'btn btn-secondary btn-sm';
    btnDismiss.style.cssText = 'font-size:0.75rem; min-height:32px; padding:6px 12px; opacity:0.6;';
    btnDismiss.textContent = '✕';
    btnDismiss.addEventListener('click', function() {
        btnContainer.remove();
    });

    btnContainer.appendChild(btnReplace);
    btnContainer.appendChild(btnAppend);
    btnContainer.appendChild(btnDismiss);
    bubble.appendChild(btnContainer);
}

// ── MOBILE PANEL SWIPE SYSTEM ────────────────────────────
(function initMobilePanels() {
    const workspace = document.getElementById('workspace');
    const dots = document.querySelectorAll('.nav-dot');
    const panels = document.querySelectorAll('.mobile-panel');

    function detectMobile() {
        isMobile = window.innerWidth <= 768;
        if (isMobile) {
            workspace.style.scrollSnapType = 'x mandatory';
            // Auf Mobile: Chat immer offen
            chatOpen = true;
            chatSection.classList.remove('collapsed');
            document.getElementById('chat-toggle-arrow').textContent = '▼';
            // Terminal-View forcieren
            switchPane('terminal');
        } else {
            workspace.style.scrollSnapType = 'none';
            workspace.scrollLeft = 0;
        }
        if (editor) setTimeout(function() { editor.resize(); }, 100);
    }

    function scrollToPanel(index) {
        if (!isMobile || !panels[index]) return;
        const panelWidth = panels[index].offsetWidth;
        workspace.scrollTo({ left: panelWidth * index, behavior: 'smooth' });
    }

    function updateDots(index) {
        dots.forEach(function(d, i) {
            d.classList.toggle('active', i === index);
        });
        mobilePanelIndex = index;
        // Swipe-Hinweis nach erstem Wechsel ausblenden
        const hint = document.getElementById('swipe-hint');
        if (hint && index > 0) hint.style.display = 'none';
    }

    // Scroll-Event fuer Snap-Erkennung
    let scrollTimeout;
    workspace.addEventListener('scroll', function() {
        if (!isMobile) return;
        clearTimeout(scrollTimeout);
        scrollTimeout = setTimeout(function() {
            const panelWidth = panels[0] ? panels[0].offsetWidth : window.innerWidth;
            const idx = Math.round(workspace.scrollLeft / panelWidth);
            if (idx !== mobilePanelIndex && idx >= 0 && idx < 3) {
                updateDots(idx);
                haptic('light');
            }
        }, 80);
    });

    // Touch-Swipe mit Velocity-Erkennung
    let touchStartX = 0;
    let touchStartY = 0;
    let touchStartTime = 0;

    workspace.addEventListener('touchstart', function(e) {
        touchStartX = e.touches[0].clientX;
        touchStartY = e.touches[0].clientY;
        touchStartTime = Date.now();
    }, { passive: true });

    workspace.addEventListener('touchend', function(e) {
        if (!isMobile) return;
        const dx = e.changedTouches[0].clientX - touchStartX;
        const dy = e.changedTouches[0].clientY - touchStartY;
        const dt = Date.now() - touchStartTime;

        // Nur horizontal Swipes (nicht vertikal)
        if (Math.abs(dx) < Math.abs(dy) * 1.5) return;

        const velocity = Math.abs(dx) / (dt || 1);
        const threshold = velocity > 0.5 ? 30 : 60; // niedriger Threshold bei schnellem Swipe

        if (Math.abs(dx) > threshold) {
            let newIdx = mobilePanelIndex;
            if (dx < 0 && mobilePanelIndex < 2) newIdx++;
            if (dx > 0 && mobilePanelIndex > 0) newIdx--;
            if (newIdx !== mobilePanelIndex) {
                scrollToPanel(newIdx);
                updateDots(newIdx);
            }
        }
    }, { passive: true });

    // Dots Click
    dots.forEach(function(dot) {
        dot.addEventListener('click', function() {
            const idx = parseInt(dot.dataset.panel);
            scrollToPanel(idx);
            updateDots(idx);
            haptic('medium');
        });
    });

    // Resize-Listener
    window.addEventListener('resize', function() {
        detectMobile();
    });

    // Init
    detectMobile();
})();

// ── CODE DOWNLOAD ────────────────────────────────────────
function downloadCode() {
    if (!editor) { showToast('❌ Editor nicht bereit'); return; }
    const code = editor.getValue();
    const lang = document.getElementById('lang-select').value;
    const ext = lang === 'html' ? 'html' : 'py';
    const defaultName = lang === 'html' ? 'sandbox_app' : 'sandbox_code';
    const filename = prompt('Dateiname:', defaultName + '.' + ext);
    if (!filename) return;

    const blob = new Blob([code], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('⬇️ ' + filename + ' heruntergeladen');
    haptic('light');
}

// ── INIT ─────────────────────────────────────────────────
loadTemplates();
log('👑 Sandbox V8 bereit', 'success');
log('▶ Run (Ctrl+Enter) | 💾 Save (Ctrl+S) | 📋 Copy | 🤖 KI-Chat | ⬇️ Download', 'info');
setTimeout(checkPermissions, 1000);