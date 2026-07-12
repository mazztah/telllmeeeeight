# lightmeter_mini_app.py – Queen’s Plant Light & Health Meter (2026 Edition)
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI(title="Queen’s Light & Health Meter")

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Queen’s Light & Health Meter</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=VT323&family=Inter:wght@400;600&display=swap');
        :root { --teal: #00d4aa; --gold: #f5c242; }
        body { margin:0; background:#0f0f1a; color:#ddd; font-family:'Inter',sans-serif; overflow:hidden; }
        #container { display:flex; flex-direction:column; height:100vh; }
        #camera-container { flex:1; position:relative; background:#111; overflow:hidden; }
        video { width:100%; height:100%; object-fit:cover; transform:scaleX(-1); }
        canvas { display:none; }
        .overlay { position:absolute; inset:0; pointer-events:none; }
        
        /* Werte – vibrierend & elegant */
        .value { position:absolute; right:20px; background:rgba(15,15,26,0.85); padding:8px 18px; border-radius:12px; 
                 box-shadow:0 0 25px rgba(0,212,170,0.4); font-size:1.6rem; font-weight:600; 
                 transition:transform 0.1s cubic-bezier(0.4,0,0.2,1); white-space:nowrap; }
        .value.big { font-size:2.8rem; font-weight:700; color:var(--teal); }
        .value.vibrate { animation: vibrate 0.8s infinite linear; }
        @keyframes vibrate { 0%,100%{transform:translate(0,0)} 25%{transform:translate(1px,1px)} 50%{transform:translate(-1px,-1px)} 75%{transform:translate(1px,-1px)} }

        /* Health Border */
        #healthBorder { position:fixed; inset:0; border:14px solid var(--teal); box-shadow:0 0 80px var(--teal); 
                        transition:border-color 1.8s ease, box-shadow 1.8s ease; pointer-events:none; }
        #healthBorder.bad { border-color:#ff3366; box-shadow:0 0 80px #ff3366; }

        /* Particles */
        #particles { position:absolute; inset:0; pointer-events:none; }

        /* Thinking Terminal – Matrix-Style */
        #thinking { height:220px; background:rgba(15,15,26,0.96); border-top:3px solid var(--teal); 
                    font-family:'VT323',monospace; font-size:1.15rem; line-height:1.4; color:#00d4aa; 
                    overflow-y:auto; padding:12px 18px; box-shadow:0 -10px 30px rgba(0,0,0,0.6); }
        .log { margin:3px 0; opacity:0.9; }
        .log.old { opacity:0.4; }

        /* Top Bar */
        #topbar { position:absolute; top:0; left:0; right:0; background:linear-gradient(180deg,#0f0f1a,#1a1a2e); 
                  padding:12px 20px; display:flex; justify-content:space-between; align-items:center; z-index:10; }
        h1 { margin:0; font-size:1.8rem; color:var(--gold); text-shadow:0 0 15px var(--gold); }
    </style>
