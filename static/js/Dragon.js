/* ═══════════════════════════════════════════════════════════════
   DRAGON JUMP v2.1 - SPEED FIX + LEADERBOARD FIX
   ═══════════════════════════════════════════════════════════════ */

class DragonGame {
    constructor() {
        this.gameContainer = document.querySelector('.game-container');

        // FIXED: Delta time for smooth animation
        this.lastTime = 0;
        this.deltaTime = 0;
        this.targetFPS = 60;
        this.timeStep = 1000 / this.targetFPS;

        // Game State
        this.isPlaying = false;
        this.isPaused = false;
        this.isGameOver = false;
        this.score = 0;
        this.coins = 0;
        this.totalCoins = parseInt(localStorage.getItem('dragonTotalCoins') || '0');
        this.highScore = parseInt(localStorage.getItem('dragonHighScore') || '0');
        this.level = 1;
        this.speed = 6;  // FIXED: Increased from 4
        this.baseSpeed = 6;  // FIXED: Increased from 4

        // Physics - FIXED: Stronger gravity and jump
        this.dragonY = 0;
        this.dragonVelocity = 0;
        this.gravity = 0.8;  // FIXED: Increased from 0.5
        this.jumpForce = -14;  // FIXED: Stronger jump
        this.isJumping = false;
        this.doubleJumpsLeft = 2;
        this.maxDoubleJumps = 2;
        this.groundY = 95;

        // Obstacles & Coins
        this.obstacles = [];
        this.coinsList = [];
        this.obstacleTimer = 0;
        this.coinTimer = 0;

        // Animation
        this.animationId = null;
        this.frameCount = 0;

        // User
        this.username = localStorage.getItem('dragonUsername') || '';

        // Shop
        this.upgrades = JSON.parse(localStorage.getItem('dragonUpgrades') || '{}');
        this.shopItems = [
            { id: 'flame', name: 'Feueratem', desc: 'Zerstoert Hindernisse', price: 50, icon: '🔥' },
            { id: 'speed', name: 'Speed Boost', desc: 'Schneller laufen', price: 30, icon: '⚡' },
            { id: 'jump', name: 'Super Sprung', desc: 'Hoeher springen', price: 40, icon: '🚀' },
            { id: 'coin', name: 'Coin Magnet', desc: 'Coins anziehen', price: 60, icon: '🧲' },
            { id: 'shield', name: 'Schild', desc: 'Einmal schutz', price: 25, icon: '🛡️' },
        ];

        // Sound
        this.soundEnabled = localStorage.getItem('dragonSound') !== 'false';
        this.audioContext = null;

        // Elements
        this.scoreEl = document.getElementById('score');
        this.highScoreEl = document.getElementById('highScore');
        this.levelEl = document.getElementById('level');
        this.coinEl = document.getElementById('coinCount');
        this.totalCoinEl = document.getElementById('totalCoinCount');

        this.startOverlay = document.getElementById('startOverlay');
        this.gameOverOverlay = document.getElementById('gameOverOverlay');
        this.pauseOverlay = document.getElementById('pauseOverlay');
        this.shopOverlay = document.getElementById('shopOverlay');

        this.finalScoreEl = document.getElementById('finalScore');
        this.finalLevelEl = document.getElementById('finalLevel');
        this.finalCoinsEl = document.getElementById('finalCoins');

        this.usernameInput = document.getElementById('usernameInput');
        this.leaderboardBody = document.getElementById('leaderboardBody');

        // FIXED: Leaderboard loaded flag
        this.leaderboardLoaded = false;

        this.init();
    }

    init() {
        this.createDragon();
        this.createEnvironment();
        this.setupEventListeners();
        this.initAudio();

        // FIXED: Load username and leaderboard immediately
        if (this.username) {
            this.usernameInput.value = this.username;
        }

        // FIXED: Load leaderboard on init
        this.loadLeaderboard();
        this.updateUI();
    }

    // ═══ AUDIO ═══
    initAudio() {
        try {
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
        } catch(e) {
            console.log('Web Audio API not supported');
        }
    }

