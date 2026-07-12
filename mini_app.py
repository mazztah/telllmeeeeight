# mini_app.py – Queen’s Aura Defense (Telegram Mini App)
# Einfacher Flask-Server mit integriertem HTML/JS-Game

from flask import Flask, render_template_string
import os

app = Flask(__name__)

# ────────────────────────────────────────────────
# KOMPLETTES HTML + CSS + JS (alles in einer Datei)
# ────────────────────────────────────────────────
HTML_CONTENT = """<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
  <title>Queen’s Aura Defense 💖</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    body { margin:0; background:#2a0044; color:#ffccff; font-family:system-ui; overflow:hidden; touch-action:manipulation; }
    canvas { display:block; margin:0 auto; background:#1a0033; }
    #ui { position:absolute; top:10px; left:10px; right:10px; z-index:100; display:flex; justify-content:space-between; font-size:18px; text-shadow:0 2px 4px rgba(0,0,0,0.8); }
    .tower-btn { background:#ff66cc; color:white; border:none; padding:12px 18px; margin:5px; border-radius:999px; font-size:16px; box-shadow:0 4px #c63399; }
    .tower-btn:active { transform:translateY(3px); box-shadow:0 1px; }
    #message { position:absolute; top:50%; left:50%; transform:translate(-50%,-50%); font-size:36px; background:rgba(0,0,0,0.9); padding:30px 60px; border-radius:25px; display:none; text-align:center; box-shadow:0 0 30px #ff66cc; }
  </style>
</head>
<body>
  <div id="ui">
    <div>Aura: <span id="lives">20</span> ❤️ | Sheesh: <span id="coins">250</span> ✨</div>
    <div>Wave: <span id="wave">1</span> 🔥</div>
  </div>

  <div style="position:absolute; bottom:15px; left:10px; z-index:100;">
    <button class="tower-btn" onclick="selectTower(0)">ASMR Whisper (50)</button>
    <button class="tower-btn" onclick="selectTower(1)">Roast Slap (80)</button>
    <button class="tower-btn" onclick="selectTower(2)">Parfüm Cloud (120)</button>
  </div>

  <canvas id="game" width="800" height="500"></canvas>
  <div id="message"></div>

  <script>
    const canvas = document.getElementById('game');
    const ctx = canvas.getContext('2d');
    const tg = window.Telegram.WebApp;
    tg.expand();
    tg.ready();

    let lives = 20, coins = 250, wave = 1, selectedTower = -1;
    let enemies = [], towers = [], projectiles = [];

    const path = [
      {x:40, y:250}, {x:220, y:250}, {x:220, y:110},
      {x:520, y:110}, {x:520, y:390}, {x:760, y:390}
    ];

    class Enemy {
      constructor() {
        this.x = path[0].x; this.y = path[0].y;
        this.hp = 90 + wave * 28;
        this.maxHp = this.hp;
        this.speed = 1.35;
        this.pathIndex = 0;
        this.reward = 18 + wave * 4;
      }
      update() {
        if (this.pathIndex >= path.length-1) return;
        const t = path[this.pathIndex + 1];
        const dx = t.x - this.x;
        const dy = t.y - this.y;
        const dist = Math.hypot(dx, dy);
        if (dist < 10) { this.pathIndex++; return; }
        this.x += (dx / dist) * this.speed;
        this.y += (dy / dist) * this.speed;
      }
      draw() {
        ctx.fillStyle = '#ff3366';
        ctx.fillRect(this.x-19, this.y-19, 38, 38);
        ctx.fillStyle = '#fff';
        ctx.font = '24px sans-serif';
        ctx.fillText('👟', this.x-13, this.y+9);
        // HP-Bar
        const w = 38 * (this.hp / this.maxHp);
        ctx.fillStyle = this.hp > 40 ? '#00ff88' : '#ff0000';
        ctx.fillRect(this.x-19, this.y-30, w, 6);
      }
    }

    class Tower {
      constructor(x, y, type) {
        this.x = Math.round(x/40)*40;
        this.y = Math.round(y/40)*40;
        this.type = type;
        this.range = [140, 150, 190][type];
        this.damage = [20, 45, 14][type];
        this.cooldown = 0;
        this.fireRate = [22, 38, 14][type];
      }
      update() {
        if (this.cooldown-- > 0) return;
        for (let e of enemies) {
          if (Math.hypot(e.x - this.x, e.y - this.y) < this.range) {
            projectiles.push({x:this.x, y:this.y, tx:e.x, ty:e.y, damage:this.damage, type:this.type});
            this.cooldown = this.fireRate;
            break;
          }
        }
      }
      draw() {
        const colors = ['#88ffff', '#ff88ff', '#ffff88'];
        ctx.fillStyle = colors[this.type];
        ctx.fillRect(this.x-23, this.y-23, 46, 46);
        ctx.fillStyle = '#fff';
        ctx.font = '30px sans-serif';
        ctx.fillText(['💨','👑','🌸'][this.type], this.x-16, this.y+12);
      }
    }

    function gameLoop() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Path (pink carpet)
      ctx.strokeStyle = '#ff66cc';
      ctx.lineWidth = 58;
      ctx.lineJoin = 'round';
      ctx.beginPath();
      ctx.moveTo(path[0].x, path[0].y);
      path.forEach(p => ctx.lineTo(p.x, p.y));
      ctx.stroke();

      // Enemies
      for (let i = enemies.length-1; i >= 0; i--) {
        const e = enemies[i];
        e.update();
        e.draw();

        if (e.x > 780) {
          lives--;
          document.getElementById('lives').textContent = lives;
          enemies.splice(i, 1);
          if (lives <= 0) showMessage("Aura verloren... du wurdest cooked 😭💀", "#ff3366");
        } else if (e.hp <= 0) {
          coins += e.reward;
          enemies.splice(i, 1);
        }
      }

      // Towers
      towers.forEach(t => { t.update(); t.draw(); });

      // Projectiles
      for (let i = projectiles.length-1; i >= 0; i--) {
        const p = projectiles[i];
        ctx.fillStyle = p.type === 2 ? '#ffff66' : '#ff99ff';
        ctx.fillRect(p.x-5, p.y-5, 10, 10);
        p.x += (p.tx - p.x) * 0.28;
        p.y += (p.ty - p.y) * 0.28;
        if (Math.hypot(p.x - p.tx, p.y - p.ty) < 15) projectiles.splice(i,1);
      }

      // Spawn enemy
      if (Math.random() < 0.028 + wave * 0.009) enemies.push(new Enemy());

      // Wave progress
      if (enemies.length === 0 && Math.random() < 0.018) {
        wave++;
        document.getElementById('wave').textContent = wave;
        coins += 35;
      }

      document.getElementById('coins').textContent = coins;

      requestAnimationFrame(gameLoop);
    }

    canvas.addEventListener('click', e => {
      if (selectedTower < 0) return;
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      const costs = [50, 80, 120];
      if (coins >= costs[selectedTower]) {
        towers.push(new Tower(x, y, selectedTower));
        coins -= costs[selectedTower];
      }
    });

    window.selectTower = t => { selectedTower = t; };

    function showMessage(text, color = "#ffccff") {
      const msg = document.getElementById('message');
      msg.textContent = text;
      msg.style.color = color;
      msg.style.display = 'block';
      setTimeout(() => { msg.style.display = 'none'; }, 4500);
    }

    // Telegram Main Button
    tg.MainButton.setText("Nächste Wave erzwingen 💥");
    tg.MainButton.show();
    tg.MainButton.onClick(() => { wave++; coins += 50; });

    gameLoop();
  </script>
</body>
</html>
"""

@app.route('/')
def aura_defense():
    return render_template_string(HTML_CONTENT)

# Optional: falls du später statische Dateien (Bilder, Sounds) brauchst
@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename) if os.path.exists('static') else "No static folder"

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