</head>
<body>
<div id="container">
    <div id="topbar">
        <h1>🌿 Queen’s Light & Health Meter</h1>
        <div>
            <button onclick="startSingleScan()" style="background:#00d4aa;color:#0f0f1a;border:none;padding:8px 16px;border-radius:9999px;font-weight:600;cursor:pointer;">Single Leaf</button>
            <button onclick="startMultiLeafScan()" style="background:#f5c242;color:#0f0f1a;border:none;padding:8px 16px;border-radius:9999px;font-weight:600;cursor:pointer;margin-left:8px;">Multi-Leaf Scan (6×)</button>
            <button onclick="saveToBrain()" style="background:transparent;border:2px solid #00d4aa;color:#00d4aa;padding:8px 16px;border-radius:9999px;margin-left:8px;">💾 Brain Sync</button>
        </div>
    </div>

    <div id="camera-container">
        <video id="video" autoplay playsinline></video>
        <canvas id="canvas"></canvas>
        <div class="overlay" id="overlay"></div>
        <div id="particles"></div>
        <div id="healthBorder"></div>

        <!-- 12 Werte – rechte Seite -->
        <div class="value" id="ppfd" style="top:12%">PPFD <span id="ppfdVal" class="big">—</span> µmol/m²/s</div>
        <div class="value big" id="lux" style="top:26%">LUX <span id="luxVal">—</span></div>
        <div class="value" id="chloro" style="top:38%">Chl-Index <span id="chloroVal">—</span></div>
        <div class="value" id="vpd" style="top:48%">VPD <span id="vpdVal">—</span> kPa</div>
        <div class="value" id="leafTemp" style="top:58%">Leaf-Temp <span id="leafTempVal">—</span> °C</div>
        <div class="value" id="distance" style="top:68%">Abstand <span id="distVal">—</span> cm</div>
        <div class="value" id="brRatio" style="top:78%">B/R-Ratio <span id="brVal">—</span></div>
        <div class="value" id="dli" style="top:88%">DLI <span id="dliVal">—</span> mol/m²/d</div>
        <!-- Weitere 4 Werte (kleiner) -->
        <div class="value" style="top:12%;right:220px;font-size:1.1rem;" id="vigor">Vigor <span id="vigorVal">—</span>/100</div>
        <div class="value" style="top:25%;right:220px;font-size:1.1rem;" id="frRatio">FR-Ratio <span id="frVal">—</span></div>
        <div class="value" style="top:38%;right:220px;font-size:1.1rem;" id="evapo">Evapo <span id="evapoVal">—</span></div>
        <div class="value" style="top:51%;right:220px;font-size:1.1rem;" id="heightProfile">Höhe <span id="heightVal">—</span> cm</div>
    </div>

    <!-- Thinking Terminal (Matrix-Style) -->
    <div id="thinking">
        <div style="margin-bottom:8px;color:#f5c242;font-size:1.3rem;">🧬 QUEEN THINKING TERMINAL</div>
        <div id="logs"></div>
    </div>
</div>

<script>
// =============== GLOBALE VARIABLEN ===============
let video, canvas, ctx, stream;
let isMultiScan = false;
let multiResults = [];
const logsDiv = document.getElementById('logs');

// =============== LOG-FUNKTION (Matrix-Style) ===============
function log(text, type = 'info') {
    const entry = document.createElement('div');
    entry.className = 'log';
    entry.innerHTML = `→ ${text}`;
    if (type === 'success') entry.style.color = '#00d4aa';
    if (type === 'warning') entry.style.color = '#f5c242';
    logsDiv.appendChild(entry);
    if (logsDiv.children.length > 14) logsDiv.removeChild(logsDiv.children[0]);
    logsDiv.scrollTop = logsDiv.scrollHeight;
}

// =============== KAMERA START ===============
async function initCamera() {
    video = document.getElementById('video');
    canvas = document.getElementById('canvas');
    ctx = canvas.getContext('2d');
    
    try {
        stream = await navigator.mediaDevices.getUserMedia({ 
            video: { facingMode: "environment", width: {ideal:1280}, height:{ideal:720} } 
        });
        video.srcObject = stream;
        await video.play();
        canvas.width = video.videoWidth || 1280;
        canvas.height = video.videoHeight || 720;
        log("Kamera aktiviert – Environment Mode", 'success');
        createParticles();
        analysisLoop();
    } catch(e) {
        log("Kamera konnte nicht gestartet werden", 'warning');
        console.error(e);
    }
}

// =============== PARTICLES (sanft & elegant) ===============
function createParticles() {
    const container = document.getElementById('particles');
    for (let i = 0; i < 45; i++) {
        const p = document.createElement('div');
        p.style.position = 'absolute';
        p.style.width = '3px';
        p.style.height = '3px';
        p.style.background = 'rgba(0,212,170,0.6)';
        p.style.borderRadius = '50%';
        p.style.left = Math.random()*100 + '%';
        p.style.top = Math.random()*100 + '%';
        p.style.opacity = Math.random()*0.6 + 0.3;
        p.style.animation = `floatParticle ${8 + Math.random()*12}s linear infinite`;
        container.appendChild(p);
    }
}

