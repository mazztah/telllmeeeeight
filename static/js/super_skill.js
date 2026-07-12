// ═══════════════════════════════════════════════════════════════════════════════
// SUPER-SKILL.MD GENERATOR — FRONTEND JAVASCRIPT
// Version: 1.0.0 | 2026
// API-Pfade: /superskill/api/* und /superskill/ws/chat
// ═══════════════════════════════════════════════════════════════════════════════

'use strict';

// ═══════════════════════════════════════════════════════════════════════════════
// STATE MANAGEMENT
// ═══════════════════════════════════════════════════════════════════════════════

const State = {
    currentSkill: null,
    chatHistory: [],
    ws: null,
    isGenerating: false,
    activeTab: 'preview',
    libraryCollapsed: false,
    currentSkillContent: ''
};

// API Base Path
const API_BASE = '/superskill';

// ═══════════════════════════════════════════════════════════════════════════════
// DOM REFERENCES
// ═══════════════════════════════════════════════════════════════════════════════

const DOM = {
    scopeInput: () => document.getElementById('scopeInput'),
    audienceSelect: () => document.getElementById('audienceSelect'),
    depthSlider: () => document.getElementById('depthSlider'),
    modelSelect: () => document.getElementById('modelSelect'),
    workflowTags: () => document.querySelectorAll('.workflow-tag'),
    generateBtn: () => document.getElementById('generateBtn'),
    chatInput: () => document.getElementById('chatInput'),
    chatMessages: () => document.getElementById('chatMessages'),
    sendBtn: () => document.getElementById('sendBtn'),
    previewArea: () => document.getElementById('previewArea'),
    emptyState: () => document.getElementById('emptyState'),
    markdownPreview: () => document.getElementById('markdownPreview'),
    rawTextarea: () => document.getElementById('rawTextarea'),
    splitTextarea: () => document.getElementById('splitTextarea'),
    splitPreview: () => document.getElementById('splitPreview'),
    loadingOverlay: () => document.getElementById('loadingOverlay'),
    refineModal: () => document.getElementById('refineModal'),
    refineInput: () => document.getElementById('refineInput'),
    skillsGrid: () => document.getElementById('skillsGrid'),
    skillsCount: () => document.getElementById('skillsCount'),
    skillsLibrary: () => document.getElementById('skillsLibrary'),
    toastContainer: () => document.getElementById('toastContainer')
};

// ═══════════════════════════════════════════════════════════════════════════════
// INITIALIZATION
// ═══════════════════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    initWorkflowTags();
    initWebSocket();
    initAutoResize();
    initDepthSlider();
    refreshSkillsList();

    if (typeof gsap !== 'undefined') {
        gsap.from('.panel', {
            y: 30, opacity: 0, duration: 0.6, stagger: 0.15, ease: 'power3.out'
        });
        gsap.from('.main-header', {
            y: -20, opacity: 0, duration: 0.5, ease: 'power2.out'
        });
    }
});

// ═══════════════════════════════════════════════════════════════════════════════
// WORKFLOW TAGS
// ═══════════════════════════════════════════════════════════════════════════════

function initWorkflowTags() {
    DOM.workflowTags().forEach(tag => {
        tag.addEventListener('click', () => {
            tag.classList.toggle('active');
            animateTagClick(tag);
        });
    });
}

function animateTagClick(tag) {
    if (typeof gsap !== 'undefined') {
        gsap.fromTo(tag, { scale: 0.95 }, { scale: 1, duration: 0.2, ease: 'back.out(2)' });
    }
}

function getSelectedWorkflows() {
    return Array.from(DOM.workflowTags())
        .filter(tag => tag.classList.contains('active'))
        .map(tag => tag.dataset.value);
}

// ═══════════════════════════════════════════════════════════════════════════════
// DEPTH SLIDER
// ═══════════════════════════════════════════════════════════════════════════════

function initDepthSlider() {
    const slider = DOM.depthSlider();
    slider.addEventListener('input', (e) => {
        const value = parseInt(e.target.value);
        if (typeof gsap !== 'undefined') {
            gsap.to(slider, { '--slider-glow': value * 0.3, duration: 0.3 });
        }
    });
}

function getDepthLabel() {
    const value = parseInt(DOM.depthSlider().value);
    return ['Überblick', 'Detailliert', 'Exhaustive'][value - 1];
}

// ═══════════════════════════════════════════════════════════════════════════════
// WEBSOCKET CHAT (mit /superskill prefix)
// ═══════════════════════════════════════════════════════════════════════════════

