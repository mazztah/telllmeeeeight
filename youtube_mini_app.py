# youtube_mini_app.py – DYNAMISCHE VERSION (empfängt Daten vom Bot)
from fastapi.responses import HTMLResponse
from fastapi import FastAPI, Request

app = FastAPI()

HTML = """<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Queen’s Crystal Ball ✨</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&family=Poppins:wght@400;600&display=swap');
    body { margin:0; overflow:hidden; background:radial-gradient(circle at center, #4a0077, #1a0033); color:#ffccff; font-family:'Poppins',sans-serif; height:100vh; }
    .scene { perspective:1500px; height:100vh; overflow-y:auto; position:relative; }
    .layer { position:absolute; width:100%; transition:transform 0.4s cubic-bezier(0.25,0.1,0.25,1); }
    .orb { position:absolute; border-radius:50%; filter:blur(20px); animation: floatOrb 12s infinite ease-in-out; }
    @keyframes floatOrb { 0%,100%{transform:translateY(0) rotate(0deg);} 50%{transform:translateY(-80px) rotate(180deg);} }
    .glow { animation: queenGlow 3s infinite alternate; }
    .card { background:rgba(255,255,255,0.1); backdrop-filter:blur(20px); border:2px solid rgba(255,102,204,0.4); border-radius:25px; padding:25px; box-shadow:0 0 60px rgba(255,102,204,0.6); }
  </style>
</head>
<body>
  <div class="scene" id="scene">
    <div class="layer" id="bg1" style="height:140%; background:radial-gradient(circle, #ff66cc22, transparent); z-index:1;"></div>
    <div class="layer" id="bg2" style="height:160%; background:linear-gradient(transparent, #ff66cc11); z-index:2; top:20%;"></div>
    
    <div class="orb" style="width:120px;height:120px;background:#ff66cc; top:15%; left:10%; animation-delay:0s;"></div>
    <div class="orb" style="width:80px;height:80px;background:#ffff66; top:40%; right:15%; animation-delay:3s;"></div>
    <div class="orb" style="width:150px;height:150px;background:#66ffff; bottom:20%; left:25%; animation-delay:6s;"></div>

    <div class="layer" style="top:8%; z-index:10; text-align:center;">
      <h1 class="glow" style="font-family:'Playfair Display',serif; font-size:3.2rem; margin:0; text-shadow:0 0 40px #ff66cc;">Queen’s Crystal Ball</h1>
      <div id="content" class="card" style="margin:30px auto; max-width:720px;"></div>
    </div>
  </div>

  <script>
    const tg = window.Telegram.WebApp;
    tg.expand();

    // Parallax Effekt
    const scene = document.getElementById('scene');
    scene.addEventListener('scroll', () => {
      const scroll = scene.scrollTop;
      document.getElementById('bg1').style.transform = `translateZ(-300px) translateY(${scroll * 0.6}px)`;
      document.getElementById('bg2').style.transform = `translateZ(-200px) translateY(${scroll * 0.4}px)`;
    });

    // Daten aus URL-Parametern lesen (vom Bot übergeben)
    function getUrlParams() {
      const params = new URLSearchParams(window.location.search);
      return {
        title: params.get('title') || "Queen’s Crystal Ball",
        text: params.get('text') || "Warte auf Analyse... ✨"
      };
    }

    const data = getUrlParams();

    document.getElementById('content').innerHTML = `
      <h2 style="margin:0 0 15px 0; font-size:1.8rem;">${data.title}</h2>
      <p style="white-space:pre-wrap; line-height:1.6; font-size:1.1rem;">${data.text}</p>
      <div style="margin-top:25px; display:flex; gap:12px; flex-wrap:wrap; justify-content:center;">
        <button onclick="downloadFile('pdf')" class="card" style="padding:14px 28px; border-radius:999px;">📄 PDF</button>
        <button onclick="downloadFile('txt')" class="card" style="padding:14px 28px; border-radius:999px;">📜 TXT</button>
        <button onclick="downloadFile('srt')" class="card" style="padding:14px 28px; border-radius:999px;">⏱️ SRT</button>
      </div>
    `;

    function downloadFile(type) {
      alert(`✨ ${type.toUpperCase()} wird für dich generiert, Queen...`);
      // Hier später echte Download-Funktion möglich
    }
  </script>
</body>
</html>
"""

@app.get("/")
async def crystal_ball(request: Request):
    return HTMLResponse(HTML)
