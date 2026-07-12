# lightmeter_mini_app.py – Queen's Plant Light & Health Meter V3
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI(title="Queen's Light & Health Meter V3")

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Queen's Light Meter V3</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=VT323&family=Inter:wght@400;600;700&display=swap');
        :root { --teal: #00d4aa; --gold: #f5c242; --red: #ff3366; --bg: #0f0f1a; }
        * { box-sizing: border-box; }
        body { margin:0; background:var(--bg); color:#ddd; font-family:'Inter',sans-serif; overflow:hidden; }
        #container { display:flex; flex-direction:column; height:100vh; }

        /* Header */
        #header { background:linear-gradient(180deg,#0f0f1a,#1a1a2e); padding:8px 12px; display:flex;
                  justify-content:space-between; align-items:center; border-bottom:1px solid #222; flex-shrink:0; }
        #header h1 { margin:0; font-size:1.1rem; color:var(--gold); text-shadow:0 0 10px var(--gold); }
        .hdr-btns { display:flex; gap:4px; }
        .hdr-btn { background:transparent; border:1px solid var(--teal); color:var(--teal);
                   padding:4px 8px; border-radius:9999px; font-size:0.65rem; font-weight:600; cursor:pointer; }
        .hdr-btn.gold { border-color:var(--gold); color:var(--gold); }

        /* Tabs */
        .tabs { display:flex; background:#1a1a2e; flex-shrink:0; }
        .tab { flex:1; padding:8px 6px; text-align:center; font-size:0.7rem; font-weight:600;
               cursor:pointer; color:#666; border:none; background:transparent; border-bottom:2px solid transparent; }
        .tab.active { color:var(--gold); border-bottom-color:var(--gold); }

        .tab-content { display:none; flex:1; overflow:hidden; }
        .tab-content.active { display:flex; flex-direction:column; }

        /* Camera area */
        #cam-wrap { flex:1; position:relative; background:#111; overflow:hidden; min-height:0; }
        video { width:100%; height:100%; object-fit:cover; transform:scaleX(-1); }
        canvas { display:none; }

        /* Scan frame */
        #frame { position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
                 width:150px; height:150px; border:2px solid rgba(0,212,170,0.6); border-radius:14px;
                 box-shadow:0 0 25px rgba(0,212,170,0.25); pointer-events:none; }
        #scanLine { position:absolute; left:8%; right:8%; height:2px;
                    background:linear-gradient(90deg,transparent,var(--teal),transparent);
                    opacity:0.7; animation: scanDown 2.5s ease-in-out infinite; }
        @keyframes scanDown { 0%{top:15%;} 50%{top:82%;} 100%{top:15%;} }

        /* Primary values */
        #primary { position:absolute; top:8%; left:50%; transform:translateX(-50%);
                   display:flex; gap:6px; }
        .pv { background:rgba(15,15,26,0.9); padding:7px 14px; border-radius:12px;
              border:1px solid rgba(0,212,170,0.25); text-align:center; min-width:110px; }
        .pv-lbl { font-size:0.58rem; color:var(--teal); letter-spacing:0.1em; font-weight:600; text-transform:uppercase; display:block; }
        .pv-val { font-size:2.0rem; font-weight:700; color:#fff; line-height:1.1; }
        .pv-val.lux { color:var(--gold); }
        .pv-val.ppfd { color:var(--teal); }
        .pv-unit { font-size:0.55rem; color:#666; }

        /* Score */
        #score { position:absolute; top:8%; right:8px; background:rgba(15,15,26,0.9); padding:7px 10px;
                 border-radius:10px; text-align:center; min-width:80px; border:2px solid var(--teal); }
        #score .lbl { font-size:0.52rem; color:#777; text-transform:uppercase; letter-spacing:0.06em; }
        #score .val { font-size:1.3rem; font-weight:700; color:var(--teal); }

        /* Light type */
        #ltype { position:absolute; top:22%; right:8px; background:rgba(15,15,26,0.85); padding:4px 8px;
                  border-radius:8px; font-size:0.58rem; color:#888; text-align:center; }
        #ltype span { color:var(--gold); font-weight:700; font-size:0.65rem; display:block; }

        /* Secondary */
        #secondary { display:grid; grid-template-columns:repeat(4,1fr); gap:4px; padding:0 6px; margin-bottom:4px; }
        .sv { background:rgba(15,15,26,0.85); padding:4px 6px; border-radius:8px;
              border:1px solid rgba(0,212,170,0.15); }
        .sv-lbl { font-size:0.5rem; color:#888; text-transform:uppercase; letter-spacing:0.05em; font-weight:600; }
        .sv-val { font-size:0.95rem; font-weight:700; color:#fff; }
        .sv-unit { font-size:0.46rem; color:#555; }
        .sv.vib { animation: vib 0.5s ease; }
        @keyframes vib { 0%,100%{transform:translate(0,0)} 25%{transform:translate(0.5px,0.5px)} 75%{transform:translate(-0.5px,-0.5px)} }
        .good { color: var(--teal) !important; }
        .ok { color: var(--gold) !important; }
        .bad { color: var(--red) !important; }

        /* Advanced */
        #advanced { display:grid; grid-template-columns:repeat(3,1fr); gap:4px; padding:0 6px; }
        .av { background:rgba(30,25,15,0.85); padding:4px 6px; border-radius:8px;
              border:1px solid rgba(245,194,66,0.2); }
        .av-lbl { font-size:0.48rem; color:#c4a055; text-transform:uppercase; letter-spacing:0.05em; font-weight:600; }
        .av-val { font-size:0.9rem; font-weight:700; color:var(--gold); }

        /* Terminal */
        #terminal { height:130px; background:rgba(15,15,26,0.96); border-top:2px solid var(--teal);
                    font-family:'VT323',monospace; font-size:0.95rem; line-height:1.35; color:var(--teal);
                    overflow-y:auto; padding:8px 14px; flex-shrink:0; }
        .log { margin:1px 0; opacity:0.8; }
        .log.suc { color:#00d4aa; }
        .log.warn { color:#f5c242; }
        .log.err { color:#ff3366; }

        /* Start overlay */
        #start { position:absolute; inset:0; background:rgba(15,15,26,0.95); display:flex;
                 flex-direction:column; align-items:center; justify-content:center; z-index:50; cursor:pointer; }
        #start .pulse { width:65px; height:65px; border-radius:50%; border:3px solid var(--teal);
                        display:flex; align-items:center; justify-content:center; font-size:2rem;
                        box-shadow:0 0 30px var(--teal); animation:pr 1.8s ease-in-out infinite; }
        #start p { color:var(--teal); margin-top:12px; font-size:0.85rem; }
        @keyframes pr { 0%,100%{box-shadow:0 0 20px var(--teal);} 50%{box-shadow:0 0 50px var(--teal),0 0 80px rgba(0,212,170,0.3);} }

        /* Cal modal */
        #cal { display:none; position:absolute; inset:0; background:rgba(0,0,0,0.93); z-index:100;
               flex-direction:column; align-items:center; justify-content:center; padding:20px; }
        #cal.show { display:flex; }
        .cal-card { background:#1a1a2e; border:2px solid var(--gold); border-radius:16px;
                    padding:20px; max-width:300px; width:100%; }
        .cal-card h2 { color:var(--gold); margin:0 0 6px; font-size:1.1rem; }
        .cal-card p { color:#aaa; margin:0 0 12px; font-size:0.78rem; }
        .cal-input { width:100%; background:#0f0f1a; border:2px solid #333; border-radius:10px;
                     color:#fff; font-size:1.2rem; padding:10px; text-align:center;
                     font-weight:700; outline:none; margin-bottom:10px; }
        .cal-input:focus { border-color:var(--gold); }
        .cal-btns { display:flex; gap:8px; }
        .cal-btn { flex:1; padding:10px; border-radius:10px; font-weight:700; font-size:0.82rem; cursor:pointer; border:none; }
        .cal-btn.save { background:var(--gold); color:#0f0f1a; }
        .cal-btn.cncl { background:transparent; border:2px solid #444; color:#888; }
        .cal-factor { color:var(--teal); font-size:0.72rem; margin-top:8px; text-align:center; }

        /* Particles */
        #parts { position:absolute; inset:0; pointer-events:none; }

        /* Ring */
        .ring { position:absolute; border:3px solid var(--gold); border-radius:50%;
                width:90px; height:90px; top:40%; left:40%; opacity:0; pointer-events:none; }
        .ring.anim { animation: rp 1.0s ease-out forwards; }
        @keyframes rp { 0%{transform:scale(0.7);opacity:1;} 100%{transform:scale(2.5);opacity:0;} }

        /* Trichome Tab */
        #tri-wrap { flex:1; overflow-y:auto; padding:16px; background:var(--bg); }
        .tri-hdr { text-align:center; margin-bottom:16px; }
        .tri-hdr h2 { color:var(--gold); margin:0 0 4px; font-size:1.3rem; }
        .tri-hdr p { color:#888; font-size:0.8rem; margin:0; }

        .tri-cam { background:#111; border-radius:14px; overflow:hidden; aspect-ratio:4/3;
                   position:relative; border:2px solid #333; margin-bottom:12px; }
        .tri-cam video, .tri-cam canvas { width:100%; height:100%; object-fit:cover; }
        .tri-overlay { position:absolute; inset:0; background:rgba(0,0,0,0.7); display:flex;
                       flex-direction:column; align-items:center; justify-content:center; gap:8px; cursor:pointer; }
        .tri-overlay .icon { font-size:3rem; }
        .tri-overlay p { color:var(--teal); margin:0; font-size:0.9rem; }
        .tri-overlay .sub { color:#666; font-size:0.72rem; margin:0; }

        .tri-btn { width:100%; padding:14px; background:var(--gold); color:#0f0f1a; border:none;
                   border-radius:12px; font-size:1.0rem; font-weight:700; cursor:pointer; margin-bottom:10px; }
        .tri-btn:disabled { background:#444; color:#888; cursor:not-allowed; }

        .tri-results { display:none; }
        .tri-results.show { display:block; }

        .tri-stage { display:flex; justify-content:center; gap:6px; margin-bottom:10px; flex-wrap:wrap; }
        .tri-stg { padding:5px 12px; border-radius:9999px; font-size:0.7rem; font-weight:700;
                   border:2px solid #333; color:#555; }
        .tri-stg.active { border-width:2px; }
        .tri-stg.early.active { color:#3b82f6; border-color:#3b82f6; background:rgba(59,130,246,0.15); }
        .tri-stg.peak.active { color:#22c55e; border-color:#22c55e; background:rgba(34,197,94,0.15); }
        .tri-stg.late.active { color:#f97316; border-color:#f97316; background:rgba(249,115,22,0.15); }
        .tri-stg.overripe.active { color:#ef4444; border-color:#ef4444; background:rgba(239,68,68,0.15); }

        .tri-card { background:#1a1a2e; border-radius:12px; padding:12px; margin-bottom:10px; }
        .tri-row { display:flex; align-items:center; gap:6px; margin:4px 0; }
        .tri-lbl { font-size:0.7rem; width:50px; font-weight:600; }
        .tri-bar { flex:1; height:16px; background:#222; border-radius:4px; overflow:hidden; }
        .tri-fill { height:100%; border-radius:4px; transition:width 1s; }
        .tri-fill.c { background:linear-gradient(90deg,#555,#888); }
        .tri-fill.m { background:linear-gradient(90deg,#ddd,#fff); }
        .tri-fill.a { background:linear-gradient(90deg,#92400e,#d97706); }
        .tri-pct { font-size:0.8rem; font-weight:700; width:35px; text-align:right; }

        .tri-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:10px; }
        .tri-card-val { background:#0f0f1a; border-radius:10px; padding:10px; text-align:center; }
        .tri-card-val .lbl { font-size:0.55rem; color:#888; text-transform:uppercase; letter-spacing:0.06em; }
        .tri-card-val .val { font-size:1.2rem; font-weight:700; }
    </style>
</head>
<body>
<div id="container">
    <!-- Header -->
    <div id="header">
        <h1>🌿 Light Meter V3</h1>
        <div class="hdr-btns">
            <button class="hdr-btn gold" onclick="openCal()">⚖️</button>
            <button class="hdr-btn" onclick="startSingle()">📸</button>
            <button class="hdr-btn" onclick="startMulti()">🌿6×</button>
            <button class="hdr-btn" onclick="saveBrain()">💾</button>
            <button class="hdr-btn" onclick="toggleAdv()">🔬</button>
        </div>
    </div>

    <!-- Tabs -->
    <div class="tabs">
        <button class="tab active" onclick="switchTab('light')">💡 Light</button>
        <button class="tab" onclick="switchTab('tri')">🔬 Trichome</button>
    </div>

    <!-- LIGHT TAB -->
    <div id="light-tab" class="tab-content active">
        <div id="cam-wrap">
            <div id="start" onclick="startCam()">
                <div class="pulse">🌿</div>
                <p>Tippen zum Starten</p>
            </div>
            <video id="video" autoplay playsinline></video>
            <canvas id="canvas"></canvas>
            <div id="frame"></div>
            <div id="scanLine"></div>
            <div id="parts"></div>

            <div id="primary">
                <div class="pv">
                    <span class="pv-lbl">🌞 Lux</span>
                    <div class="pv-val lux" id="luxVal">—</div>
                    <div class="pv-unit">Beleuchtung</div>
                </div>
                <div class="pv">
                    <span class="pv-lbl">⚡ PPFD</span>
                    <div class="pv-val ppfd" id="ppfdVal">—</div>
                    <div class="pv-unit">µmol/m²/s</div>
                </div>
            </div>

            <div id="score">
                <div class="lbl">Score</div>
                <div class="val" id="scoreVal">—</div>
            </div>

            <div id="ltype">Licht:<span id="ltypeVal">—</span></div>

            <div id="secondary">
                <div class="sv"><div class="sv-lbl">🌱 Chloro</div><div class="sv-val" id="chloroVal">—</div><div class="sv-unit">Index</div></div>
                <div class="sv"><div class="sv-lbl">💧 VPD</div><div class="sv-val" id="vpdVal">—</div><div class="sv-unit">kPa</div></div>
                <div class="sv"><div class="sv-lbl">☀️ DLI</div><div class="sv-val" id="dliVal">—</div><div class="sv-unit">mol/m²/d</div></div>
                <div class="sv"><div class="sv-lbl">🌡°C</div><div class="sv-val" id="tempVal">—</div><div class="sv-unit">Blatt</div></div>
                <div class="sv"><div class="sv-lbl">💪 Vigor</div><div class="sv-val" id="vigorVal">—</div><div class="sv-unit">Vitalität</div></div>
                <div class="sv"><div class="sv-lbl">🌡 Luft</div><div class="sv-val" id="rhVal">55</div><div class="sv-unit">% geschätzt</div></div>
                <div class="sv"><div class="sv-lbl">🎯 DLI-Ziel</div><div class="sv-val" id="dliTgt">—</div><div class="sv-unit">mol/m²/d</div></div>
                <div class="sv"><div class="sv-lbl">📐 B/R</div><div class="sv-val" id="brVal">—</div><div class="sv-unit">Spektrum</div></div>
            </div>

            <div id="advanced" style="display:none;">
                <div class="av"><div class="av-lbl">🛰️ NDVI</div><div class="av-val" id="ndviVal">—</div></div>
                <div class="av"><div class="av-lbl">🔋 CFI</div><div class="av-val" id="cfiVal">—</div></div>
                <div class="av"><div class="av-lbl">🚪 Gs</div><div class="av-val" id="gsVal">—</div></div>
                <div class="av"><div class="av-lbl">💧 Transp.</div><div class="av-val" id="transpVal">—</div></div>
                <div class="av"><div class="av-lbl">⚠️ Stress</div><div class="av-val" id="stressVal">—</div></div>
                <div class="av"><div class="av-lbl">📈 Wachstum</div><div class="av-val" id="growthVal">—</div></div>
            </div>

            <!-- Cal Modal -->
            <div id="cal">
                <div class="cal-card">
                    <h2>⚖️ Kalibrierung</h2>
                    <p>Referenz-Luxmeter neben Handy halten und echten Wert eingeben.</p>
                    <input type="number" class="cal-input" id="calInp" placeholder="z.B. 850" min="0">
                    <div class="cal-btns">
                        <button class="cal-btn cncl" onclick="closeCal()">Abbrechen</button>
                        <button class="cal-btn save" onclick="saveCal()">Kalibrieren</button>
                    </div>
                    <div class="cal-factor" id="calFact">Faktor: 1.00</div>
                </div>
            </div>
        </div>

        <div id="terminal">
            <div style="margin-bottom:4px;color:#f5c242;font-size:1.0rem;">🧬 QUEEN THINKING TERMINAL V3</div>
            <div id="logs"></div>
        </div>
    </div>

    <!-- TRICHOME TAB -->
    <div id="tri-tab" class="tab-content">
        <div id="tri-wrap">
            <div class="tri-hdr">
                <h2>🔬 Trichom-Scanner</h2>
                <p>Tippe auf die Kamera → Fokus auf Trichome → Analyse</p>
            </div>

            <div class="tri-cam">
                <video id="triVideo" autoplay playsinline style="display:none;"></video>
                <canvas id="triCanvas" style="display:none;"></canvas>
                <div class="tri-overlay" id="triOverlay" onclick="startTriCam()">
                    <div class="icon">📸</div>
                    <p>Tippen zum Starten</p>
                    <p class="sub">Makro-Modus empfohlen</p>
                </div>
            </div>

            <button class="tri-btn" id="triBtn" onclick="captureTri()" disabled>🔍 Analyse starten</button>

            <div class="tri-results" id="triResults">
                <div class="tri-stage">
                    <div class="tri-stg early" id="tEarly">🔵 Early</div>
                    <div class="tri-stg peak" id="tPeak">🟢 Peak</div>
                    <div class="tri-stg late" id="tLate">🟠 Late</div>
                    <div class="tri-stg overripe" id="tOverripe">🔴 Overripe</div>
                </div>

                <div class="tri-card">
                    <div class="tri-row">
                        <span class="tri-lbl" style="color:#888">⬜</span>
                        <div class="tri-bar"><div class="tri-fill c" id="tClear" style="width:0%"></div></div>
                        <span class="tri-pct" id="tClearV">0%</span>
                    </div>
                    <div class="tri-row">
                        <span class="tri-lbl" style="color:#fff">🥛</span>
                        <div class="tri-bar"><div class="tri-fill m" id="tMilk" style="width:0%"></div></div>
                        <span class="tri-pct" id="tMilkV">0%</span>
                    </div>
                    <div class="tri-row">
                        <span class="tri-lbl" style="color:#d97706">🟤</span>
                        <div class="tri-bar"><div class="tri-fill a" id="tAmber" style="width:0%"></div></div>
                        <span class="tri-pct" id="tAmberV">0%</span>
                    </div>
                </div>

                <div class="tri-grid">
                    <div class="tri-card-val">
                        <div class="lbl">THC</div>
                        <div class="val" style="color:#a78bfa" id="tThc">—</div>
                        <div class="lbl">%</div>
                    </div>
                    <div class="tri-card-val">
                        <div class="lbl">CBD</div>
                        <div class="val" style="color:#22d3ee" id="tCbd">—</div>
                        <div class="lbl">%</div>
                    </div>
                    <div class="tri-card-val">
                        <div class="lbl">Bud</div>
                        <div class="val" style="color:var(--teal)" id="tBud">—</div>
                        <div class="lbl">%</div>
                    </div>
                    <div class="tri-card-val">
                        <div class="lbl">Harz</div>
                        <div class="val" style="color:var(--gold)" id="tResin">—</div>
                        <div class="lbl">Prod.</div>
                    </div>
                </div>

                <div class="tri-card">
                    <div style="font-size:0.75rem;color:#888;margin-bottom:8px;">💡 Empfehlungen</div>
                    <div id="tRecs"></div>
                </div>

                <div style="text-align:center;font-size:0.7rem;color:#666;">
                    Konfidenz: <span id="tConf" style="color:var(--teal);font-weight:700">—</span>% |
                    Bild: <span id="tQual" style="color:var(--teal);font-weight:700">—</span>%
                </div>
            </div>
        </div>
    </div>
</div>

<script>
// ══════════════ LIGHT METER LOGIC ══════════════
let video, canvas, ctx, stream;
let calFactor = 1.0, rh = 55, advOn = false;
const logs = document.getElementById('logs');
let lastPPFD = 0;

function log(t, type='info') {
    const e = document.createElement('div');
    e.className = 'log';
    e.innerHTML = `→ ${t}`;
    if (type === 'suc') e.style.color = '#00d4aa';
    if (type === 'warn') e.style.color = '#f5c242';
    if (type === 'err') e.style.color = '#ff3366';
    logs.appendChild(e);
    while (logs.children.length > 8) logs.removeChild(logs.children[0]);
    logs.scrollTop = logs.scrollHeight;
}

async function startCam() {
    document.getElementById('start').style.display = 'none';
    video = document.getElementById('video');
    canvas = document.getElementById('canvas');
    ctx = canvas.getContext('2d');
    const sf = localStorage.getItem('luxCal');
    if (sf) { calFactor = parseFloat(sf); log(`Kalibrierung: ${calFactor.toFixed(3)}`, 'warn'); }

    try {
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: "environment", width: { ideal: 1280 } }
            });
        } catch(e) {
            stream = await navigator.mediaDevices.getUserMedia({ video: true });
        }
        video.srcObject = stream;
        await video.play();
        canvas.width = video.videoWidth || 1280;
        canvas.height = video.videoHeight || 720;
        log(`✅ Kamera ${canvas.width}×${canvas.height}`, 'suc');
        createParts();
        loop();
    } catch(e) { log('Kamerafehler: ' + e.message, 'err'); }
}

// Calculations
function detLight(r,g,b) {
    const tot = r+g+b; if (tot===0) return {f:0.0188,l:'—',s:0};
    const rR=r/tot,gR=g/tot,bR=b/tot;
    if (rR>0.45&&gR>0.35&&bR<0.12) return {f:0.016,l:'💡Glühbirne',s:15};
    if (rR>0.35&&gR>0.38&&bR<0.15) return {f:0.017,l:'💡Leuchtstoff',s:18};
    if (rR<0.30&&gR>0.35&&bR>0.15) return {f:0.020,l:'☀️Tageslicht',s:25};
    if (rR>0.42&&bR>0.22) return {f:0.014,l:'🌈Grow-LED',s:20};
    if (rR>0.40&&gR>0.40&&bR<0.12) return {f:0.020,l:'☀️Sonnenlicht',s:25};
    return {f:0.0188,l:'💡LED',s:22};
}

function chl(r,g,b) {
    const tot=r+g+b; if(tot===0)return 0;
    const gD=(g-(r+b)/2)/(g+(r+b)/2+1);
    return Math.round(Math.max(0,Math.min(100,(gD+1)*50)));
}

function leafTemp(lux,a=22){return Math.round((a+Math.max(0,(lux-5000)/10000))*10)/10;}

function vpd(t,rh=55){const s=0.61078*Math.exp(17.27*t/(t+237.3));return Math.round((s-s*(rh/100))*10)/10;}

function dli(ppfd,h=14){return Math.round(ppfd*h*3600/1e6*10)/10;}

function vigor(ppfd,ch,s){const p=ppfd>=650?40:ppfd>=400?35:ppfd>=200?25:ppfd>=100?15:ppfd>=50?8:0;
  const c=ch>=75?35:ch>=55?28:ch>=40?20:ch>=25?12:5;
  return Math.min(100,p+c+s);}

function ndvi(r,g,b){const tot=r+g+b;if(tot===0)return 0;
  const gD=(g-(r*0.6))/(g+(r*0.6)+1);
  return Math.round(Math.max(0,Math.min(1,(gD+1)*0.4))*100)/100;}

function cfi(r,g,b){return Math.round((g/(r+b+1))*100)/100;}

function gs(ppfd,vpd,temp){const lF=Math.min(1,ppfd/300);
  const vF=vpd<0.4?0.7:vpd>2.0?0.2:vpd>1.5?0.5:1.0;
  const tF=temp<15?0.3:temp<20?0.6:temp>35?0.2:temp>30?0.6:1.0;
  return Math.round(0.15*lF*vF*tF*1000)/1000;}

function transp(gs,vpd){return Math.round(gs*vpd*0.5*100)/100;}

function stress(ch,vpd,temp,ppfd){let s=0;
  if(vpd<0.3)s+=10;else if(vpd>2.5)s+=35;else if(vpd>2.0)s+=25;else if(vpd>1.6)s+=15;
  if(temp<10)s+=35;else if(temp<15)s+=20;else if(temp<20)s+=8;else if(temp>38)s+=40;else if(temp>33)s+=25;else if(temp>30)s+=12;
  if(ch<20)s+=30;else if(ch<35)s+=20;else if(ch<50)s+=10;
  if(ppfd<30)s+=20;else if(ppfd<100)s+=10;else if(ppfd>1500)s+=15;
  return Math.min(100,Math.max(0,s));}

function growth(dli,v,temp){const tF=temp<15?0.1:temp<20?0.5:temp>33?0.3:temp>30?0.7:1.0;
  return Math.round(Math.max(0,2*(Math.min(1,dli/40))*(v/100)*tF)*10)/10;}

function score(ppfd,ch,vpd,sI){let sc=0;
  if(ppfd>=650)sc+=25;else if(ppfd>=400)sc+=20;else if(ppfd>=200)sc+=12;else if(ppfd>=50)sc+=5;
  if(ch>=70)sc+=25;else if(ch>=50)sc+=18;else if(ch>=35)sc+=10;else sc+=3;
  if(vpd>=0.4&&vpd<=1.6)sc+=20;else if(vpd>=0.2&&vpd<=2.0)sc+=12;else sc+=5;
  sc-=Math.round(sI*0.25);
  return Math.min(100,Math.max(0,sc));}

// Analysis loop
function loop(){setInterval(()=>{
  if(!video||!video.videoWidth)return;
  ctx.drawImage(video,0,0,canvas.width,canvas.height);
  const d=ctx.getImageData(0,0,canvas.width,canvas.height).data;
  let r=0,g=0,b=0,p=0;
  const w=canvas.width,h=canvas.height,mx=Math.floor(w*0.2),my=Math.floor(h*0.2);
  for(let y=my;y<h-my;y++)for(let x=mx;x<w-mx;x++){const i=(y*w+x)*4;r+=d[i];g+=d[i+1];b+=d[i+2];p++;}
  const aR=r/p,aG=g/p,aB=b/p;
  const lum=0.299*aR+0.587*aG+0.114*aB;
  const nB=lum/255;
  let lux=(nB<0.05?nB*2000:nB<0.15?100+(nB-0.05)*1e4:nB<0.35?1000+(nB-0.15)*25e3:nB<0.65?15e3+(nB-0.35)*185e3:80e3+(nB-0.65)*2e5)*calFactor;
  lux=Math.round(lux);
  const lD=detLight(aR,aG,aB);
  const ppfd=Math.round(lux*lD.f);
  const ch=chl(aR,aG,aB);
  const lt=leafTemp(lux);
  const vp=vpd(lt,rh);
  const di=dli(ppfd);
  const vi=vigor(ppfd,ch,lD.s);
  const br=(aR/(aB+1)).toFixed(2);
  const nd=ndvi(aR,aG,aB);
  const cf=cfi(aR,aG,aB);
  const gsVal=gs(ppfd,vp,lt);
  const tr=transp(gsVal,vp);
  const si=stress(ch,vp,lt,ppfd);
  const gr=growth(di,vi,lt);
  const sc=score(ppfd,ch,vp,si);

  // UI
  document.getElementById('luxVal').textContent=lux>=1e3?(lux/1e3).toFixed(1)+'k':lux;
  document.getElementById('ppfdVal').textContent=ppfd;
  document.getElementById('scoreVal').textContent=sc;
  document.getElementById('scoreVal').style.color=sc>=70?'var(--teal)':sc>=40?'var(--gold)':'var(--red)';
  document.getElementById('ltypeVal').textContent=lD.l;
  document.getElementById('chloroVal').textContent=ch;
  document.getElementById('vpdVal').textContent=vp;
  document.getElementById('dliVal').textContent=di;
  document.getElementById('tempVal').textContent=lt;
  document.getElementById('vigorVal').textContent=vi;
  document.getElementById('dliTgt').textContent=ppfd<50?3:ppfd<200?8:ppfd<400?15:ppfd<650?25:40;
  document.getElementById('brVal').textContent=br;

  // Colors
  document.getElementById('chloroVal').className='sv-val '+(ch>=70?'good':ch>=50?'ok':'bad');
  document.getElementById('vpdVal').className='sv-val '+(vp>=0.4&&vp<=1.6?'good':vp>2?'bad':'ok');
  document.getElementById('tempVal').className='sv-val '+(lt>=20&&lt<=28?'good':lt>33||lt<15?'bad':'ok');

  if(advOn){
    document.getElementById('ndviVal').textContent=nd;
    document.getElementById('cfiVal').textContent=cf;
    document.getElementById('gsVal').textContent=gsVal.toFixed(3);
    document.getElementById('transpVal').textContent=tr.toFixed(2);
    document.getElementById('stressVal').textContent=si+'%';
    document.getElementById('growthVal').textContent=gr.toFixed(1);
    document.getElementById('ndviVal').className='av-val '+(nd>=0.6?'good':nd>=0.3?'ok':'bad');
    document.getElementById('stressVal').className='av-val '+(si<=20?'good':si<=50?'ok':'bad');
    document.getElementById('growthVal').className='av-val '+(gr>=1.5?'good':gr>=0.5?'ok':'bad');
  }

  if(Math.abs(ppfd-lastPPFD)>25){
    log(`Lux:${lux>=1e3?(lux/1e3).toFixed(1)+'k':lux} PPFD:${ppfd} DLI:${di} Chl:${ch} Vigor:${vi}% | NDVI:${nd} SI:${si}% | +${gr}mm/d`,sc>=60?'suc':'warn');
    lastPPFD=ppfd;
    if(ppfd>=650&&lastPPFD<650){triggerRing();try{speechSynthesis.speak(new SpeechSynthesisUtterance(`Optimal. PPFD ${ppfd}.`));}catch(e){}}
  }
},500);}

// Actions
function toggleAdv(){advOn=!advOn;document.getElementById('advanced').style.display=advOn?'grid':'none';log(advOn?'🔬 Erweitert an':'🔬 Erweitert aus','info');}
function triggerRing(){const r=document.createElement('div');r.className='ring anim';document.getElementById('cam-wrap').appendChild(r);setTimeout(()=>r.remove(),1200);
  try{const a=new(window.AudioContext||window.webkitAudioContext)();const o=a.createOscillator();o.type='sine';o.frequency.setValueAtTime(880,a.currentTime);o.connect(a.destination);o.start();setTimeout(()=>o.stop(),80);}catch(e){}}
function startSingle(){log('📸 Single-Scan – halte ruhig über das Blatt','suc');triggerRing();}
async function startMulti(){log('🚀 Multi-Leaf (6×) gestartet','suc');}
function openCal(){document.getElementById('cal').classList.add('show');document.getElementById('calFact').textContent='Faktor: '+calFactor.toFixed(3);}
function closeCal(){document.getElementById('cal').classList.remove('show');}
function saveCal(){const inp=parseFloat(document.getElementById('calInp').value);if(!inp||inp<=0){alert('Gültigen Lux-Wert!');return;}const cur=parseInt(document.getElementById('luxVal').textContent)||0;if(cur<=0){alert('Kein Kamera-Wert!');return;}calFactor=inp/cur;localStorage.setItem('luxCal',calFactor.toString());document.getElementById('calFact').textContent='Neuer Faktor: '+calFactor.toFixed(3);log('✅ Kalibriert! Faktor: '+calFactor.toFixed(3),'suc');setTimeout(closeCal,1000);}
async function saveBrain(){const d={timestamp:new Date().toISOString(),lux:parseInt(document.getElementById('luxVal').textContent)||0,ppfd:parseInt(document.getElementById('ppfdVal').textContent)||0,chloroIndex:parseInt(document.getElementById('chloroVal').textContent)||0,vpd:parseFloat(document.getElementById('vpdVal').textContent)||0,dli:parseFloat(document.getElementById('dliVal').textContent)||0,vigor:parseInt(document.getElementById('vigorVal').textContent)||0,leafTemp:parseFloat(document.getElementById('tempVal').textContent)||0};try{const r=await fetch('/api/save_measurement',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});if(r.ok){log('💾 Brain-Sync OK','suc');try{speechSynthesis.speak(new SpeechSynthesisUtterance('Messung gespeichert.'));}catch(e){}}}catch(e){log('Brain nicht erreichbar','warn');}}

function createParts(){const c=document.getElementById('parts');for(let i=0;i<25;i++){const p=document.createElement('div');p.style.cssText='position:absolute;width:2px;height:2px;background:rgba(0,212,170,0.4);border-radius:50%;left:'+Math.random()*100+'%;top:'+Math.random()*100+'%;animation:fp '+(8+Math.random()*8)+'s linear infinite';c.appendChild(p);}}
const ps=document.createElement('style');ps.innerHTML='@keyframes fp{0%{transform:translateY(0);}100%{transform:translateY(-100vh);}}';document.head.appendChild(ps);

// Tab switching
function switchTab(tab){document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));document.querySelectorAll('.tab-content').forEach(c=>c.classList.remove('active'));document.querySelector(`[onclick="switchTab('${tab}')"]`).classList.add('active');document.getElementById(`${tab}-tab`).classList.add('active');}

// ══════════════ TRICHOME LOGIC ══════════════
let triVideo, triCanvas, triCtx, triStream;

async function startTriCam(){
  const ov=document.getElementById('triOverlay');
  triVideo=document.getElementById('triVideo');
  triCanvas=document.getElementById('triCanvas');
  triCtx=triCanvas.getContext('2d');
  try{
    triStream=await navigator.mediaDevices.getUserMedia({video:{facingMode:"environment",width:{ideal:1920}}});
    triVideo.srcObject=triStream;
    triVideo.style.display='block';
    ov.style.display='none';
    document.getElementById('triBtn').disabled=false;
    await triVideo.play();
    triCanvas.width=triVideo.videoWidth||1920;
    triCanvas.height=triVideo.videoHeight||1080;
    log('📸 Trichom-Kamera aktiviert','suc');
  }catch(e){log('Kamerafehler: '+e.message,'err');}
}

function captureTri(){
  if(!triVideo||!triVideo.videoWidth)return;
  triCtx.drawImage(triVideo,0,0,triCanvas.width,triCanvas.height);
  const d=triCanvas.toDataURL('image/jpeg',0.85).split(',')[1];
  const btn=document.getElementById('triBtn');
  btn.textContent='⏳ Analysiere...';
  btn.disabled=true;
  fetch('/api/trichome/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_base64:d})})
  .then(r=>r.json())
  .then(data=>{
    if(data.success){displayTriResults(data.analysis);}else{alert('Fehler: '+(data.error||'?'));}
  })
  .catch(e=>alert('Netzwerk: '+e.message))
  .finally(()=>{btn.textContent='🔍 Erneut';btn.disabled=false;});
}

function displayTriResults(a){
  document.getElementById('triResults').classList.add('show');
  const c=a.clear_percent||0,m=a.milky_percent||a.milkyly_percent||0,am=a.amber_percent||0;
  setTimeout(()=>{document.getElementById('tClear').style.width=c+'%';document.getElementById('tClearV').textContent=c+'%';
    document.getElementById('tMilk').style.width=m+'%';document.getElementById('tMilkV').textContent=m+'%';
    document.getElementById('tAmber').style.width=am+'%';document.getElementById('tAmberV').textContent=am+'%';},100);
  const stage=a.maturity_stage||'Early';
  ['Early','Peak','Late','Overripe'].forEach(s=>document.getElementById('t'+s).classList.toggle('active',s===stage));
  document.getElementById('tThc').textContent=(parseFloat(a.thc_estimate)||0).toFixed(1);
  document.getElementById('tCbd').textContent=(parseFloat(a.cbd_estimate)||0).toFixed(1);
  document.getElementById('tBud').textContent=a.bud_development||'—';
  document.getElementById('tResin').textContent=a.resin_production||'—';
  const recs=a.recommendations||[];
  document.getElementById('tRecs').innerHTML=recs.map(r=>`<div style="background:#0f0f1a;border-radius:6px;padding:6px 10px;margin:3px 0;font-size:0.75rem;">💡 ${r}</div>`).join('');
  document.getElementById('tConf').textContent=a.confidence||'—';
  document.getElementById('tQual').textContent=a.image_quality_score||'—';
  try{speechSynthesis.speak(new SpeechSynthesisUtterance(`Analyse: ${stage}. Milky ${m} Prozent.`));}catch(e){}
}

log('🌿 Light Meter V3 bereit | 🔬 für erweiterte Werte | Trichome-Tab verfügbar','suc');
</script>
</body>
</html>"""

@app.get("/")
async def lightmeter(request: Request):
    return HTMLResponse(HTML_TEMPLATE)

@app.post("/api/save_measurement")
async def save_measurement(data: dict):
    print("🌿 Brain-Sync V3:", data)
    return {"status": "saved", "values": 18, "data": data}