function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}${API_BASE}/ws/chat`;

    State.ws = new WebSocket(wsUrl);

    State.ws.onopen = () => {
        console.log('WebSocket verbunden');
        showToast('Chat verbunden', 'success');
    };

    State.ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleWebSocketMessage(data);
    };

    State.ws.onclose = () => {
        console.log('WebSocket geschlossen, versuche Reconnect...');
        setTimeout(initWebSocket, 3000);
    };

    State.ws.onerror = (error) => {
        console.error('WebSocket Fehler:', error);
        showToast('Chat-Verbindung unterbrochen', 'warning');
    };
}

function handleWebSocketMessage(data) {
    switch (data.type) {
        case 'stream':
            appendStreamChunk(data.chunk);
            break;
        case 'done':
            finalizeStream(data.full_response);
            break;
        case 'typing':
            toggleTypingIndicator(data.status);
            break;
    }
}

function appendStreamChunk(chunk) {
    const messages = DOM.chatMessages();
    let lastMessage = messages.lastElementChild;

    if (!lastMessage || !lastMessage.classList.contains('streaming')) {
        lastMessage = createAssistantMessage('');
        lastMessage.classList.add('streaming');
        messages.appendChild(lastMessage);
    }

    const textEl = lastMessage.querySelector('.message-text');
    textEl.innerHTML += chunk;
    messages.scrollTop = messages.scrollHeight;
}

function finalizeStream(fullResponse) {
    const messages = DOM.chatMessages();
    const streamingMsg = messages.querySelector('.streaming');

    if (streamingMsg) {
        streamingMsg.classList.remove('streaming');
        const textEl = streamingMsg.querySelector('.message-text');
        textEl.innerHTML = formatMessageText(fullResponse);
    }

    toggleTypingIndicator(false);
}

function toggleTypingIndicator(show) {
    const messages = DOM.chatMessages();
    let typingIndicator = messages.querySelector('.typing-indicator');

    if (show && !typingIndicator) {
        typingIndicator = document.createElement('div');
        typingIndicator.className = 'message typing-indicator';
        typingIndicator.innerHTML = `
            <div class="message-avatar"><span>🧠</span></div>
            <div class="message-content">
                <div class="message-header">
                    <span class="message-author">Groq Assistant</span>
                </div>
                <div class="typing-dots">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
            </div>
        `;
        messages.appendChild(typingIndicator);
        messages.scrollTop = messages.scrollHeight;
    } else if (!show && typingIndicator) {
        typingIndicator.remove();
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// CHAT FUNCTIONS
// ═══════════════════════════════════════════════════════════════════════════════

function sendMessage() {
    const input = DOM.chatInput();
    const message = input.value.trim();

    if (!message || !State.ws || State.ws.readyState !== WebSocket.OPEN) return;

    addUserMessage(message);
    State.ws.send(JSON.stringify({ message }));
    input.value = '';
    input.style.height = 'auto';

    State.chatHistory.push({ role: 'user', content: message });
}

function addUserMessage(text) {
    const messages = DOM.chatMessages();
    const msg = document.createElement('div');
    msg.className = 'message user-message';
    msg.innerHTML = `
        <div class="message-avatar"><span>👤</span></div>
        <div class="message-content">
            <div class="message-header">
                <span class="message-author">Du</span>
                <span class="message-time">${new Date().toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })}</span>
            </div>
            <div class="message-text">${escapeHtml(text)}</div>
        </div>
    `;
    messages.appendChild(msg);
    messages.scrollTop = messages.scrollHeight;

    if (typeof gsap !== 'undefined') {
        gsap.from(msg, { x: 20, opacity: 0, duration: 0.3, ease: 'power2.out' });
    }
}

function createAssistantMessage(text) {
    const msg = document.createElement('div');
    msg.className = 'message';
    msg.innerHTML = `
        <div class="message-avatar"><span>🧠</span></div>
        <div class="message-content">
            <div class="message-header">
                <span class="message-author">Groq Assistant</span>
                <span class="message-time">${new Date().toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })}</span>
            </div>
            <div class="message-text">${text}</div>
        </div>
    `;
    return msg;
}

function formatMessageText(text) {
    return escapeHtml(text)
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/`(.+?)`/g, '<code>$1</code>')
        .replace(/\n/g, '<br>');
}

function handleChatKeydown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SKILL GENERATION (mit /superskill prefix)
// ═══════════════════════════════════════════════════════════════════════════════

async function generateSkill() {
    const scope = DOM.scopeInput().value.trim();

    if (!scope || scope.length < 20) {
        showToast('Bitte gib einen Scope mit mindestens 20 Zeichen ein', 'warning');
        DOM.scopeInput().focus();
        return;
    }

    if (State.isGenerating) return;
    State.isGenerating = true;

    showLoadingOverlay();
    animateLoadingSteps();

    const request = {
        scope: scope,
        audience: DOM.audienceSelect().value,
        depth: getDepthLabel(),
        model: DOM.modelSelect().value,
        workflows: getSelectedWorkflows()
    };

    try {
        const response = await fetch(`${API_BASE}/api/generate-skill`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(request)
        });

        const data = await response.json();

        if (data.success) {
            State.currentSkill = data.skill;
            State.currentSkillContent = data.skill.full_content;

            showPreview(data.skill.full_content);
            DOM.rawTextarea().value = data.skill.full_content;
            DOM.splitTextarea().value = data.skill.full_content;

            DOM.emptyState().style.display = 'none';
            DOM.previewArea().style.display = 'flex';

            refreshSkillsList();

            showToast(`PowerSkill "${data.skill.title}" erfolgreich generiert!`, 'success');

            if (typeof gsap !== 'undefined') {
                gsap.from('.preview-area', { opacity: 0, y: 20, duration: 0.5 });
            }
        } else {
            showToast(data.error || 'Fehler bei der Generierung', 'error');
        }
    } catch (error) {
        console.error('Generation Error:', error);
        showToast('Netzwerkfehler bei der Generierung', 'error');
    } finally {
        hideLoadingOverlay();
        State.isGenerating = false;
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// PREVIEW FUNCTIONS
// ═══════════════════════════════════════════════════════════════════════════════

function showPreview(markdown) {
    const preview = DOM.markdownPreview();
    preview.innerHTML = marked.parse(markdown);

    if (typeof hljs !== 'undefined') {
        preview.querySelectorAll('pre code').forEach(block => {
            hljs.highlightElement(block);
        });
    }
}

function switchTab(tab) {
    State.activeTab = tab;

    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tab);
    });

    DOM.previewArea().style.display = tab === 'preview' ? 'flex' : 'none';
    document.getElementById('rawEditor').style.display = tab === 'raw' ? 'block' : 'none';
    document.getElementById('splitView').style.display = tab === 'split' ? 'grid' : 'none';

    if (tab === 'split') {
        updateSplitPreview();
    }
}

function updateSplitPreview() {
    const content = DOM.splitTextarea().value;
    DOM.splitPreview().innerHTML = marked.parse(content);
}

// ═══════════════════════════════════════════════════════════════════════════════
// SKILL REFINEMENT (mit /superskill prefix)
// ═══════════════════════════════════════════════════════════════════════════════

function showRefineModal() {
    if (!State.currentSkill) {
        showToast('Bitte generiere zuerst einen Skill', 'warning');
        return;
    }
    DOM.refineModal().classList.add('active');
    DOM.refineInput().focus();
}

function closeRefineModal() {
    DOM.refineModal().classList.remove('active');
    DOM.refineInput().value = '';
}

async function refineSkill() {
    const feedback = DOM.refineInput().value.trim();

    if (!feedback) {
        showToast('Bitte gib Feedback ein', 'warning');
        return;
    }

    closeRefineModal();
    showLoadingOverlay();

    try {
        const response = await fetch(`${API_BASE}/api/refine-skill/${State.currentSkill.skill_id}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ feedback })
        });

        const data = await response.json();

        if (data.success) {
            State.currentSkill = data.skill;
            State.currentSkillContent = data.skill.full_content;

            showPreview(data.skill.full_content);
            DOM.rawTextarea().value = data.skill.full_content;
            DOM.splitTextarea().value = data.skill.full_content;

            refreshSkillsList();
            showToast('Skill erfolgreich verbessert!', 'success');
        } else {
            showToast(data.error || 'Fehler beim Verbessern', 'error');
        }
    } catch (error) {
        showToast('Netzwerkfehler', 'error');
    } finally {
        hideLoadingOverlay();
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// DOWNLOAD & COPY (mit /superskill prefix)
// ═══════════════════════════════════════════════════════════════════════════════

function downloadSkill() {
    if (!State.currentSkill) {
        showToast('Kein Skill zum Download verfügbar', 'warning');
        return;
    }

    window.location.href = `${API_BASE}/api/download-skill/${State.currentSkill.skill_id}`;
    showToast('Download gestartet', 'success');
}

function copyToClipboard() {
    if (!State.currentSkillContent) {
        showToast('Kein Inhalt zum Kopieren', 'warning');
        return;
    }

    navigator.clipboard.writeText(State.currentSkillContent).then(() => {
        showToast('Inhalt kopiert!', 'success');
    }).catch(() => {
        showToast('Kopieren fehlgeschlagen', 'error');
    });
}

// ═══════════════════════════════════════════════════════════════════════════════
// SKILLS LIBRARY (mit /superskill prefix)
// ═══════════════════════════════════════════════════════════════════════════════

async function refreshSkillsList() {
    try {
        const response = await fetch(`${API_BASE}/api/list-skills`);
        const data = await response.json();

        renderSkillsGrid(data.skills || []);
        DOM.skillsCount().textContent = (data.skills || []).length;
    } catch (error) {
        console.error('Fehler beim Laden der Skills:', error);
    }
}

function renderSkillsGrid(skills) {
    const grid = DOM.skillsGrid();

    if (skills.length === 0) {
        grid.innerHTML = `
            <div class="skill-card" style="justify-content: center; opacity: 0.5;">
                <span style="color: var(--text-muted); font-size: 0.85rem;">Noch keine Skills generiert</span>
            </div>
        `;
        return;
    }

    grid.innerHTML = skills.map(skill => `
        <div class="skill-card" data-filename="${skill.filename}">
            <div class="skill-icon">📄</div>
            <div class="skill-info">
                <div class="skill-name">${skill.filename.replace('.md', '')}</div>
                <div class="skill-meta">${formatFileSize(skill.size)} · ${formatDate(skill.created)}</div>
            </div>
            <div class="skill-actions">
                <button class="skill-action-btn" onclick="downloadSkillByUrl('${skill.download_url}')" title="Download">
                    ⬇️
                </button>
            </div>
        </div>
    `).join('');
}

function downloadSkillByUrl(url) {
    window.location.href = url;
    showToast('Download gestartet', 'success');
}

function toggleLibrary() {
    State.libraryCollapsed = !State.libraryCollapsed;
    DOM.skillsLibrary().classList.toggle('collapsed', State.libraryCollapsed);
    document.getElementById('libraryToggleIcon').textContent = State.libraryCollapsed ? '🔽' : '🔼';
}

// ═══════════════════════════════════════════════════════════════════════════════
// LOADING OVERLAY
// ═══════════════════════════════════════════════════════════════════════════════

function showLoadingOverlay() {
    DOM.loadingOverlay().classList.add('active');
    resetLoadingSteps();
}

function hideLoadingOverlay() {
    DOM.loadingOverlay().classList.remove('active');
}

function resetLoadingSteps() {
    document.querySelectorAll('.step').forEach(step => {
        step.classList.remove('active', 'completed');
    });
}

function animateLoadingSteps() {
    const steps = document.querySelectorAll('.step');
    const delays = [0, 1500, 3000, 5000];

    steps.forEach((step, index) => {
        setTimeout(() => {
            if (index > 0) steps[index - 1].classList.remove('active');
            if (index > 0) steps[index - 1].classList.add('completed');
            step.classList.add('active');
        }, delays[index]);
    });
}

// ═══════════════════════════════════════════════════════════════════════════════
// TOAST NOTIFICATIONS
// ═══════════════════════════════════════════════════════════════════════════════

function showToast(message, type = 'info') {
    const container = DOM.toastContainer();
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };

    toast.innerHTML = `
        <span class="toast-icon">${icons[type] || icons.info}</span>
        <div class="toast-content">
            <div class="toast-title">${type === 'success' ? 'Erfolg' : type === 'error' ? 'Fehler' : type === 'warning' ? 'Warnung' : 'Info'}</div>
            <div class="toast-message">${message}</div>
        </div>
        <button class="toast-close" onclick="this.parentElement.remove()">×</button>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        if (toast.parentElement) {
            if (typeof gsap !== 'undefined') {
                gsap.to(toast, { x: 100, opacity: 0, duration: 0.3, onComplete: () => toast.remove() });
            } else {
                toast.remove();
            }
        }
    }, 5000);
}

// ═══════════════════════════════════════════════════════════════════════════════
// UTILITY FUNCTIONS
// ═══════════════════════════════════════════════════════════════════════════════

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function formatDate(isoString) {
    const date = new Date(isoString);
    return date.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

function togglePanel(panelId) {
    const panel = document.getElementById(panelId);
    panel.classList.toggle('collapsed');
}

function initAutoResize() {
    const textareas = document.querySelectorAll('textarea');
    textareas.forEach(textarea => {
        textarea.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 200) + 'px';
        });
    });
}

// ═══════════════════════════════════════════════════════════════════════════════
// KEYBOARD SHORTCUTS
// ═══════════════════════════════════════════════════════════════════════════════

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeRefineModal();
    }

    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        if (document.activeElement === DOM.scopeInput()) {
            generateSkill();
        }
    }
});
