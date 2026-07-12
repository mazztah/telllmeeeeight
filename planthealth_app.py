# planthealth_app.py – Queen Plant Health Dashboard 2026
# Features: PPFD/Lux-Tacho, Blatt-Temp, Transpiration, VPD, Chlorophyll,
#           DLI, Bodenfeuchtigkeit, Growth Stage, Stress-Level, Plant Age Tracking
#           Auto-Logging ins Brain alle 10 Sek, Lampen-Kalibrierung 4 Typen
import logging
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)
app = FastAPI(title="Queen Plant Health Dashboard 🌿")

HTML = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>🌿 Queen Plant Health</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  body { background: linear-gradient(180deg,#0f172a,#1e3a2f); color:#fff; font-family:system-ui,-apple-system,sans-serif; }
  .value { font-size:2.6rem; font-weight:700; line-height:1; }
  .gauge-wrap { position:relative; width:160px; height:160px; margin:0 auto; }
  .gauge-label { position:absolute; bottom:10px; width:100%; text-align:center; font-size:.75rem; letter-spacing:.1em; opacity:.7; }
  .gauge-val  { position:absolute; top:50%; left:50%; transform:translate(-50%,-55%); font-size:1.6rem; font-weight:700; }
  input[type=number], select { background:rgba(0,0,0,.6); border:1px solid rgba(255,255,255,.15); border-radius:1rem; color:#fff; padding:.5rem 1rem; width:100%; text-align:center; font-size:1.1rem; }
  input[type=range] { width:100%; accent-color:#10b981; }
  .card { background:rgba(0,0,0,.4); border:1px solid rgba(255,255,255,.08); border-radius:1.5rem; padding:1.25rem; }
  .badge { display:inline-block; padding:.2rem .7rem; border-radius:9999px; font-size:.75rem; font-weight:600; }
  #livePanel { position:fixed; top:.75rem; right:.75rem; background:rgba(0,0,0,.75); border:1px solid rgba(16,185,129,.3); border-radius:1rem; padding:.5rem .85rem; font-size:.7rem; line-height:1.6; z-index:50; min-width:110px; }
  .stress-bar { height:8px; border-radius:4px; background:linear-gradient(90deg,#22c55e,#eab308,#ef4444); }
  .stress-indicator { height:14px; width:4px; background:#fff; border-radius:2px; position:relative; margin-top:-11px; transition:left .5s; }
</style>
</head>
<body class="min-h-screen pb-28">

<!-- Live-Panel oben rechts (alle 10s Update) -->
<div id="livePanel">
  <div class="text-emerald-400 font-bold mb-1">📡 Live</div>
  <div>PPFD: <span id="lpPPFD" class="font-mono text-yellow-300">—</span></div>
  <div>Lux: <span id="lpLux" class="font-mono">—</span></div>
  <div>Blatt: <span id="lpLeaf" class="font-mono text-cyan-300">—</span>°C</div>
  <div>VPD: <span id="lpVPD" class="font-mono text-pink-300">—</span> kPa</div>
  <div>DLI: <span id="lpDLI" class="font-mono text-violet-300">—</span></div>
  <div>Alter: <span id="lpAge" class="font-mono text-orange-300">—</span> T</div>
  <div>Stage: <span id="lpStage" class="font-mono">—</span></div>
  <div id="lpLog" class="text-gray-500 text-xs mt-1"></div>
</div>

<div class="p-4 pt-3">
  <h1 class="text-2xl font-bold text-emerald-400">🌿 Queen Plant Health</h1>
  <p class="text-emerald-200 text-xs mt-1">Live PPFD • Blatt-Temp • VPD • Trichome • Brain-Logging</p>
</div>

<div class="px-4 space-y-5">

  <!-- LAMPEN-KALIBRIERUNG -->
  <div class="card">
    <p class="text-xs text-emerald-300 uppercase tracking-widest mb-2">🔦 Lampen-Kalibrierung</p>
    <select id="lampType" onchange="onLampChange()">
      <option value="1.85">LED Full-Spectrum (Standard)</option>
      <option value="1.45">HPS – Natriumdampf</option>
      <option value="1.72">CMH – Keramik-MH</option>
      <option value="1.30">MH / CFL</option>
    </select>
    <p class="text-xs text-gray-500 mt-1 text-center">Kalibrierungsfaktor für PPFD-Schätzung</p>
  </div>

  <!-- TACHOS -->
  <div class="card">
    <p class="text-xs text-emerald-300 uppercase tracking-widest mb-3">⚡ Live-Sensoren</p>
    <div class="grid grid-cols-2 gap-4">
      <div>
        <div class="gauge-wrap">
          <canvas id="luxGauge"></canvas>
          <div class="gauge-val text-yellow-400" id="luxGVal">0</div>
          <div class="gauge-label text-yellow-200">LUX</div>
        </div>
      </div>
      <div>
        <div class="gauge-wrap">
          <canvas id="ppfdGauge"></canvas>
          <div class="gauge-val text-emerald-400" id="ppfdGVal">0</div>
          <div class="gauge-label text-emerald-200">PPFD µmol</div>
        </div>
      </div>
    </div>
    <div class="grid grid-cols-2 gap-2 mt-3 text-xs text-center">
      <div>CCT: <span id="cctVal" class="text-pink-300 font-mono">—</span> K</div>
      <div>Spectrum: <span id="specVal" class="text-cyan-300 font-mono">—</span></div>
    </div>
    <div id="sensorStatus" class="text-xs text-center text-gray-500 mt-2">Sensor wird initialisiert…</div>
  </div>

  <!-- EINGABEN -->
  <div class="card">
    <p class="text-xs text-emerald-300 uppercase tracking-widest mb-3">📐 Messparameter</p>
    <div class="grid grid-cols-2 gap-3">
      <div>
        <label class="text-xs text-gray-400">Abstand Lampe→Blatt (cm)</label>
        <input type="number" id="distance" value="40" min="5" max="200">
      </div>
      <div>
        <label class="text-xs text-gray-400">Luft-Temp (°C)</label>
        <input type="number" id="airTemp" value="24" min="10" max="45">
      </div>
      <div>
        <label class="text-xs text-gray-400">Luftfeuchte (%)</label>
        <input type="number" id="rh" value="55" min="10" max="100">
      </div>
      <div>
        <label class="text-xs text-gray-400">Bodenfeuchtigkeit (%)</label>
        <input type="number" id="soilMoist" value="60" min="0" max="100">
      </div>
    </div>
    <button onclick="calculateAll()"
      class="w-full mt-4 bg-emerald-500 hover:bg-emerald-600 active:scale-95 py-3 rounded-2xl text-lg font-bold transition-all">
      ▶ Alles berechnen
    </button>
  </div>

  <!-- ERGEBNISSE -->
  <div id="results" class="hidden card space-y-4">
    <p class="text-xs text-emerald-300 uppercase tracking-widest">📊 Messwerte</p>

    <!-- Blatt-Temp + Transpiration -->
    <div class="grid grid-cols-2 gap-3 text-center">
      <div class="bg-black/40 rounded-2xl p-3">
        <div class="value text-cyan-400" id="rLeafTemp">—</div>
        <div class="text-xs text-cyan-200 mt-1">°C Blattoberfläche</div>
      </div>
      <div class="bg-black/40 rounded-2xl p-3">
        <div class="value text-blue-400" id="rTrans">—</div>
        <div class="text-xs text-blue-200 mt-1">mmol/m²/s Verdunstung</div>
      </div>
    </div>

    <!-- VPD -->
    <div class="bg-black/40 rounded-2xl p-3 text-center">
      <div class="text-xs text-gray-400 mb-1">VPD (Vapor Pressure Deficit)</div>
      <div class="value text-pink-400 text-3xl" id="rVPD">—</div>
      <div class="text-xs text-pink-200">kPa</div>
      <div class="text-sm mt-1 font-medium" id="rVPDrec">—</div>
    </div>

    <!-- Chlorophyll -->
    <div class="bg-black/40 rounded-2xl p-3 text-center">
      <div class="text-xs text-gray-400 mb-1">🍃 Chlorophyll-Index (NDVI-Näherung)</div>
      <div class="value text-green-400 text-3xl" id="rChloro">—</div>
      <div class="text-sm mt-1" id="rChloroRec">—</div>
    </div>

    <!-- DLI -->
    <div class="bg-black/40 rounded-2xl p-3 text-center">
      <div class="text-xs text-gray-400 mb-1">☀️ DLI (Daily Light Integral)</div>
      <div class="value text-violet-400 text-3xl" id="rDLI">—</div>
      <div class="text-xs text-violet-200">mol/m²/Tag (bei 18h)</div>
      <div class="text-sm mt-1" id="rDLIrec">—</div>
    </div>

    <!-- Stress Level -->
    <div class="bg-black/40 rounded-2xl p-4">
      <div class="text-xs text-gray-400 mb-2">⚠️ Stress-Level</div>
      <div class="stress-bar"></div>
      <div class="stress-indicator" id="stressIndicator" style="left:0%"></div>
      <div class="text-sm text-center mt-2 font-medium" id="rStress">—</div>
    </div>

    <!-- Growth Stage -->
    <div class="bg-black/40 rounded-2xl p-3 text-center">
      <div class="text-xs text-gray-400 mb-1">🌱 Growth Stage</div>
      <div class="text-2xl font-bold" id="rStage">—</div>
      <div class="text-sm mt-1" id="rStageRec">—</div>
    </div>

    <!-- Bodenfeuchtigkeit -->
    <div class="bg-black/40 rounded-2xl p-3 text-center">
      <div class="text-xs text-gray-400 mb-1">💧 Bodenfeuchtigkeit</div>
      <div class="value text-blue-300 text-3xl" id="rSoil">—</div>
      <div class="text-sm mt-1" id="rSoilRec">—</div>
    </div>

    <!-- Empfehlung (Grower-Tabelle) -->
    <div class="bg-emerald-900/40 border border-emerald-500/30 rounded-2xl p-4 text-center">
      <div class="text-xs text-emerald-300 mb-2 uppercase tracking-widest">Empfehlung (Grower-Tabelle)</div>
      <div class="text-lg font-bold" id="rMainRec">—</div>
    </div>
  </div>

  <!-- PLANT AGE TRACKING -->
  <div class="card">
    <p class="text-xs text-emerald-300 uppercase tracking-widest mb-3">🌿 Plant Age Tracker</p>
    <div class="grid grid-cols-2 gap-3">
      <div>
        <label class="text-xs text-gray-400">Keim-Datum (oder 0 = heute)</label>
        <input type="date" id="germDate" class="text-sm py-2">
      </div>
      <div>
        <label class="text-xs text-gray-400">Bekannte Höhe jetzt (cm)</label>
        <input type="number" id="plantHeight" value="30" min="1" max="300">
      </div>
      <div>
        <label class="text-xs text-gray-400">Anzahl Blattetagen</label>
        <input type="number" id="nodeCount" value="8" min="1" max="30">
      </div>
      <div>
        <label class="text-xs text-gray-400">Internodienabstand (cm)</label>
        <input type="number" id="internode" value="4" min="1" max="20">
      </div>
    </div>
    <button onclick="estimateAge()"
      class="w-full mt-3 bg-violet-600 hover:bg-violet-700 active:scale-95 py-3 rounded-2xl text-lg font-bold transition-all">
      📐 Alter schätzen (bio + math)
    </button>
    <div id="ageResult" class="hidden mt-3 bg-black/50 rounded-2xl p-4 text-center">
      <div class="text-3xl font-bold text-orange-300" id="estAge">—</div>
      <div class="text-xs text-orange-200 mt-1">Tage geschätzt</div>
      <div class="text-sm mt-2" id="ageDetail">—</div>
    </div>
  </div>

  <!-- AUTO-LOGGING -->
  <div class="card">
    <div class="flex items-center justify-between">
      <div>
        <p class="text-sm font-bold text-emerald-300">🧠 Auto-Brain-Logging</p>
        <p class="text-xs text-gray-400">Alle 10 Sek kompletter Datensatz</p>
      </div>
      <label class="relative inline-flex items-center cursor-pointer">
        <input type="checkbox" id="autoLog" class="sr-only peer" onchange="toggleAutoLog()">
        <div class="w-11 h-6 bg-gray-600 rounded-full peer peer-checked:bg-emerald-500 after:content-[''] after:absolute after:top-.5 after:left-.5 after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:after:translate-x-5"></div>
      </label>
    </div>
    <div id="logStatus" class="text-xs text-gray-500 mt-2">—</div>
  </div>

</div>

<!-- FOOTER -->
<div class="fixed bottom-0 left-0 right-0 bg-black/90 border-t border-white/10 p-3 flex justify-between items-center">
  <div id="footerStatus" class="font-mono text-xs text-gray-400">Sensor init…</div>
  <button onclick="sendToBot()"
    class="bg-emerald-500 text-black px-5 py-2 rounded-full text-sm font-bold active:scale-95">
    📤 An Bot senden
  </button>
</div>

<script>
// ── State ──────────────────────────────────────────────────────────────────────
let luxSensor, videoStream, video, canvas, ctx;
let currentLux = 0, currentPPFD = 0, currentCCT = 5500;
let currentR = 0, currentG = 0, currentB = 0;
let luxGauge, ppfdGauge;
let ppfdFactor = 1.85; // LED default
let autoLogInterval = null;
let dliAccumPPFD = 0, dliFrames = 0;
let lastResults = {};

// ── Lampen-Kalibrierung ────────────────────────────────────────────────────────
function onLampChange() {
  ppfdFactor = parseFloat(document.getElementById('lampType').value);
}

// ── Gauges ─────────────────────────────────────────────────────────────────────
function initGauges() {
  const opts = (color, max) => ({
    type: 'doughnut',
    data: { datasets: [{ data: [0, max], backgroundColor: [color, '#1e293b'], borderWidth: 0, circumference: 270, rotation: 225 }] },
    options: { cutout: '80%', plugins: { legend: { display: false }, tooltip: { enabled: false } }, animation: { duration: 100 } }
  });
  luxGauge  = new Chart(document.getElementById('luxGauge'),  opts('#eab308', 100));
  ppfdGauge = new Chart(document.getElementById('ppfdGauge'), opts('#10b981', 2000));
}

function updateGauges() {
  const luxPct  = Math.min(currentLux / 100000 * 100, 100);
  const ppfdPct = Math.min(currentPPFD, 2000);
  luxGauge.data.datasets[0].data  = [luxPct, 100 - luxPct];
  ppfdGauge.data.datasets[0].data = [ppfdPct, 2000 - ppfdPct];
  luxGauge.update('none');
  ppfdGauge.update('none');
  document.getElementById('luxGVal').textContent  = currentLux > 9999 ? (currentLux/1000).toFixed(1)+'k' : currentLux;
  document.getElementById('ppfdGVal').textContent = currentPPFD;
}

// ── Sensor-Init ────────────────────────────────────────────────────────────────
async function initSensors() {
  initGauges();

  // Ambient Light Sensor
  if ('AmbientLightSensor' in window) {
    try {
      const als = new AmbientLightSensor({ frequency: 5 });
      als.onreading = () => {
        currentLux = Math.round(als.illuminance);
        document.getElementById('lpLux').textContent = currentLux;
        updateGauges();
      };
      als.onerror = () => {};
      als.start();
      setStatus('✅ AmbientLightSensor aktiv');
    } catch(e) { setStatus('ℹ️ Nur Kamera-Modus'); }
  } else {
    setStatus('ℹ️ ALS nicht verfügbar – Kamera-Modus');
  }

  // Kamera für PPFD + Spektrum + Chlorophyll
  try {
    video  = document.createElement('video');
    canvas = document.createElement('canvas');
    ctx    = canvas.getContext('2d');
    video.style.display = 'none';
    document.body.appendChild(video);
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment', width: { ideal: 640 }, height: { ideal: 480 } } });
    video.srcObject = stream;
    videoStream = stream;
    await video.play();
    setInterval(analyzeFrame, 200);
    setStatus((prev => prev + ' • 📷 Kamera aktiv'), true);
  } catch(e) {
    setStatus('❌ Kamera: ' + e.message);
  }

  // Live-Panel alle 10s
  setInterval(updateLivePanel, 10000);
}

function setStatus(msg, append) {
  const el = document.getElementById('sensorStatus');
  el.textContent = append ? (el.textContent + ' ' + msg) : msg;
  document.getElementById('footerStatus').textContent = msg.substring(0, 40);
}

// ── Frame-Analyse (PPFD, Spektrum, Chlorophyll) ────────────────────────────────
function analyzeFrame() {
  if (!video || !video.videoWidth) return;
  canvas.width  = Math.min(video.videoWidth, 200);
  canvas.height = Math.min(video.videoHeight, 150);
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  const d = ctx.getImageData(0, 0, canvas.width, canvas.height).data;

  let r = 0, g = 0, b = 0, n = d.length / 4;
  for (let i = 0; i < d.length; i += 4) { r += d[i]; g += d[i+1]; b += d[i+2]; }
  r = r/n; g = g/n; b = b/n;
  currentR = r; currentG = g; currentB = b;

  const brightness = r * 0.299 + g * 0.587 + b * 0.114;
  currentPPFD = Math.round(brightness * ppfdFactor);
  currentCCT  = Math.max(2000, Math.min(8000, Math.round(6600 - (r - b) * 9)));

  // Lux aus Kamera wenn ALS nicht verfügbar
  if (currentLux === 0) currentLux = Math.round(currentPPFD * 54);

  document.getElementById('cctVal').textContent  = currentCCT;
  document.getElementById('specVal').textContent  = (g > 160 ? 'Grün' : r > b ? 'Rot' : 'Blau') + ' ~' + Math.round(500 + (r-b)*0.4) + 'nm';
  document.getElementById('lpPPFD').textContent   = currentPPFD;
  document.getElementById('lpLux').textContent    = currentLux;

  // DLI accumulation
  dliAccumPPFD += currentPPFD * 0.2 / 1000000; // µmol → mol, 0.2s interval
  dliFrames++;

  updateGauges();
}

// ── Haupt-Berechnung ───────────────────────────────────────────────────────────
function calculateAll() {
  const dist      = parseFloat(document.getElementById('distance').value)   || 40;
  const airTemp   = parseFloat(document.getElementById('airTemp').value)     || 24;
  const rh        = parseFloat(document.getElementById('rh').value)          || 55;
  const soilMoist = parseFloat(document.getElementById('soilMoist').value)   || 60;
  const ppfd      = currentPPFD || 600;

  // ── Blatt-Temperatur (Energiebilanz-Modell) ──────────────────────────────
  const absorbed  = ppfd * 0.85 * 0.48;
  const deltaT    = absorbed / 1800;
  const leafTemp  = +(airTemp + deltaT).toFixed(1);

  // ── VPD ──────────────────────────────────────────────────────────────────
  const esLeaf = 0.6108 * Math.exp(17.27 * leafTemp / (leafTemp + 237.3));
  const esAir  = 0.6108 * Math.exp(17.27 * airTemp  / (airTemp  + 237.3));
  const ea     = esAir * (rh / 100);
  const vpd    = +(esLeaf - ea).toFixed(2);

  // ── Transpiration ─────────────────────────────────────────────────────────
  const gs            = 0.45 * (ppfd / (ppfd + 180));
  const transpiration = Math.round(gs * vpd * 42);

  // ── Chlorophyll (NDVI-Näherung aus Kamera R/G/B) ─────────────────────────
  const ndvi   = currentG > 0 ? ((currentG - currentR) / (currentG + currentR + 1)) : 0.3;
  const chloro = Math.max(0, Math.min(100, Math.round(50 + ndvi * 80)));

  // ── DLI (bei 18h Lichttag) ────────────────────────────────────────────────
  const dli = +(ppfd * 0.0036 * 18).toFixed(1);

  // ── Growth Stage ──────────────────────────────────────────────────────────
  let stage = '🌱 Veg', stageRec = 'Stickstoff-betont, PPFD 400–600';
  if (ppfd > 700 && rh < 60) { stage = '🌸 Flower'; stageRec = 'Kalium-betont, PPFD 700–1000'; }
  if (ppfd > 800 && rh < 50) { stage = '🍯 Pre-Harvest'; stageRec = 'Spülung, kein N mehr'; }

  // ── Stress-Level ──────────────────────────────────────────────────────────
  let stress = 0;
  if (vpd < 0.4 || vpd > 1.6)   stress += 30;
  if (leafTemp > 30)             stress += 25;
  if (ppfd > 1200)               stress += 20;
  if (soilMoist < 30)           stress += 25;
  stress = Math.min(stress, 100);
  const stressLabel = stress < 20 ? '🟢 Kein Stress' : stress < 50 ? '🟡 Leichter Stress' : '🔴 Hoher Stress – Eingriff nötig';

  // ── Empfehlung (Grower-Tabelle) ───────────────────────────────────────────
  let mainRec = '';
  if (vpd < 0.4)       mainRec = '💧 VPD zu niedrig – Feuchte reduzieren';
  else if (vpd > 1.4)  mainRec = '🌬️ VPD zu hoch – Feuchte erhöhen oder kühlen';
  else if (transpiration < 2) mainRec = '🟢 Sehr entspannt – ideal für Clones';
  else if (transpiration < 4) mainRec = '🟡 Optimal für Veg – perfekt';
  else if (transpiration < 7) mainRec = '🔥 Flower-Modus – alles gut';
  else                 mainRec = '⚠️ Zu hohe Transpiration – Blatt überhitzt';

  // ── Bodenfeuchtigkeit ─────────────────────────────────────────────────────
  let soilRec = soilMoist < 30 ? '⚠️ Trocken – jetzt gießen!'
              : soilMoist < 50 ? '🟡 Etwas trocken'
              : soilMoist < 80 ? '🟢 Optimal'
              : '💧 Zu nass – Drainage prüfen';

  // ── UI Update ─────────────────────────────────────────────────────────────
  document.getElementById('rLeafTemp').textContent = leafTemp + '°';
  document.getElementById('rTrans').textContent    = transpiration;
  document.getElementById('rVPD').textContent      = vpd;
  document.getElementById('rVPDrec').textContent   = vpd < 0.4 ? '🟦 Zu niedrig' : vpd > 1.4 ? '🔴 Zu hoch' : '🟢 Optimal';
  document.getElementById('rChloro').textContent   = chloro;
  document.getElementById('rChloroRec').textContent= chloro > 70 ? '🟢 Gesund' : chloro > 40 ? '🟡 OK' : '🔴 Chlorose – N prüfen';
  document.getElementById('rDLI').textContent      = dli;
  document.getElementById('rDLIrec').textContent   = dli < 15 ? '⬇️ Zu wenig' : dli < 35 ? '🟢 Gut' : '⬆️ Sehr hoch';
  document.getElementById('rStress').textContent   = stressLabel;
  document.getElementById('rStage').textContent    = stage;
  document.getElementById('rStageRec').textContent = stageRec;
  document.getElementById('rSoil').textContent     = soilMoist + '%';
  document.getElementById('rSoilRec').textContent  = soilRec;
  document.getElementById('rMainRec').textContent  = mainRec;

  // Stress-Indikator
  document.getElementById('stressIndicator').style.left = `calc(${stress}% - 2px)`;

  document.getElementById('results').classList.remove('hidden');

  lastResults = { ppfd, lux: currentLux, cct: currentCCT, leafTemp, transpiration, vpd, dli, chloro, stress, stage, soilMoist, ts: new Date().toISOString() };
  updateLivePanel();
}

// ── Plant Age Schätzung ────────────────────────────────────────────────────────
function estimateAge() {
  const germDateVal = document.getElementById('germDate').value;
  const height    = parseFloat(document.getElementById('plantHeight').value)  || 30;
  const nodes     = parseFloat(document.getElementById('nodeCount').value)    || 8;
  const internode = parseFloat(document.getElementById('internode').value)    || 4;

  let ageCalendar = null, ageStr = '';
  if (germDateVal) {
    const diff = (new Date() - new Date(germDateVal)) / (1000*60*60*24);
    ageCalendar = Math.round(diff);
    ageStr += `📅 Kalender: ${ageCalendar} Tage. `;
  }

  // Biologische Schätzung: ~3-4 Tage pro Blattetage, +5 Tage Keimling
  const ageBio = Math.round(nodes * 3.5 + 7);
  // Mathematisch: Wachstumsrate ~0.8-1.2 cm/Tag früh, ~1.5-2.5 cm/Tag später
  const ageMath = Math.round(height / 1.1 + nodes * 2);

  const ageFinal = ageCalendar
    ? Math.round((ageCalendar + ageBio + ageMath) / 3)
    : Math.round((ageBio + ageMath) / 2);

  let detail = `🌿 Bio (Knoten): ~${ageBio}T. 📐 Math (Höhe): ~${ageMath}T.`;
  if (ageCalendar) detail += ` 📅 Kalender: ${ageCalendar}T.`;
  detail += ` → Ø ${ageFinal} Tage`;

  const stage = ageFinal < 14 ? 'Keimling' : ageFinal < 35 ? 'Veg early' : ageFinal < 60 ? 'Veg late' : ageFinal < 100 ? 'Flower' : 'Late Flower';
  detail += ` | Stage: ${stage}`;

  document.getElementById('estAge').textContent   = ageFinal;
  document.getElementById('ageDetail').textContent = detail;
  document.getElementById('ageResult').classList.remove('hidden');
  document.getElementById('lpAge').textContent    = ageFinal;
  document.getElementById('lpStage').textContent  = stage;
}

// ── Live Panel Update ──────────────────────────────────────────────────────────
function updateLivePanel() {
  if (!lastResults || !lastResults.ppfd) return;
  document.getElementById('lpPPFD').textContent  = lastResults.ppfd || currentPPFD;
  document.getElementById('lpLux').textContent   = lastResults.lux  || currentLux;
  document.getElementById('lpLeaf').textContent  = lastResults.leafTemp || '—';
  document.getElementById('lpVPD').textContent   = lastResults.vpd  || '—';
  document.getElementById('lpDLI').textContent   = lastResults.dli  || '—';

  if (document.getElementById('autoLog').checked) {
    sendToBrain();
    document.getElementById('lpLog').textContent = '🧠 ' + new Date().toLocaleTimeString('de');
  }
}

// ── Auto-Log Toggle ────────────────────────────────────────────────────────────
function toggleAutoLog() {
  const on = document.getElementById('autoLog').checked;
  document.getElementById('logStatus').textContent = on
    ? '✅ Logging aktiv – alle 10s ins Brain'
    : '⏸ Logging pausiert';
}

// ── Brain senden ───────────────────────────────────────────────────────────────
function sendToBrain() {
  if (!window.Telegram || !window.Telegram.WebApp) return;
  const payload = { action: 'brain_log', data: lastResults };
  try { window.Telegram.WebApp.sendData(JSON.stringify(payload)); } catch(e) {}
}

function sendToBot() {
  if (!lastResults || !lastResults.ppfd) {
    alert('Bitte erst "Alles berechnen" drücken!');
    return;
  }
  const payload = { action: 'plant_report', data: lastResults };
  if (window.Telegram && window.Telegram.WebApp) {
    window.Telegram.WebApp.sendData(JSON.stringify(payload));
    window.Telegram.WebApp.close();
  } else {
    alert('📊 Messung:\nPPFD: ' + lastResults.ppfd + '\nBlatt: ' + lastResults.leafTemp + '°C\nVPD: ' + lastResults.vpd + ' kPa\nStress: ' + lastResults.stress + '%');
  }
}

window.onload = initSensors;
</script>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
async def planthealth_page(request: Request):
    return HTMLResponse(HTML)

@app.get("/health")
async def health():
    return {"status": "ok", "module": "planthealth"}