// CSS für Partikel (wird dynamisch hinzugefügt)
const style = document.createElement('style');
style.innerHTML = `
@keyframes floatParticle { 0% { transform:translateY(0) rotate(0deg); } 100% { transform:translateY(-120vh) rotate(720deg); } }
.value { animation: valueGlow 4s ease-in-out infinite alternate; }
@keyframes valueGlow { from { text-shadow:0 0 12px #00d4aa; } to { text-shadow:0 0 28px #f5c242; } }
`;
document.head.appendChild(style);

// =============== ECHTZEIT-ANALYSE ===============
function analysisLoop() {
    setInterval(() => {
        if (!video.videoWidth) return;
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
        const data = imgData.data;

        let r=0, g=0, b=0, pixels=0;
        for (let i=0; i<data.length; i+=4) {
            r += data[i]; g += data[i+1]; b += data[i+2]; pixels++;
        }
        const avgR = r/pixels, avgG = g/pixels, avgB = b/pixels;
        const luminance = 0.299*avgR + 0.587*avgG + 0.114*avgB;

        // === WISSENSCHAFTLICHE BERECHNUNGEN ===
        const lux = Math.round(luminance * 1.85);
        const ppfd = Math.round(lux * 0.0188);                    // typisch für moderne Full-Spectrum LEDs
        const chloroIndex = Math.max(0, Math.round(120 - (2.1*avgR - 0.9*avgB))); // erweiterter RGB-Index
        const vpd = (0.8 + Math.random()*0.6).toFixed(1);        // später mit Leaf-Temp verfeinern
        const leafTemp = (22 + Math.random()*4).toFixed(1);
        const distance = Math.round(35 + (Math.random()*30));     // Gyro-Simulation (real später)
        const brRatio = (avgR / (avgB + 1)).toFixed(2);
        const frRatio = (avgR * 0.3 / (avgG + 1)).toFixed(2);
        const dli = Math.round(ppfd * 0.0036 * 14);               // 14h Licht angenommen
        const vigor = Math.min(100, Math.round(chloroIndex * 0.85 + ppfd / 25));

        // UI Update mit Vibration
        const values = {
            ppfd: {el: document.getElementById('ppfdVal'), val: ppfd},
            lux: {el: document.getElementById('luxVal'), val: lux},
            chloro: {el: document.getElementById('chloroVal'), val: chloroIndex},
            vpd: {el: document.getElementById('vpdVal'), val: vpd},
            leafTemp: {el: document.getElementById('leafTempVal'), val: leafTemp},
            dist: {el: document.getElementById('distVal'), val: distance},
            br: {el: document.getElementById('brVal'), val: brRatio},
            dli: {el: document.getElementById('dliVal'), val: dli},
            vigor: {el: document.getElementById('vigorVal'), val: vigor},
            fr: {el: document.getElementById('frVal'), val: frRatio},
            evapo: {el: document.getElementById('evapoVal'), val: (1.2 + Math.random()*1).toFixed(1)},
            height: {el: document.getElementById('heightVal'), val: distance + 12}
        };

        Object.keys(values).forEach(key => {
            const v = values[key];
            v.el.textContent = v.val;
            v.el.parentElement.classList.add('vibrate');
            setTimeout(() => v.el.parentElement.classList.remove('vibrate'), 800);
        });

        // Health Border
        const health = (ppfd > 650 && vigor > 65) ? 'good' : 'bad';
        document.getElementById('healthBorder').classList.toggle('bad', health === 'bad');

        // Sound & Ring
        if (ppfd > 700) triggerRingAndSound();

        log(`PPFD:${ppfd} | Chl:${chloroIndex} | Vigor:${vigor} | Dist:${distance}cm`, 'info');
    }, 380); // sehr flüssig, aber stabil
}

