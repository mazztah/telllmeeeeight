# trichome_mini_app.py – Queen's Trichom-Scanner Mini-App
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI(title="Queen's Trichom Scanner")

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Queen's Trichom-Scanner</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
        :root { --teal: #00d4aa; --gold: #f5c242; --red: #ef4444; --green: #22c55e; --bg: #0f0f1a; }
        * { box-sizing: border-box; }
        body { margin:0; background:var(--bg); color:#ddd; font-family:'Inter',sans-serif; min-height:100vh; }

        /* Header */
        .header { background:linear-gradient(180deg,#1a1a2e,#0f0f1a); padding:16px 20px; border-bottom:1px solid #222; text-align:center; }
        .header h1 { margin:0; font-size:1.5rem; color:var(--gold); text-shadow:0 0 15px var(--gold); }
        .header p { margin:6px 0 0; font-size:0.8rem; color:#888; }

        /* Tabs */
        .tabs { display:flex; background:#1a1a2e; }
        .tab { flex:1; padding:12px 8px; text-align:center; font-weight:600; font-size:0.8rem; cursor:pointer;
               color:#888; border:none; background:transparent; border-bottom:2px solid transparent; transition:all 0.3s; }
        .tab.active { color:var(--gold); border-bottom-color:var(--gold); }

        /* Content */
        .content { display:none; padding:16px; }
        .content.active { display:block; }

        /* Camera */
        .cam-wrap { background:#111; border-radius:16px; overflow:hidden; aspect-ratio:4/3; position:relative;
                    border:2px solid #333; margin-bottom:12px; }
        .cam-wrap video, .cam-wrap canvas { width:100%; height:100%; object-fit:cover; }
        .cam-overlay { position:absolute; inset:0; background:rgba(0,0,0,0.7); display:flex;
                       flex-direction:column; align-items:center; justify-content:center; gap:10px; cursor:pointer; }
        .cam-overlay .icon { font-size:3.5rem; }
        .cam-overlay p { color:var(--teal); font-size:0.95rem; margin:0; }
        .cam-overlay .sub { color:#666; font-size:0.75rem; margin:0; }

        /* Quality Warning */
        .warn { background:rgba(239,68,68,0.15); border:1px solid var(--red); border-radius:10px;
                padding:10px 14px; margin-bottom:10px; font-size:0.8rem; color:var(--red);
                display:none; text-align:center; }
        .warn.show { display:block; }

        /* Trichome Bar */
        .tri-card { background:#1a1a2e; border-radius:14px; padding:14px; margin-bottom:12px; }
        .tri-legend { display:flex; justify-content:center; gap:20px; margin-bottom:12px; font-size:0.75rem; }
        .tri-legend span { display:flex; align-items:center; gap:6px; }
        .tri-dot { width:10px; height:10px; border-radius:50%; }
        .tri-row { display:flex; align-items:center; gap:8px; margin:6px 0; }
        .tri-label { font-size:0.75rem; width:55px; font-weight:600; }
        .tri-bar { flex:1; height:20px; background:#222; border-radius:6px; overflow:hidden; }
        .tri-fill { height:100%; border-radius:6px; transition:width 1.2s ease; }
        .tri-fill.c { background:linear-gradient(90deg,#555,#888); }
        .tri-fill.m { background:linear-gradient(90deg,#ddd,#fff); }
        .tri-fill.a { background:linear-gradient(90deg,#92400e,#d97706); }
        .tri-val { font-size:0.85rem; font-weight:700; width:38px; text-align:right; }

        /* Stage */
        .stage-row { display:flex; justify-content:center; gap:8px; margin-bottom:12px; flex-wrap:wrap; }
        .stage { padding:6px 14px; border-radius:9999px; font-size:0.75rem; font-weight:700;
                 border:2px solid #333; color:#555; transition:all 0.5s; }
        .stage.active { border-width:2px; }
        .stage.early { color:#3b82f6; }
        .stage.early.active { background:rgba(59,130,246,0.15); border-color:#3b82f6; }
        .stage.peak { color:#22c55e; }
        .stage.peak.active { background:rgba(34,197,94,0.15); border-color:#22c55e; }
        .stage.late { color:#f97316; }
        .stage.late.active { background:rgba(249,115,22,0.15); border-color:#f97316; }
        .stage.overripe { color:#ef4444; }
        .stage.overripe.active { background:rgba(239,68,68,0.15); border-color:#ef4444; }

        /* Cards */
        .grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:12px; }
        .card { background:#1a1a2e; border-radius:12px; padding:12px; text-align:center; }
        .card .lbl { font-size:0.6rem; color:#888; text-transform:uppercase; letter-spacing:0.08em; margin-bottom:4px; }
        .card .val { font-size:1.3rem; font-weight:700; }
        .card .unit { font-size:0.6rem; color:#666; }

        /* Gauges */
        .gauge-card { background:#1a1a2e; border-radius:14px; padding:14px; margin-bottom:12px; }
        .gauge-row { display:flex; align-items:center; gap:10px; margin:6px 0; }
        .gauge-lbl { font-size:0.7rem; width:32px; font-weight:700; }
        .gauge-bar { flex:1; height:10px; background:#2a2a2a; border-radius:5px; overflow:hidden; }
        .gauge-fill { height:100%; border-radius:5px; transition:width 1s ease; }
        .gauge-fill.t { background:linear-gradient(90deg,#7c3aed,#a78bfa); }
        .gauge-fill.c { background:linear-gradient(90deg,#0891b2,#22d3ee); }
        .gauge-num { font-size:0.8rem; font-weight:700; width:45px; text-align:right; }

        /* Recommendations */
        .rec-card { background:#1a1a2e; border-radius:14px; padding:14px; margin-bottom:12px; }
        .rec-card h3 { margin:0 0 10px; font-size:0.85rem; color:var(--gold); }
        .rec-item { background:#0f0f1a; border-radius:8px; padding:8px 12px; margin:4px 0;
                     font-size:0.8rem; display:flex; align-items:center; gap:8px; }

        /* Stress */
        .stress-card { background:rgba(239,68,68,0.08); border:1px solid rgba(239,68,68,0.3);
                       border-radius:12px; padding:12px; margin-bottom:12px; display:none; }
        .stress-card.show { display:block; }
        .stress-card .lbl { font-size:0.7rem; color:var(--red); font-weight:700; margin-bottom:4px; }
        .stress-card .val { font-size:0.85rem; color:var(--red); }

        /* Capture Button */
        .cap-btn { width:100%; padding:16px; background:var(--gold); color:#0f0f1a; border:none;
                   border-radius:14px; font-size:1.1rem; font-weight:700; cursor:pointer;
                   margin-bottom:12px; transition:all 0.3s; }
        .cap-btn:hover { background:#fcd34d; transform:scale(1.01); }
        .cap-btn:disabled { background:#444; color:#888; cursor:not-allowed; transform:none; }

        /* History */
        .hist-item { background:#1a1a2e; border-radius:10px; padding:12px; margin:6px 0;
                     display:flex; justify-content:space-between; align-items:center; }
        .hist-item .date { font-size:0.7rem; color:#888; }
        .hist-item .stage { padding:3px 10px; border-radius:9999px; font-size:0.7rem; font-weight:700; }
        .hist-item .m { background:#fff; color:#333; }
        .hist-item .a { background:#d97706; color:#fff; }
        .hist-item .thc { color:#a78bfa; font-size:0.75rem; font-weight:700; }

        /* Info */
        .info-card { background:#1a1a2e; border-radius:14px; padding:14px; margin-bottom:12px; }
        .info-card h3 { margin:0 0 8px; font-size:0.9rem; color:var(--teal); }
        .info-card p { margin:0 0 6px; font-size:0.82rem; color:#aaa; line-height:1.5; }
        .info-card ul { margin:0; padding-left:16px; font-size:0.82rem; color:#aaa; line-height:1.8; }

        /* Footer */
        .footer { text-align:center; padding:10px; font-size:0.7rem; color:#555; }

        /* Conf */
        .conf { text-align:center; font-size:0.7rem; color:#666; margin-top:8px; }
        .conf span { color:var(--teal); font-weight:700; }
    </style>
</head>
<body>
    <!-- Header -->
    <div class="header">
        <h1>🔬 Trichom-Scanner</h1>
        <p>Halte die Kamera nah an die Bud-Trichome</p>
    </div>

    <!-- Tabs -->
    <div class="tabs">
        <button class="tab active" onclick="switchTab('scan')">📸 Scanner</button>
        <button class="tab" onclick="switchTab('hist')">📈 Verlauf</button>
        <button class="tab" onclick="switchTab('info')">📖 Info</button>
    </div>

    <!-- SCANNER TAB -->
    <div id="scan-tab" class="content active">
        <!-- Camera -->
        <div class="cam-wrap">
            <video id="video" autoplay playsinline style="display:none;"></video>
            <canvas id="canvas" style="display:none;"></canvas>
            <div class="cam-overlay" id="overlay" onclick="startCam()">
                <div class="icon">📸</div>
                <p>Tippen zum Starten</p>
                <p class="sub">Makro-Modus empfohlen</p>
            </div>
        </div>

        <div class="warn" id="warn">⚠️ Bild unscharf – Ergebnis unsicher</div>

        <button class="cap-btn" id="capBtn" onclick="capture()" disabled>🔍 Analyse starten</button>

        <!-- Results -->
        <div id="results" style="display:none;">
            <!-- Stage -->
            <div class="stage-row">
                <div class="stage early" id="sEarly">🔵 Early</div>
                <div class="stage peak" id="sPeak">🟢 Peak</div>
                <div class="stage late" id="sLate">🟠 Late</div>
                <div class="stage overripe" id="sOverripe">🔴 Overripe</div>
            </div>

            <!-- Trichome Bar -->
            <div class="tri-card">
                <div class="tri-legend">
                    <span><div class="tri-dot" style="background:#888"></div>⬜ Klar</span>
                    <span><div class="tri-dot" style="background:#fff;border:1px solid #ccc"></div>🥛 Milky</span>
                    <span><div class="tri-dot" style="background:#d97706"></div>🟤 Amber</span>
                </div>
                <div class="tri-row">
                    <span class="tri-label" style="color:#888">⬜</span>
                    <div class="tri-bar"><div class="tri-fill c" id="cBar" style="width:0%"></div></div>
                    <span class="tri-val" id="cVal">0%</span>
                </div>
                <div class="tri-row">
                    <span class="tri-label" style="color:#fff">🥛</span>
                    <div class="tri-bar"><div class="tri-fill m" id="mBar" style="width:0%"></div></div>
                    <span class="tri-val" id="mVal">0%</span>
                </div>
                <div class="tri-row">
                    <span class="tri-label" style="color:#d97706">🟤</span>
                    <div class="tri-bar"><div class="tri-fill a" id="aBar" style="width:0%"></div></div>
                    <span class="tri-val" id="aVal">0%</span>
                </div>
            </div>

            <!-- THC/CBD -->
            <div class="gauge-card">
                <div class="gauge-row">
                    <span class="gauge-lbl" style="color:#a78bfa">THC</span>
                    <div class="gauge-bar"><div class="gauge-fill t" id="thcBar" style="width:0%"></div></div>
                    <span class="gauge-num" id="thcNum">0%</span>
                </div>
                <div class="gauge-row">
                    <span class="gauge-lbl" style="color:#22d3ee">CBD</span>
                    <div class="gauge-bar"><div class="gauge-fill c" id="cbdBar" style="width:0%"></div></div>
                    <span class="gauge-num" id="cbdNum">0%</span>
                </div>
            </div>

            <!-- Other Values -->
            <div class="grid">
                <div class="card">
                    <div class="lbl">Bud-Entwicklung</div>
                    <div class="val" id="budVal" style="color:var(--teal)">—</div>
                    <div class="unit">%</div>
                </div>
                <div class="card">
                    <div class="lbl">Harz</div>
                    <div class="val" id="resinVal" style="color:var(--gold)">—</div>
                    <div class="unit">Produktion</div>
                </div>
                <div class="card">
                    <div class="lbl">Terpene</div>
                    <div class="val" id="terpVal" style="font-size:1.0rem">—</div>
                    <div class="unit">Profil</div>
                </div>
                <div class="card">
                    <div class="lbl">Pistillen</div>
                    <div class="val" id="pistilVal" style="font-size:1.0rem">—</div>
                    <div class="unit">Farbe</div>
                </div>
            </div>

            <!-- Stress -->
            <div class="stress-card" id="stressCard">
                <div class="lbl">⚠️ Stress erkannt</div>
                <div class="val" id="stressVal">—</div>
            </div>

            <!-- Recommendations -->
            <div class="rec-card" id="recCard">
                <h3>💡 Empfehlungen</h3>
                <div id="recList"></div>
            </div>

            <!-- Confidence -->
            <div class="conf">
                Konfidenz: <span id="confVal">—</span>% | Bild: <span id="qualVal">—</span>%
            </div>
        </div>

        <!-- Notes -->
        <div id="notes" style="margin-top:10px; font-size:0.8rem; color:#666; font-style:italic; display:none;"></div>
    </div>

    <!-- HISTORY TAB -->
    <div id="hist-tab" class="content">
        <div class="header" style="padding:12px 20px; border:none;">
            <h1 style="font-size:1.2rem">📈 Analyse-Verlauf</h1>
        </div>
        <div id="historyList">
            <div style="text-align:center; color:#555; padding:40px;">Noch keine Analysen vorhanden</div>
        </div>
    </div>

    <!-- INFO TAB -->
    <div id="info-tab" class="content">
        <div class="header" style="padding:12px 20px; border:none;">
            <h1 style="font-size:1.2rem">📖 Trichom-Wissen</h1>
        </div>

        <div class="info-card">
            <h3>🔬 Trichome</h3>
            <p>Kleine, harzige Drüsen auf Cannabis-Blüten – produzieren Cannabinoide und Terpene.</p>
        </div>

        <div class="info-card">
            <h3>🎨 Stadien</h3>
            <ul>
                <li><b>⬜ Klar:</b> Unreif – beginnen sich zu entwickeln</li>
                <li><b>🥛 Milky:</b> THC-Peak – berauschende Wirkung</li>
                <li><b>🟤 Amber:</b> CBN – sedierende Wirkung</li>
            </ul>
        </div>

        <div class="info-card">
            <h3>🌿 Ernte-Timing</h3>
            <ul>
                <li><b>60-70% Milky:</b> Peak – maximale High-Effekte 🟢</li>
                <li><b>50-60% Milky:</b> Hybrid – ausgewogen</li>
                <li><b>30-40% Milky:</b> Spät – entspannend 🟠</li>
                <li><b>>50% Amber:</b> Überreif – CBD/CBN 🔴</li>
            </ul>
        </div>

        <div class="info-card">
            <h3>📸 Foto-Tipps</h3>
            <ul>
                <li>Makro-Modus verwenden</li>
                <li>Gleichmäßige Beleuchtung</li>
                <li>Fokus auf die Trichome (nicht Blätter)</li>
                <li>2-5cm Abstand</li>
                <li>Mehrere Fotos von verschiedenen Buds</li>
            </ul>
        </div>
    </div>

    <div class="footer">Queen's Trichom-Scanner V2 –Powered by LLaMA Vision</div>

<script>
// ── Tab Switching ──
function switchTab(tab) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.content').forEach(c => c.classList.remove('active'));
    document.querySelector(`[onclick="switchTab('${tab}')"]`).classList.add('active');
    document.getElementById(`${tab}-tab`).classList.add('active');
}

// ── Camera ──
let video, canvas, ctx, stream;

async function startCam() {
    const overlay = document.getElementById('overlay');
    video = document.getElementById('video');
    canvas = document.getElementById('canvas');
    ctx = canvas.getContext('2d');

    try {
        stream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: "environment", width: { ideal: 1920 }, height: { ideal: 1080 } }
        });
        video.srcObject = stream;
        video.style.display = 'block';
        overlay.style.display = 'none';
        document.getElementById('capBtn').disabled = false;
        await video.play();
        canvas.width = video.videoWidth || 1920;
        canvas.height = video.videoHeight || 1080;
    } catch (e) {
        alert('Kamerafehler: ' + e.message);
    }
}

// ── Capture & Analyze ──
function capture() {
    if (!video || !video.videoWidth) return;

    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    const dataUrl = canvas.toDataURL('image/jpeg', 0.85);
    const base64 = dataUrl.split(',')[1];

    const btn = document.getElementById('capBtn');
    btn.textContent = '⏳ Analysiere...';
    btn.disabled = true;

    fetch('/api/trichome/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_base64: base64 })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            displayResults(data.analysis);
            addToHistory(data.analysis);
        } else {
            alert('Analyse fehlgeschlagen: ' + (data.error || 'Unbekannt'));
        }
    })
    .catch(e => alert('Netzwerkfehler: ' + e.message))
    .finally(() => {
        btn.textContent = '🔍 Erneut analysieren';
        btn.disabled = false;
    });
}

// ── Display Results ──
function displayResults(a) {
    document.getElementById('results').style.display = 'block';
    document.getElementById('warn').classList.toggle('show', (a.image_quality_score || 0) < 50);

    const c = a.clear_percent || 0;
    const m = a.milky_percent || a.milkyly_percent || 0;
    const am = a.amber_percent || 0;

    setTimeout(() => {
        document.getElementById('cBar').style.width = c + '%';
        document.getElementById('cVal').textContent = c + '%';
        document.getElementById('mBar').style.width = m + '%';
        document.getElementById('mVal').textContent = m + '%';
        document.getElementById('aBar').style.width = am + '%';
        document.getElementById('aVal').textContent = am + '%';
    }, 100);

    // Stage
    const stage = a.maturity_stage || 'Early';
    ['Early', 'Peak', 'Late', 'Overripe'].forEach(s => {
        document.getElementById('s' + s).classList.toggle('active', s === stage);
    });

    // THC/CBD
    const thc = parseFloat(a.thc_estimate || '0');
    const cbd = parseFloat(a.cbd_estimate || '0');
    document.getElementById('thcNum').textContent = thc.toFixed(1) + '%';
    document.getElementById('cbdNum').textContent = cbd.toFixed(1) + '%';
    setTimeout(() => {
        document.getElementById('thcBar').style.width = Math.min(100, thc * 2.5) + '%';
        document.getElementById('cbdBar').style.width = Math.min(100, cbd * 5) + '%';
    }, 200);

    // Other
    document.getElementById('budVal').textContent = a.bud_development || '—';
    document.getElementById('resinVal').textContent = a.resin_production || '—';
    document.getElementById('terpVal').textContent = a.terpene_hint || '—';
    document.getElementById('pistilVal').textContent = a.pistil_color || '—';

    // Stress
    const stress = a.stress_indicators || [];
    document.getElementById('stressCard').classList.toggle('show', stress.length > 0);
    document.getElementById('stressVal').textContent = stress.length > 0 ? stress.join(', ') : '—';

    // Recommendations
    const recs = a.recommendations || [];
    document.getElementById('recList').innerHTML = recs.map(r =>
        `<div class="rec-item"><span>💡</span>${r}</div>`
    ).join('');

    // Confidence
    document.getElementById('confVal').textContent = a.confidence || '—';
    document.getElementById('qualVal').textContent = a.image_quality_score || '—';

    // Notes
    const notes = document.getElementById('notes');
    if (a.analysis_notes) {
        notes.style.display = 'block';
        notes.textContent = '📌 ' + a.analysis_notes;
    }

    // Voice feedback
    try {
        const utter = new SpeechSynthesisUtterance(
            `Trichom-Analyse: ${stage}. Milky ${m} Prozent. ${a.harvest_recommendation || ''}`
        );
        utter.lang = 'de-DE';
        speechSynthesis.speak(utter);
    } catch(e) {}
}

// ── History ──
let history = [];

function addToHistory(a) {
    history.unshift({
        time: new Date().toLocaleTimeString('de', { hour: '2-digit', minute: '2-digit' }),
        stage: a.maturity_stage || '?',
        milky: a.milky_percent || 0,
        amber: a.amber_percent || 0,
        thc: a.thc_estimate || '?'
    });
    if (history.length > 10) history.pop();
    renderHistory();
}

function renderHistory() {
    const list = document.getElementById('historyList');
    if (history.length === 0) {
        list.innerHTML = '<div style="text-align:center;color:#555;padding:40px;">Noch keine Analysen</div>';
        return;
    }
    list.innerHTML = history.map(h => `
        <div class="hist-item">
            <div>
                <div class="date">${h.time}</div>
                <div style="font-size:0.8rem;margin-top:2px;">
                    <span style="color:#fff">🥛${h.milky}%</span>
                    <span style="color:#d97706;margin-left:6px">🟤${h.amber}%</span>
                </div>
            </div>
            <div style="text-align:right">
                <div class="stage ${h.stage.toLowerCase()}">${h.stage}</div>
                <div class="thc">THC ${h.thc}</div>
            </div>
        </div>
    `).join('');
}

// Init
renderHistory();
</script>
</body>
</html>"""

@app.get("/")
async def trichome(request: Request):
    return HTMLResponse(HTML_TEMPLATE)


@app.post("/api/trichome/analyze")
async def trichome_analyze(request: Request):
    """Proxy für Trichom-Analyse via Backend."""
    body = await request.json()
    image_base64 = body.get("image_base64")

    if not image_base64:
        return {"success": False, "error": "image_base64 required"}

    # Import und Aufruf des echten Analyzers
    try:
        from trichome_analyzer import handle_trichome_analysis

        class MockUpdate:
            class MockMessage:
                async def reply_text(self, text, **kwargs):
                    pass
            message = MockMessage()

        result = await handle_trichome_analysis(
            update=MockUpdate(),
            context=None,
            image_base64=image_base64,
            plant_age_days=body.get("plant_age_days"),
            light_sensor_data=body.get("light_sensor_data")
        )
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