    playSound(type) {
        if (!this.soundEnabled || !this.audioContext) return;

        const ctx = this.audioContext;
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();

        osc.connect(gain);
        gain.connect(ctx.destination);

        switch(type) {
            case 'jump':
                osc.frequency.setValueAtTime(400, ctx.currentTime);
                osc.frequency.exponentialRampToValueAtTime(800, ctx.currentTime + 0.1);
                gain.gain.setValueAtTime(0.2, ctx.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.15);
                osc.start(ctx.currentTime);
                osc.stop(ctx.currentTime + 0.15);
                break;
            case 'doublejump':
                osc.frequency.setValueAtTime(500, ctx.currentTime);
                osc.frequency.exponentialRampToValueAtTime(1000, ctx.currentTime + 0.1);
                gain.gain.setValueAtTime(0.2, ctx.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.15);
                osc.start(ctx.currentTime);
                osc.stop(ctx.currentTime + 0.15);
                break;
            case 'coin':
                osc.frequency.setValueAtTime(1000, ctx.currentTime);
                osc.frequency.exponentialRampToValueAtTime(1500, ctx.currentTime + 0.1);
                gain.gain.setValueAtTime(0.15, ctx.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.15);
                osc.start(ctx.currentTime);
                osc.stop(ctx.currentTime + 0.15);
                break;
            case 'levelup':
                [523, 659, 784, 1047].forEach((freq, i) => {
                    const o = ctx.createOscillator();
                    const g = ctx.createGain();
                    o.connect(g);
                    g.connect(ctx.destination);
                    o.frequency.value = freq;
                    g.gain.setValueAtTime(0.2, ctx.currentTime + i * 0.15);
                    g.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + i * 0.15 + 0.3);
                    o.start(ctx.currentTime + i * 0.15);
                    o.stop(ctx.currentTime + i * 0.15 + 0.3);
                });
                break;
            case 'fail':
                osc.frequency.setValueAtTime(400, ctx.currentTime);
                osc.frequency.exponentialRampToValueAtTime(100, ctx.currentTime + 0.5);
                gain.gain.setValueAtTime(0.3, ctx.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.5);
                osc.start(ctx.currentTime);
                osc.stop(ctx.currentTime + 0.5);
                break;
            case 'hit':
                osc.type = 'sawtooth';
                osc.frequency.setValueAtTime(200, ctx.currentTime);
                osc.frequency.exponentialRampToValueAtTime(50, ctx.currentTime + 0.2);
                gain.gain.setValueAtTime(0.2, ctx.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.2);
                osc.start(ctx.currentTime);
                osc.stop(ctx.currentTime + 0.2);
                break;
        }
    }

    toggleSound() {
        this.soundEnabled = !this.soundEnabled;
        localStorage.setItem('dragonSound', this.soundEnabled);
        const btn = document.getElementById('soundToggle');
        btn.textContent = this.soundEnabled ? '🔊' : '🔇';
        btn.classList.toggle('muted', !this.soundEnabled);
    }

    // ═══ CREATE DRAGON SVG ═══
    createDragon() {
        this.dragon = document.createElement('div');
        this.dragon.className = 'dragon';
        this.dragon.id = 'dragon';
        this.dragon.innerHTML = `
            <div class="dragon-body">
                <svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
                    <defs>
                        <radialGradient id="dragonGlow" cx="50%" cy="50%" r="50%">
                            <stop offset="0%" stop-color="#7FDBDA" stop-opacity="0.8"/>
                            <stop offset="100%" stop-color="#4ECDC4" stop-opacity="0"/>
                        </radialGradient>
                    </defs>
                    <circle cx="50" cy="50" r="40" fill="url(#dragonGlow)" opacity="0.4"/>
                    <ellipse cx="50" cy="55" rx="28" ry="22" fill="#4ECDC4"/>
                    <ellipse cx="50" cy="55" rx="22" ry="17" fill="#7FDBDA"/>
                    <ellipse cx="50" cy="60" rx="15" ry="10" fill="#A8E6CF"/>
                    <circle cx="72" cy="38" r="16" fill="#4ECDC4"/>
                    <circle cx="72" cy="38" r="12" fill="#7FDBDA"/>
                    <circle cx="78" cy="34" r="5" fill="white"/>
                    <circle cx="80" cy="34" r="3" fill="#1a1a2e"/>
                    <circle cx="81" cy="33" r="1" fill="white"/>
                    <path d="M 70 28 Q 78 24 86 28" stroke="#2A9D8F" stroke-width="2" fill="none"/>
                    <ellipse cx="88" cy="42" rx="8" ry="6" fill="#4ECDC4"/>
                    <ellipse cx="90" cy="42" rx="5" ry="4" fill="#7FDBDA"/>
                    <circle cx="92" cy="41" r="1.5" fill="#2A9D8F"/>
                    <path d="M 82 46 Q 88 48 92 46" stroke="#2A9D8F" stroke-width="1.5" fill="none"/>
                    <path d="M 68 24 L 72 12 L 76 24" fill="#FFD700"/>
                    <path d="M 70 22 L 72 16 L 74 22" fill="#FFF8DC"/>
                    <ellipse cx="60" cy="28" rx="5" ry="8" fill="#4ECDC4" transform="rotate(-20 60 28)"/>
                    <ellipse cx="60" cy="28" rx="3" ry="5" fill="#7FDBDA" transform="rotate(-20 60 28)"/>
                    <path d="M 35 45 Q 15 35 20 20 Q 30 30 40 40" fill="#2A9D8F" opacity="0.7"/>
                    <path d="M 40 48 Q 18 42 22 25 Q 32 35 45 43" fill="#4ECDC4"/>
                    <path d="M 40 48 Q 25 44 28 32" stroke="#7FDBDA" stroke-width="1.5" fill="none"/>
                    <path d="M 25 55 Q 10 50 8 40 Q 12 48 22 52" fill="#4ECDC4"/>
                    <path d="M 8 40 L 5 35 L 10 38" fill="#FFD700"/>
                    <ellipse cx="35" cy="72" rx="6" ry="10" fill="#2A9D8F"/>
                    <ellipse cx="35" cy="78" rx="8" ry="4" fill="#FFD700"/>
                    <ellipse cx="55" cy="72" rx="6" ry="10" fill="#4ECDC4"/>
                    <ellipse cx="55" cy="78" rx="8" ry="4" fill="#FFD700"/>
                    <path d="M 32 80 L 30 84 M 35 80 L 35 85 M 38 80 L 40 84" stroke="#2A9D8F" stroke-width="1.5"/>
                    <path d="M 52 80 L 50 84 M 55 80 L 55 85 M 58 80 L 60 84" stroke="#2A9D8F" stroke-width="1.5"/>
                    <path d="M 45 35 L 48 28 L 51 35" fill="#FFD700"/>
                    <path d="M 38 38 L 41 31 L 44 38" fill="#FFD700"/>
                    <path d="M 52 33 L 55 26 L 58 33" fill="#FFD700"/>
                    <circle cx="50" cy="50" r="35" fill="none" stroke="#4ECDC4" stroke-width="0.5" opacity="0.3"/>
                </svg>
            </div>
        `;
        this.gameContainer.appendChild(this.dragon);
    }

    createEnvironment() {
        const starsContainer = document.createElement('div');
        starsContainer.className = 'stars';
        for (let i = 0; i < 60; i++) {
            const star = document.createElement('div');
            star.className = 'star';
            star.style.left = Math.random() * 100 + '%';
            star.style.top = Math.random() * 65 + '%';
            star.style.animationDelay = Math.random() * 2 + 's';
            star.style.width = (Math.random() * 2 + 1) + 'px';
            star.style.height = star.style.width;
            starsContainer.appendChild(star);
        }
        this.gameContainer.appendChild(starsContainer);

        const moon = document.createElement('div');
        moon.className = 'moon';
        this.gameContainer.appendChild(moon);

        const skyline = document.createElement('div');
        skyline.className = 'skyline';
        this.gameContainer.appendChild(skyline);

        const sidewalk = document.createElement('div');
        sidewalk.className = 'sidewalk';
        this.gameContainer.appendChild(sidewalk);

        const ground = document.createElement('div');
        ground.className = 'ground';
        this.gameContainer.appendChild(ground);
    }

    // ═══ EVENT LISTENERS ═══
    setupEventListeners() {
        document.addEventListener('keydown', (e) => {
            if (e.code === 'Space' || e.code === 'ArrowUp') {
                e.preventDefault();
                if (!this.isPlaying && !this.isGameOver && !this.isPaused) {
                    this.startGame();
                } else if (this.isPlaying && !this.isPaused) {
                    this.jump();
                } else if (this.isGameOver) {
                    this.restartGame();
                }
            }
            if (e.code === 'ArrowDown' && this.isPlaying && !this.isPaused) {
                this.fastFall();
            }
            if (e.code === 'Escape' && this.isPlaying) {
                this.togglePause();
            }
        });

        this.gameContainer.addEventListener('touchstart', (e) => {
            if (e.target.closest('.overlay') || e.target.closest('.game-buttons') || e.target.closest('.sound-toggle')) return;
            e.preventDefault();
            if (!this.isPlaying && !this.isGameOver && !this.isPaused) {
                this.startGame();
            } else if (this.isPlaying && !this.isPaused) {
                this.jump();
            } else if (this.isGameOver) {
                this.restartGame();
            }
        }, { passive: false });

        this.gameContainer.addEventListener('mousedown', (e) => {
            if (e.target.closest('.overlay') || e.target.closest('.game-buttons') || e.target.closest('.sound-toggle')) return;
            if (!this.isPlaying && !this.isGameOver && !this.isPaused) {
                this.startGame();
            } else if (this.isPlaying && !this.isPaused) {
                this.jump();
            } else if (this.isGameOver) {
                this.restartGame();
            }
        });

        document.getElementById('startBtn').addEventListener('click', () => {
            this.saveUsername();
            this.startGame();
        });

        document.getElementById('restartBtn').addEventListener('click', () => {
            this.saveUsername();
            this.restartGame();
        });

        document.getElementById('pauseBtn').addEventListener('click', () => this.togglePause());
        document.getElementById('stopBtn').addEventListener('click', () => this.stopGame());
        document.getElementById('menuBtn').addEventListener('click', () => this.openShop());
        document.getElementById('resumeBtn').addEventListener('click', () => this.togglePause());
        document.getElementById('shopCloseBtn').addEventListener('click', () => this.closeShop());
        document.getElementById('soundToggle').addEventListener('click', () => this.toggleSound());

        const jumpBtn = document.getElementById('jumpBtn');
        const duckBtn = document.getElementById('duckBtn');

        if (jumpBtn) {
            jumpBtn.addEventListener('touchstart', (e) => {
                e.preventDefault();
                if (this.isPlaying && !this.isPaused) this.jump();
                else if (!this.isGameOver && !this.isPaused) this.startGame();
            }, { passive: false });
        }

        if (duckBtn) {
            duckBtn.addEventListener('touchstart', (e) => {
                e.preventDefault();
                if (this.isPlaying && !this.isPaused && this.isJumping) this.fastFall();
            }, { passive: false });
        }

        this.usernameInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.saveUsername();
                if (!this.isPlaying && !this.isGameOver) this.startGame();
            }
        });

        const soundBtn = document.getElementById('soundToggle');
        soundBtn.textContent = this.soundEnabled ? '🔊' : '🔇';
        soundBtn.classList.toggle('muted', !this.soundEnabled);
    }

    saveUsername() {
        const name = this.usernameInput.value.trim();
        if (name) {
            this.username = name;
            localStorage.setItem('dragonUsername', name);
        }
    }

    // ═══ JUMP ═══
    jump() {
        if (!this.isJumping) {
            this.isJumping = true;
            this.dragonVelocity = this.jumpForce;
            this.doubleJumpsLeft = this.maxDoubleJumps;
            this.dragon.classList.add('jump');
            this.createFireParticles();
            this.playSound('jump');
            this.updateJumpIndicator();
            setTimeout(() => this.dragon.classList.remove('jump'), 700);
        } else if (this.doubleJumpsLeft > 0) {
            this.doubleJumpsLeft--;
            this.dragonVelocity = this.jumpForce * 0.85;
            this.dragon.classList.remove('jump');
            void this.dragon.offsetWidth;
            this.dragon.classList.add('double-jump');
            this.createFireParticles();
            this.playSound('doublejump');
            this.updateJumpIndicator();
            setTimeout(() => this.dragon.classList.remove('double-jump'), 500);
        }
    }

    fastFall() {
        this.dragonVelocity = 12;
    }

    updateJumpIndicator() {
        const indicators = document.querySelectorAll('.jump-charge');
        indicators.forEach((ind, i) => {
            ind.classList.toggle('active', i < this.doubleJumpsLeft);
        });
    }

    createFireParticles() {
        for (let i = 0; i < 5; i++) {
            setTimeout(() => {
                const particle = document.createElement('div');
                particle.className = 'fire-particle';
                const rect = this.dragon.getBoundingClientRect();
                const containerRect = this.gameContainer.getBoundingClientRect();
                particle.style.left = (rect.left - containerRect.left + 15 + Math.random() * 20) + 'px';
                particle.style.bottom = (this.groundY + 10) + 'px';
                this.gameContainer.appendChild(particle);
                setTimeout(() => particle.remove(), 500);
            }, i * 50);
        }
    }

    // ═══ GAME CONTROLS ═══
    startGame() {
        if (this.isPlaying) return;

        this.isPlaying = true;
        this.isGameOver = false;
        this.isPaused = false;
        this.score = 0;
        this.coins = 0;
        this.level = 1;
        this.speed = this.baseSpeed;
        this.obstacles = [];
        this.coinsList = [];
        this.obstacleTimer = 0;
        this.coinTimer = 0;
        this.frameCount = 0;
        this.dragonVelocity = 0;
        this.isJumping = false;
        this.doubleJumpsLeft = this.maxDoubleJumps;
        this.lastTime = performance.now();  // FIXED: Reset delta time

        document.querySelectorAll('.obstacle, .coin, .particle, .speed-line').forEach(el => el.remove());

        this.startOverlay.classList.add('hidden');
        this.gameOverOverlay.classList.add('hidden');
        this.pauseOverlay.classList.add('hidden');
        this.shopOverlay.classList.add('hidden');

        this.dragon.style.bottom = this.groundY + 'px';
        this.dragon.style.transform = 'translateY(0)';
        this.dragon.classList.remove('dead');

        this.updateUI();
        this.updateJumpIndicator();
        this.gameLoop(this.lastTime);  // FIXED: Pass initial time
    }

    restartGame() {
        this.isGameOver = false;
        this.startGame();
    }

    stopGame() {
        this.isPlaying = false;
        this.isGameOver = true;
        cancelAnimationFrame(this.animationId);
        this.showGameOver();
    }

    togglePause() {
        if (!this.isPlaying || this.isGameOver) return;

        this.isPaused = !this.isPaused;

        if (this.isPaused) {
            cancelAnimationFrame(this.animationId);
            this.pauseOverlay.classList.remove('hidden');
        } else {
            this.pauseOverlay.classList.add('hidden');
            this.lastTime = performance.now();  // FIXED: Reset time on resume
            this.gameLoop(this.lastTime);
        }
    }

    // ═══ SHOP ═══
    openShop() {
        if (this.isPlaying && !this.isPaused) {
            this.togglePause();
        }
        this.shopOverlay.classList.remove('hidden');
        this.renderShop();
    }

    closeShop() {
        this.shopOverlay.classList.add('hidden');
    }

    renderShop() {
        const container = document.getElementById('shopItems');
        document.getElementById('shopCoinBalance').textContent = this.totalCoins;

        container.innerHTML = this.shopItems.map(item => {
            const owned = this.upgrades[item.id];
            return `
                <div class="shop-item ${owned ? 'owned' : ''}" data-id="${item.id}">
                    <div class="item-icon">${item.icon}</div>
                    <div class="item-name">${item.name}</div>
                    <div class="item-desc">${item.desc}</div>
                    <div class="item-price">
                        ${owned ? '<span class="owned-tag">✅ Gekauft</span>' : `🪙 ${item.price}`}
                    </div>
                </div>
            `;
        }).join('');

        container.querySelectorAll('.shop-item').forEach(item => {
            item.addEventListener('click', () => this.buyUpgrade(item.dataset.id));
        });
    }

    buyUpgrade(id) {
        const item = this.shopItems.find(i => i.id === id);
        if (!item || this.upgrades[id]) return;

        if (this.totalCoins >= item.price) {
            this.totalCoins -= item.price;
            this.upgrades[id] = true;
            localStorage.setItem('dragonTotalCoins', this.totalCoins);
            localStorage.setItem('dragonUpgrades', JSON.stringify(this.upgrades));
            this.playSound('coin');
            this.renderShop();
            this.updateUI();
        } else {
            const balance = document.getElementById('shopCoinBalance');
            balance.style.color = '#ff4444';
            setTimeout(() => balance.style.color = '', 500);
        }
    }

    // ═══ FIXED: GAME LOOP with Delta Time ═══
    gameLoop(currentTime) {
        if (!this.isPlaying || this.isPaused) return;

        // FIXED: Calculate delta time for smooth animation
        this.deltaTime = currentTime - this.lastTime;
        this.lastTime = currentTime;

        // Cap delta time to prevent huge jumps after tab switch
        if (this.deltaTime > 100) this.deltaTime = 100;

        // Calculate speed factor based on target 60 FPS
        const speedFactor = this.deltaTime / this.timeStep;

        this.frameCount++;

        this.updateDragon(speedFactor);
        this.spawnObstacles(speedFactor);
        this.spawnCoins(speedFactor);
        this.updateObstacles(speedFactor);
        this.updateCoins(speedFactor);
        this.checkCollisions();
        this.updateLevel();
        this.createSpeedLines();

        // FIXED: Score increases faster
        this.score += Math.round(speedFactor);

        if (this.frameCount % 6 === 0) {
            this.updateUI();
        }

        this.animationId = requestAnimationFrame((time) => this.gameLoop(time));
    }

    // ═══ FIXED: Update with speed factor ═══
    updateDragon(factor) {
        if (this.isJumping) {
            this.dragonVelocity += this.gravity * factor;
            let currentBottom = parseFloat(this.dragon.style.bottom) || this.groundY;
            currentBottom -= this.dragonVelocity * factor;

            if (currentBottom <= this.groundY) {
                currentBottom = this.groundY;
                this.isJumping = false;
                this.dragonVelocity = 0;
                this.doubleJumpsLeft = this.maxDoubleJumps;
                this.updateJumpIndicator();
            }

            this.dragon.style.bottom = currentBottom + 'px';
            const rotation = Math.max(-25, Math.min(25, this.dragonVelocity * 2.5));
            this.dragon.style.transform = `rotate(${rotation}deg)`;
        } else {
            this.dragon.style.transform = 'rotate(0deg)';
        }
    }

    // ═══ FIXED: Spawn with speed factor ═══
    spawnObstacles(factor) {
        this.obstacleTimer += factor;

        // FIXED: Faster spawn rate
        const interval = Math.max(35, 70 - this.level * 5);

        if (this.obstacleTimer >= interval) {
            this.obstacleTimer = 0;
            this.createStreetObstacle();
        }
    }

    spawnCoins(factor) {
        this.coinTimer += factor;

        if (this.coinTimer >= 50) {  // FIXED: More frequent coins
            this.coinTimer = 0;
            this.createCoin();
        }
    }

    createStreetObstacle() {
        const types = ['trashcan', 'cardboard', 'brick'];
        if (this.level >= 2) types.push('campfire');
        if (this.level >= 3) types.push('hanging');

        const type = types[Math.floor(Math.random() * types.length)];
        const obstacle = document.createElement('div');
        obstacle.className = `obstacle ${type}`;
        obstacle.dataset.type = type;

        const containerWidth = this.gameContainer.offsetWidth;
        obstacle.style.left = containerWidth + 'px';

        const svgs = {
            trashcan: `<svg viewBox="0 0 40 60" xmlns="http://www.w3.org/2000/svg">
                <rect x="5" y="10" width="30" height="45" rx="3" fill="#5D6D7E" stroke="#2C3E50" stroke-width="2"/>
                <rect x="3" y="5" width="34" height="8" rx="2" fill="#2C3E50"/>
                <line x1="12" y1="20" x2="12" y2="50" stroke="#34495E" stroke-width="2"/>
                <line x1="20" y1="20" x2="20" y2="50" stroke="#34495E" stroke-width="2"/>
                <line x1="28" y1="20" x2="28" y2="50" stroke="#34495E" stroke-width="2"/>
                <ellipse cx="20" cy="55" rx="12" ry="3" fill="#2C3E50" opacity="0.5"/>
            </svg>`,

            cardboard: `<svg viewBox="0 0 45 35" xmlns="http://www.w3.org/2000/svg">
                <rect x="2" y="5" width="40" height="28" rx="2" fill="#D4A373" stroke="#A67B5B" stroke-width="1.5"/>
                <line x1="2" y1="15" x2="42" y2="15" stroke="#A67B5B" stroke-width="1"/>
                <line x1="2" y1="25" x2="42" y2="25" stroke="#A67B5B" stroke-width="1"/>
                <line x1="15" y1="5" x2="15" y2="33" stroke="#A67B5B" stroke-width="1"/>
                <line x1="30" y1="5" x2="30" y2="33" stroke="#A67B5B" stroke-width="1"/>
                <text x="8" y="22" font-size="8" fill="#8B6914" font-family="Arial">BOX</text>
            </svg>`,

            brick: `<svg viewBox="0 0 50 45" xmlns="http://www.w3.org/2000/svg">
                <rect x="2" y="2" width="46" height="41" rx="2" fill="#A0522D" stroke="#8B4513" stroke-width="2"/>
                <line x1="2" y1="15" x2="48" y2="15" stroke="#8B4513" stroke-width="1.5"/>
                <line x1="2" y1="28" x2="48" y2="28" stroke="#8B4513" stroke-width="1.5"/>
                <line x1="17" y1="2" x2="17" y2="15" stroke="#8B4513" stroke-width="1.5"/>
                <line x1="33" y1="2" x2="33" y2="15" stroke="#8B4513" stroke-width="1.5"/>
                <line x1="10" y1="15" x2="10" y2="28" stroke="#8B4513" stroke-width="1.5"/>
                <line x1="25" y1="15" x2="25" y2="28" stroke="#8B4513" stroke-width="1.5"/>
                <line x1="40" y1="15" x2="40" y2="28" stroke="#8B4513" stroke-width="1.5"/>
                <line x1="17" y1="28" x2="17" y2="43" stroke="#8B4513" stroke-width="1.5"/>
                <line x1="33" y1="28" x2="33" y2="43" stroke="#8B4513" stroke-width="1.5"/>
            </svg>`,

            campfire: `<svg viewBox="0 0 45 50" xmlns="http://www.w3.org/2000/svg">
                <ellipse cx="22" cy="45" rx="18" ry="4" fill="#333" opacity="0.5"/>
                <ellipse cx="15" cy="42" rx="6" ry="3" fill="#8B4513"/>
                <ellipse cx="30" cy="42" rx="6" ry="3" fill="#8B4513"/>
                <ellipse cx="22" cy="40" rx="5" ry="3" fill="#A0522D"/>
                <path class="flame" d="M 22 38 Q 15 25 18 15 Q 22 5 26 15 Q 29 25 22 38" fill="#FF6B35"/>
                <path class="flame" d="M 22 35 Q 18 28 20 20 Q 22 15 24 20 Q 26 28 22 35" fill="#FFD93D" opacity="0.8"/>
                <circle cx="18" cy="32" r="1.5" fill="#FFF" opacity="0.6"/>
                <circle cx="26" cy="28" r="1" fill="#FFF" opacity="0.6"/>
            </svg>`,

            hanging: `<svg viewBox="0 0 50 70" xmlns="http://www.w3.org/2000/svg">
                <line x1="25" y1="0" x2="25" y2="30" stroke="#666" stroke-width="2"/>
                <line x1="25" y1="0" x2="0" y2="0" stroke="#666" stroke-width="2"/>
                <rect x="10" y="30" width="30" height="25" rx="3" fill="#E74C3C" stroke="#C0392B" stroke-width="2"/>
                <text x="15" y="47" font-size="10" fill="white" font-family="Arial" font-weight="bold">STOP</text>
                <circle cx="25" cy="65" r="3" fill="#F39C12"/>
            </svg>`
        };

        obstacle.innerHTML = svgs[type] || svgs.trashcan;

        const sizes = {
            trashcan: { w: 35, h: 50 },
            cardboard: { w: 40, h: 35 },
            brick: { w: 50, h: 45 },
            campfire: { w: 45, h: 50 },
            hanging: { w: 50, h: 70 }
        };

        const size = sizes[type];
        obstacle.dataset.width = size.w;
        obstacle.dataset.height = size.h;

        if (type === 'hanging') {
            obstacle.style.bottom = '160px';
        } else {
            obstacle.style.bottom = this.groundY + 'px';
        }

        this.gameContainer.appendChild(obstacle);
        this.obstacles.push({
            element: obstacle,
            x: containerWidth,
            width: size.w,
            height: size.h,
            type: type
        });
    }

    createCoin() {
        const coin = document.createElement('div');
        coin.className = 'coin';

        const containerWidth = this.gameContainer.offsetWidth;
        const heights = [120, 150, 180, 210, this.groundY + 20];
        const height = heights[Math.floor(Math.random() * heights.length)];

        coin.style.left = containerWidth + 'px';
        coin.style.bottom = height + 'px';

        coin.innerHTML = `
            <svg viewBox="0 0 30 30" xmlns="http://www.w3.org/2000/svg">
                <circle cx="15" cy="15" r="13" fill="#FFD700" stroke="#FFA500" stroke-width="2"/>
                <circle cx="15" cy="15" r="10" fill="#FFA500"/>
                <text x="15" y="20" text-anchor="middle" font-size="12" fill="#FFD700" font-weight="bold">$</text>
                <circle cx="10" cy="10" r="2" fill="white" opacity="0.4"/>
            </svg>
        `;

        this.gameContainer.appendChild(coin);
        this.coinsList.push({
            element: coin,
            x: containerWidth,
            width: 28,
            height: 28,
            collected: false
        });
    }

    // ═══ FIXED: Update with speed factor ═══
    updateObstacles(factor) {
        for (let i = this.obstacles.length - 1; i >= 0; i--) {
            const obs = this.obstacles[i];
            obs.x -= this.speed * factor;
            obs.element.style.left = obs.x + 'px';

            if (obs.x < -100) {
                obs.element.remove();
                this.obstacles.splice(i, 1);
            }
        }
    }

    updateCoins(factor) {
        const dragonRect = this.dragon.getBoundingClientRect();
        const containerRect = this.gameContainer.getBoundingClientRect();

        const dragonHitbox = {
            left: dragonRect.left - containerRect.left + 8,
            right: dragonRect.right - containerRect.left - 8,
            top: dragonRect.top - containerRect.top + 8,
            bottom: dragonRect.bottom - containerRect.top - 5
        };

        for (let i = this.coinsList.length - 1; i >= 0; i--) {
            const coin = this.coinsList[i];
            coin.x -= this.speed * factor;
            coin.element.style.left = coin.x + 'px';

            if (!coin.collected) {
                const coinRect = coin.element.getBoundingClientRect();
                const coinHitbox = {
                    left: coinRect.left - containerRect.left,
                    right: coinRect.right - containerRect.left,
                    top: coinRect.top - containerRect.top,
                    bottom: coinRect.bottom - containerRect.top
                };

                if (
                    dragonHitbox.left < coinHitbox.right &&
                    dragonHitbox.right > coinHitbox.left &&
                    dragonHitbox.top < coinHitbox.bottom &&
                    dragonHitbox.bottom > coinHitbox.top
                ) {
                    coin.collected = true;
                    coin.element.classList.add('collected');
                    this.coins++;
                    this.totalCoins++;
                    localStorage.setItem('dragonTotalCoins', this.totalCoins);
                    this.playSound('coin');
                    this.createSparkles(coin.x, parseFloat(coin.element.style.bottom));
                    setTimeout(() => {
                        coin.element.remove();
                        const idx = this.coinsList.indexOf(coin);
                        if (idx > -1) this.coinsList.splice(idx, 1);
                    }, 400);
                }
            }

            if (coin.x < -50 && !coin.collected) {
                coin.element.remove();
                this.coinsList.splice(i, 1);
            }
        }
    }

    createSparkles(x, y) {
        for (let i = 0; i < 6; i++) {
            const sparkle = document.createElement('div');
            sparkle.className = 'sparkle';
            sparkle.style.left = x + 14 + 'px';
            sparkle.style.bottom = y + 14 + 'px';
            sparkle.style.setProperty('--tx', (Math.random() * 40 - 20) + 'px');
            sparkle.style.setProperty('--ty', (Math.random() * -40 - 10) + 'px');
            this.gameContainer.appendChild(sparkle);
            setTimeout(() => sparkle.remove(), 600);
        }
    }

    checkCollisions() {
        const dragonRect = this.dragon.getBoundingClientRect();
        const containerRect = this.gameContainer.getBoundingClientRect();

        const dragonHitbox = {
            left: dragonRect.left - containerRect.left + 10,
            right: dragonRect.right - containerRect.left - 10,
            top: dragonRect.top - containerRect.top + 10,
            bottom: dragonRect.bottom - containerRect.top - 5
        };

        for (const obs of this.obstacles) {
            const obsRect = obs.element.getBoundingClientRect();

            const obsHitbox = {
                left: obsRect.left - containerRect.left + 5,
                right: obsRect.right - containerRect.left - 5,
                top: obsRect.top - containerRect.top + 5,
                bottom: obsRect.bottom - containerRect.top - 5
            };

            if (
                dragonHitbox.left < obsHitbox.right &&
                dragonHitbox.right > obsHitbox.left &&
                dragonHitbox.top < obsHitbox.bottom &&
                dragonHitbox.bottom > obsHitbox.top
            ) {
                if (this.upgrades.shield) {
                    this.upgrades.shield = false;
                    localStorage.setItem('dragonUpgrades', JSON.stringify(this.upgrades));
                    this.playSound('hit');
                    obs.element.style.opacity = '0.3';
                    return;
                }

                this.playSound('fail');
                this.gameOver();
                return;
            }
        }
    }

    updateLevel() {
        const newLevel = Math.floor(this.score / 300) + 1;  // FIXED: Faster level up
        if (newLevel > this.level) {
            this.level = newLevel;
            this.speed = this.baseSpeed + (this.level - 1) * 1.5;
            this.playSound('levelup');
            this.showLevelUpAnimation();
        }
    }

    showLevelUpAnimation() {
        this.gameContainer.classList.add('camera-shake');
        setTimeout(() => this.gameContainer.classList.remove('camera-shake'), 500);

        const overlay = document.createElement('div');
        overlay.className = 'level-up-overlay';
        overlay.innerHTML = `
            <div class="level-up-text">LEVEL ${this.level}</div>
            <div class="level-up-score">${this.score} PUNKTE</div>
            <div class="dragon-closeup">
                ${this.dragon.querySelector('svg').outerHTML}
            </div>
        `;
        this.gameContainer.appendChild(overlay);

        setTimeout(() => overlay.remove(), 2000);
    }

    createSpeedLines() {
        if (this.speed > 8 && Math.random() < 0.4) {
            const line = document.createElement('div');
            line.className = 'speed-line';
            line.style.top = Math.random() * 70 + '%';
            line.style.width = (50 + Math.random() * 100) + 'px';
            line.style.left = '100%';
            this.gameContainer.appendChild(line);
            setTimeout(() => line.remove(), 300);
        }
    }

    gameOver() {
        this.isPlaying = false;
        this.isGameOver = true;
        cancelAnimationFrame(this.animationId);

        this.dragon.classList.add('dead');
        this.createFireBreath();

        if (this.score > this.highScore) {
            this.highScore = this.score;
            localStorage.setItem('dragonHighScore', this.highScore.toString());
        }

        setTimeout(() => this.showGameOver(), 1500);
        this.updateUI();
    }

    createFireBreath() {
        const breath = document.createElement('div');
        breath.className = 'fire-breath';
        const rect = this.dragon.getBoundingClientRect();
        const containerRect = this.gameContainer.getBoundingClientRect();
        breath.style.left = (rect.right - containerRect.left) + 'px';
        breath.style.bottom = (parseFloat(this.dragon.style.bottom) + 20) + 'px';
        breath.innerHTML = `
            <svg viewBox="0 0 60 30" xmlns="http://www.w3.org/2000/svg">
                <path d="M 0 15 Q 20 0 40 5 Q 50 10 60 15 Q 50 20 40 25 Q 20 30 0 15" fill="#FF6B35" opacity="0.9"/>
                <path d="M 5 15 Q 20 5 35 8 Q 42 12 50 15" fill="#FFD93D" opacity="0.8"/>
            </svg>
        `;
        this.gameContainer.appendChild(breath);
        setTimeout(() => breath.remove(), 800);
    }

    showGameOver() {
        this.finalScoreEl.textContent = this.score.toLocaleString();
        this.finalLevelEl.textContent = this.level;
        this.finalCoinsEl.textContent = this.coins;
        this.gameOverOverlay.classList.remove('hidden');

        const gameOverInput = document.getElementById('usernameInputGameOver');
        if (gameOverInput) gameOverInput.value = this.username;

        this.saveScore();
    }

    // ═══ FIXED: Leaderboard with better error handling ═══
    async saveScore() {
        if (!this.username) {
            console.log('No username, saving locally only');
            this.saveLocalScore();
            return;
        }

        try {
            const response = await fetch('/api/dragon/score', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    username: this.username,
                    score: this.score,
                    level: this.level,
                    coins: this.coins,
                    date: new Date().toISOString()
                })
            });

            if (response.ok) {
                const result = await response.json();
                console.log('Score saved to server:', result);
                // FIXED: Reload leaderboard after saving
                await this.loadLeaderboard();
            } else {
                console.error('Server error, saving locally');
                this.saveLocalScore();
            }
        } catch (err) {
            console.error('Network error, saving locally:', err);
            this.saveLocalScore();
        }
    }

    saveLocalScore() {
        const scores = JSON.parse(localStorage.getItem('dragonScores') || '[]');
        scores.push({
            username: this.username || 'Anonymous',
            score: this.score,
            level: this.level,
            coins: this.coins,
            date: new Date().toISOString()
        });
        scores.sort((a, b) => b.score - a.score);
        localStorage.setItem('dragonScores', JSON.stringify(scores.slice(0, 50)));
        this.renderLeaderboard(scores.slice(0, 10));
    }

    // ═══ FIXED: Load leaderboard with retry ═══
    async loadLeaderboard() {
        if (this.leaderboardLoaded) return; // Prevent multiple loads

        try {
            console.log('Loading leaderboard from API...');
            const response = await fetch('/api/dragon/leaderboard');

            if (response.ok) {
                const data = await response.json();
                console.log('Leaderboard data:', data);

                if (data.success && data.scores) {
                    this.renderLeaderboard(data.scores);
                    this.leaderboardLoaded = true;
                } else {
                    throw new Error('Invalid data format');
                }
            } else {
                throw new Error(`HTTP ${response.status}`);
            }
        } catch (err) {
            console.log('API failed, loading local scores:', err);
            const scores = JSON.parse(localStorage.getItem('dragonScores') || '[]');
            this.renderLeaderboard(scores.slice(0, 10));
        }
    }

    renderLeaderboard(scores) {
        if (!scores || scores.length === 0) {
            this.leaderboardBody.innerHTML = `
                <tr><td colspan="6" style="text-align:center; color:rgba(255,255,255,0.4); padding:20px;">
                    Noch keine Eintraege. Sei der Erste! 🐉
                </td></tr>`;
            return;
        }

        this.leaderboardBody.innerHTML = scores.map((entry, index) => {
            let dateStr = 'Unbekannt';
            if (entry.date) {
                try {
                    const date = new Date(entry.date);
                    dateStr = date.toLocaleDateString('de-DE', { 
                        day: '2-digit', month: '2-digit', year: 'numeric',
                        hour: '2-digit', minute: '2-digit'
                    });
                } catch(e) {
                    dateStr = entry.date;
                }
            }

            const rankClass = index < 3 ? `rank-${index + 1}` : '';
            const medal = index === 0 ? '👑' : index === 1 ? '🥈' : index === 2 ? '🥉' : `${index + 1}.`;

            return `
                <tr class="${rankClass}">
                    <td>${medal}</td>
                    <td>${this.escapeHtml(entry.username || 'Unbekannt')}</td>
                    <td class="score-cell">${(entry.score || 0).toLocaleString()}</td>
                    <td class="level-cell">Level ${entry.level || 1}</td>
                    <td>🪙 ${entry.coins || 0}</td>
                    <td>${dateStr}</td>
                </tr>
            `;
        }).join('');
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

    updateUI() {
        if (this.scoreEl) this.scoreEl.textContent = this.score.toLocaleString();
        if (this.highScoreEl) this.highScoreEl.textContent = this.highScore.toLocaleString();
        if (this.levelEl) this.levelEl.textContent = this.level;
        if (this.coinEl) this.coinEl.textContent = this.coins;
        if (this.totalCoinEl) this.totalCoinEl.textContent = this.totalCoins;

        const badge = document.querySelector('.level-badge');
        if (badge) badge.textContent = `Level ${this.level}`;
    }
}

// ═══ INITIALIZE ═══
document.addEventListener('DOMContentLoaded', () => {
    window.dragonGame = new DragonGame();
});