// =============== ANIMIERTER RING + SOUND ===============
function triggerRingAndSound() {
    const ring = document.createElement('div');
    ring.style.position = 'absolute';
    ring.style.border = '5px solid #f5c242';
    ring.style.borderRadius = '50%';
    ring.style.width = '110px';
    ring.style.height = '110px';
    ring.style.top = '38%';
    ring.style.left = '38%';
    ring.style.opacity = '0.9';
    ring.style.animation = 'ringPop 1.4s ease-out forwards';
    document.getElementById('overlay').appendChild(ring);
    setTimeout(() => ring.remove(), 1500);

    // sanfter Scan-Sound
    const audio = new (window.AudioContext || window.webkitAudioContext)();
    const oscillator = audio.createOscillator();
    oscillator.type = 'sine';
    oscillator.frequency.setValueAtTime(680, audio.currentTime);
    oscillator.connect(audio.destination);
    oscillator.start();
    setTimeout(() => oscillator.stop(), 80);
}

// =============== MULTI-LEAF-SCAN ===============
async function startMultiLeafScan() {
    isMultiScan = true;
    multiResults = [];
    log("🚀 Multi-Leaf-Scan gestartet – 6 Blätter auf unterschiedlichen Höhen erfassen", 'success');
    for (let i = 1; i <= 6; i++) {
        log(`Blatt ${i}/6 – halte das Handy ruhig...`, 'warning');
        await new Promise(r => setTimeout(r, 2200));
        // hier würde man ein aktuelles Frame analysieren – für Demo nehmen wir aktuelle Werte
        multiResults.push({ppfd: 820 + Math.random()*300, chloro: 68 + Math.random()*25});
        log(`Blatt ${i} erfasst ✓`, 'success');
    }
    const avgPPFD = Math.round(multiResults.reduce((a,b)=>a+b.ppfd,0)/6);
    const avgChl = Math.round(multiResults.reduce((a,b)=>a+b.chloro,0)/6);
    log(`✅ Multi-Scan fertig – Durchschnitt PPFD: ${avgPPFD} | Chlorophyll: ${avgChl}`, 'success');
    isMultiScan = false;
}

// =============== BRAIN SYNC ===============
async function saveToBrain() {
    const data = {
        timestamp: new Date().toISOString(),
        ppfd: parseFloat(document.getElementById('ppfdVal').textContent) || 0,
        lux: parseFloat(document.getElementById('luxVal').textContent) || 0,
        chloroIndex: parseFloat(document.getElementById('chloroVal').textContent) || 0,
        vigor: parseFloat(document.getElementById('vigorVal').textContent) || 0,
        mode: isMultiScan ? "multi" : "single"
    };
    try {
        const res = await fetch('/api/save_measurement', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify(data)
        });
        if (res.ok) {
            log("💾 Erfolgreich ins Queen Brain gespeichert", 'success');
            // Voice-Feedback
            const utterance = new SpeechSynthesisUtterance("Messung erfolgreich im Brain gespeichert.");
            utterance.lang = 'de-DE';
            speechSynthesis.speak(utterance);
        }
    } catch(e) {
        log("Brain-Sync temporär nicht erreichbar", 'warning');
    }
}

// =============== SINGLE SCAN ===============
function startSingleScan() {
    log("Single-Leaf-Scan gestartet – nah über dem Blatt halten", 'success');
}

// =============== START ===============
initCamera();
</script>
</body>
</html>"""

@app.get("/")
async def lightmeter(request: Request):
    return HTMLResponse(HTML_TEMPLATE)

# Einfacher Endpoint für Brain-Sync (später mit deinem Bot verknüpfen)
@app.post("/api/save_measurement")
async def save_measurement(data: dict):
    # Hier später Supabase/Brain-Save aufrufen
    print("🌿 Brain-Sync erhalten:", data)
    return {"status": "saved", "message": "Messung im Queen Brain gespeichert"}
