# diagnose_app.py – System Diagnose Dashboard mit Filter
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
import asyncio
import json

from test_suite import run_diagnostics

app = FastAPI(title="Bot System Diagnose")

# Kategorie-Icons für Filter
CATEGORY_ICONS = {
    "CORE": "⚙️",
    "AI_APIS": "🤖", 
    "BRAIN_MEMORY": "🧠",
    "MEDIA_GENERATION": "🎨",
    "VOICE_AUDIO": "🎤",
    "3D_GRAPHICS": "🧊",
    "WEB_INTEGRATION": "🌐",
    "UTILITIES": "🛠️",
    "HANDLERS": "📱",
    "MINI_APPS": "🎮",
    "SECURITY": "🔒"
}

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 Bot System-Diagnose</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        :root {
            --bg: #0d0014;
            --surface: #160020;
            --card: #1e002e;
            --card-hover: #2a0044;
            --border: #3d005a;
            --accent: #cc44ff;
            --accent-glow: rgba(204, 68, 255, 0.3);
            --success: #00ff88;
            --error: #ff4444;
            --warning: #ffcc44;
            --text: #f0d6ff;
            --text-muted: #9966bb;
        }
        
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            background: var(--bg);
            color: var(--text);
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            min-height: 100vh;
            line-height: 1.6;
        }
        
        .container { max-width: 900px; margin: 0 auto; padding: 20px; }
        
        /* Header */
        .header {
            text-align: center;
            padding: 40px 20px;
            background: linear-gradient(135deg, var(--surface) 0%, var(--card) 100%);
            border-bottom: 1px solid var(--border);
            margin-bottom: 30px;
            position: relative;
            overflow: hidden;
        }
        
        .header::before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle, var(--accent-glow) 0%, transparent 70%);
            animation: pulse 4s ease-in-out infinite;
        }
        
        @keyframes pulse {
            0%, 100% { transform: scale(1); opacity: 0.5; }
            50% { transform: scale(1.1); opacity: 0.8; }
        }
        
        h1 {
            font-size: 2.5rem;
            font-weight: 800;
            background: linear-gradient(135deg, var(--accent), #ff44cc);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 15px;
            position: relative;
            z-index: 1;
        }
        
        .subtitle {
            color: var(--text-muted);
            font-size: 1rem;
            position: relative;
            z-index: 1;
        }
        
        .status-badge {
            display: inline-block;
            margin-top: 20px;
            padding: 12px 30px;
            border-radius: 30px;
            font-weight: 700;
            font-size: 1.1rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            position: relative;
            z-index: 1;
            animation: glow 2s ease-in-out infinite alternate;
        }
        
        @keyframes glow {
            from { box-shadow: 0 0 10px var(--accent-glow); }
            to { box-shadow: 0 0 25px var(--accent-glow), 0 0 10px var(--accent); }
        }
        
        .status-healthy {
            background: rgba(0, 255, 136, 0.1);
            border: 2px solid var(--success);
            color: var(--success);
        }
        
        .status-issues {
            background: rgba(255, 68, 68, 0.1);
            border: 2px solid var(--error);
            color: var(--error);
        }
        
        .status-warning {
            background: rgba(255, 204, 68, 0.1);
            border: 2px solid var(--warning);
            color: var(--warning);
        }
        
        /* Summary Cards */
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }
        
        .stat-card {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 25px;
            text-align: center;
            transition: transform 0.3s, box-shadow 0.3s;
            position: relative;
            overflow: hidden;
        }
        
        .stat-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        }
        
        .stat-card::after {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: linear-gradient(90deg, var(--accent), #ff44cc);
        }
        
        .stat-value {
            font-size: 3rem;
            font-weight: 800;
            margin-bottom: 8px;
        }
        
        .stat-value.success { color: var(--success); }
        .stat-value.error { color: var(--error); }
        .stat-value.accent { color: var(--accent); }
        
        .stat-label {
            color: var(--text-muted);
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        /* Filter Buttons */
        .filter-container {
            margin: 30px 0;
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            justify-content: center;
            padding: 20px;
            background: var(--surface);
            border-radius: 16px;
            border: 1px solid var(--border);
        }
        
        .filter-btn {
            background: var(--card);
            border: 1px solid var(--border);
            color: var(--text);
            padding: 10px 20px;
            border-radius: 25px;
            cursor: pointer;
            font-size: 0.95rem;
            transition: all 0.3s;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .filter-btn:hover {
            background: var(--card-hover);
            border-color: var(--accent);
            transform: scale(1.05);
        }
        
        .filter-btn.active {
            background: var(--accent);
            border-color: var(--accent);
            color: white;
            box-shadow: 0 0 20px var(--accent-glow);
        }
        
        .filter-btn .count {
            background: rgba(255,255,255,0.2);
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 0.8rem;
            font-weight: bold;
        }
        
        /* Test Items */
        .test-list {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        
        .test-item {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            display: flex;
            align-items: flex-start;
            gap: 15px;
            transition: all 0.3s;
            cursor: pointer;
        }
        
        .test-item:hover {
            background: var(--card-hover);
            border-color: var(--accent);
            transform: translateX(5px);
        }
        
        .test-item.hidden {
            display: none;
        }
        
        .test-icon {
            font-size: 1.5rem;
            width: 40px;
            height: 40px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 10px;
            background: rgba(255,255,255,0.05);
            flex-shrink: 0;
        }
        
        .test-icon.success { background: rgba(0, 255, 136, 0.1); }
        .test-icon.error { background: rgba(255, 68, 68, 0.1); }
        
        .test-content {
            flex: 1;
            min-width: 0;
        }
        
        .test-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 5px;
            flex-wrap: wrap;
            gap: 10px;
        }
        
        .test-name {
            font-weight: 600;
            font-size: 1.1rem;
        }
        
        .test-module {
            color: var(--accent);
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .test-message {
            color: var(--text-muted);
            font-size: 0.95rem;
            margin-top: 5px;
            word-break: break-word;
        }
        
        .test-meta {
            display: flex;
            gap: 15px;
            margin-top: 10px;
            font-size: 0.85rem;
            color: var(--text-muted);
        }
        
        .test-duration {
            font-family: monospace;
            background: rgba(255,255,255,0.05);
            padding: 2px 8px;
            border-radius: 6px;
        }
        
        .critical-badge {
            background: var(--error);
            color: white;
            padding: 2px 8px;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: bold;
            text-transform: uppercase;
        }
        
        /* Loading State */
        .loading-container {
            text-align: center;
            padding: 100px 20px;
        }
        
        .spinner {
            width: 60px;
            height: 60px;
            border: 4px solid var(--border);
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 30px;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        .loading-text {
            color: var(--text-muted);
            font-size: 1.2rem;
        }
        
        /* Refresh Button */
        .refresh-btn {
            position: fixed;
            bottom: 30px;
            right: 30px;
            width: 60px;
            height: 60px;
            border-radius: 50%;
            background: var(--accent);
            border: none;
            color: white;
            font-size: 1.5rem;
            cursor: pointer;
            box-shadow: 0 5px 20px var(--accent-glow);
            transition: all 0.3s;
            z-index: 100;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .refresh-btn:hover {
            transform: scale(1.1) rotate(180deg);
            box-shadow: 0 8px 30px var(--accent-glow);
        }
        
        .refresh-btn.spinning {
            animation: spin 1s linear infinite;
        }
        
        /* Error State */
        .error-message {
            background: rgba(255, 68, 68, 0.1);
            border: 1px solid var(--error);
            color: var(--error);
            padding: 30px;
            border-radius: 16px;
            text-align: center;
        }
        
        /* Empty State */
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: var(--text-muted);
        }
        
        /* Progress Bar */
        .progress-container {
            margin: 20px 0;
            background: var(--surface);
            border-radius: 10px;
            height: 10px;
            overflow: hidden;
            border: 1px solid var(--border);
        }
        
        .progress-bar {
            height: 100%;
            background: linear-gradient(90deg, var(--accent), #ff44cc);
            transition: width 0.3s;
        }
        
        /* Responsive */
        @media (max-width: 768px) {
            h1 { font-size: 1.8rem; }
            .summary-grid { grid-template-columns: repeat(2, 1fr); }
            .test-header { flex-direction: column; align-items: flex-start; }
            .filter-btn { padding: 8px 15px; font-size: 0.9rem; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 System Diagnose</h1>
            <div class="subtitle">Umfassender Health-Check aller Bot-Module</div>
            <div id="overall-status">Lade...</div>
            <div style="margin-top: 15px; font-size: 0.9rem; opacity: 0.7;" id="timestamp"></div>
        </div>
        
        <div id="loading" class="loading-container">
            <div class="spinner"></div>
            <div class="loading-text">Führe Tests durch...</div>
            <div class="progress-container" style="max-width: 400px; margin: 20px auto;">
                <div class="progress-bar" id="progress" style="width: 0%"></div>
            </div>
        </div>
        
        <div id="content" style="display: none;">
            <div class="summary-grid" id="summary"></div>
            
            <div class="filter-container" id="filters"></div>
            
            <div class="test-list" id="test-list"></div>
        </div>
        
        <div id="error" class="error-message" style="display: none;"></div>
    </div>
    
    <button class="refresh-btn" onclick="refreshTests()" title="Neu testen">↻</button>

    <script>
        const tg = window.Telegram.WebApp;
        tg.expand();
        tg.ready();
        
        // Theme anpassen
        if (tg.colorScheme === 'dark') {
            document.documentElement.style.setProperty('--bg', '#0d0014');
        }
        
        let allData = null;
        let currentFilter = 'ALL';
        
        const CATEGORY_ICONS = {
            "CORE": "⚙️",
            "AI_APIS": "🤖", 
            "BRAIN_MEMORY": "🧠",
            "MEDIA_GENERATION": "🎨",
            "VOICE_AUDIO": "🎤",
            "3D_GRAPHICS": "🧊",
            "WEB_INTEGRATION": "🌐",
            "UTILITIES": "🛠️",
            "HANDLERS": "📱",
            "MINI_APPS": "🎮",
            "SECURITY": "🔒"
        };
        
        async function loadDiagnostics() {
            const loading = document.getElementById('loading');
            const content = document.getElementById('content');
            const error = document.getElementById('error');
            
            try {
                // Simuliere Fortschritt
                const progress = document.getElementById('progress');
                let width = 0;
                const interval = setInterval(() => {
                    if (width < 90) {
                        width += Math.random() * 10;
                        progress.style.width = width + '%';
                    }
                }, 300);
                
                const response = await fetch('api/run-tests');
                clearInterval(interval);
                progress.style.width = '100%';
                
                if (!response.ok) throw new Error('HTTP ' + response.status);
                
                const data = await response.json();
                allData = data;
                
                setTimeout(() => {
                    loading.style.display = 'none';
                    content.style.display = 'block';
                    renderData(data);
                }, 500);
                
            } catch (e) {
                loading.style.display = 'none';
                error.style.display = 'block';
                error.textContent = '❌ Fehler beim Laden: ' + e.message;
                console.error(e);
            }
        }
        
        function renderData(data) {
            // Status Badge
            const statusDiv = document.getElementById('overall-status');
            let statusClass = 'status-healthy';
            let statusText = '🟢 System Gesund';
            
            if (data.critical_failures > 0) {
                statusClass = 'status-issues';
                statusText = '🔴 Kritische Fehler';
            } else if (data.failed > 0) {
                statusClass = 'status-warning';
                statusText = '🟡 Einige Probleme';
            }
            
            statusDiv.innerHTML = `<div class="status-badge ${statusClass}">${statusText}</div>`;
            document.getElementById('timestamp').textContent = 
                new Date(data.timestamp).toLocaleString('de-DE');
            
            // Summary Cards
            const summary = document.getElementById('summary');
            const passRate = Math.round((data.passed / data.total_tests) * 100);
            
            summary.innerHTML = `
                <div class="stat-card">
                    <div class="stat-value accent">${data.total_tests}</div>
                    <div class="stat-label">Tests Gesamt</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value success">${data.passed}</div>
                    <div class="stat-label">Bestanden</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value error">${data.failed}</div>
                    <div class="stat-label">Fehler</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value accent">${passRate}%</div>
                    <div class="stat-label">Erfolgsquote</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value ${data.critical_failures > 0 ? 'error' : 'success'}">${data.critical_failures}</div>
                    <div class="stat-label">Kritisch</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value accent">${data.duration}</div>
                    <div class="stat-label">Dauer</div>
                </div>
            `;
            
            // Filter Buttons
            renderFilters(data);
            
            // Test List
            renderTestList(data.results);
        }
        
        function renderFilters(data) {
            const container = document.getElementById('filters');
            const categories = {};
            
            data.results.forEach(r => {
                if (!categories[r.module]) categories[r.module] = { total: 0, passed: 0 };
                categories[r.module].total++;
                if (r.ok) categories[r.module].passed++;
            });
            
            let html = `<button class="filter-btn ${currentFilter === 'ALL' ? 'active' : ''}" onclick="filterByCategory('ALL')">
                📋 Alle <span class="count">${data.total_tests}</span>
            </button>`;
            
            Object.entries(CATEGORY_ICONS).forEach(([cat, icon]) => {
                if (categories[cat]) {
                    const info = categories[cat];
                    html += `<button class="filter-btn ${currentFilter === cat ? 'active' : ''}" onclick="filterByCategory('${cat}')">
                        ${icon} ${cat.replace('_', ' ')} <span class="count">${info.passed}/${info.total}</span>
                    </button>`;
                }
            });
            
            container.innerHTML = html;
        }
        
        function renderTestList(results) {
            const container = document.getElementById('test-list');
            container.innerHTML = '';
            
            const filtered = currentFilter === 'ALL' 
                ? results 
                : results.filter(r => r.module === currentFilter);
            
            if (filtered.length === 0) {
                container.innerHTML = '<div class="empty-state">Keine Tests in dieser Kategorie</div>';
                return;
            }
            
            filtered.forEach(test => {
                const item = document.createElement('div');
                item.className = 'test-item';
                
                const isOk = test.ok;
                const iconClass = isOk ? 'success' : 'error';
                const icon = isOk ? '✓' : '✗';
                
                item.innerHTML = `
                    <div class="test-icon ${iconClass}">${icon}</div>
                    <div class="test-content">
                        <div class="test-header">
                            <div>
                                <div class="test-name">${test.test}</div>
                                <div class="test-module">${CATEGORY_ICONS[test.module] || '📦'} ${test.module}</div>
                            </div>
                            ${test.critical ? '<span class="critical-badge">Kritisch</span>' : ''}
                        </div>
                        <div class="test-message">${escapeHtml(test.message)}</div>
                        <div class="test-meta">
                            <span class="test-duration">⏱ ${test.duration}</span>
                            <span>${test.timestamp.split('T')[1].split('.')[0]}</span>
                        </div>
                    </div>
                `;
                
                container.appendChild(item);
            });
        }
        
        function filterByCategory(category) {
            currentFilter = category;
            renderFilters(allData);
            renderTestList(allData.results);
        }
        
        function refreshTests() {
            const btn = document.querySelector('.refresh-btn');
            btn.classList.add('spinning');
            
            document.getElementById('content').style.display = 'none';
            document.getElementById('error').style.display = 'none';
            document.getElementById('loading').style.display = 'block';
            
            setTimeout(() => {
                location.reload();
            }, 500);
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        // Start
        loadDiagnostics();
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return HTMLResponse(HTML_TEMPLATE)

@app.get("/api/run-tests")
async def api_run_tests():
    """API Endpoint für die Tests"""
    try:
        results = await run_diagnostics()
        return JSONResponse(content=results)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "status": "error"}
        )

@app.get("/api/module/{module_name}")
async def api_module_detail(module_name: str):
    """Details für ein spezifisches Modul"""
    try:
        results = await run_diagnostics()
        module_tests = [r for r in results["results"] if r["module"] == module_name]
        return {
            "module": module_name,
            "tests": module_tests,
            "passed": sum(1 for t in module_tests if t["ok"]),
            "total": len(module_tests)
        }
    except Exception as e:
        return {"error": str(e)}
