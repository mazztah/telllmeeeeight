/* Space War - Galactic Shooter v2.0 - Android Optimized */
class SpaceWar{
  constructor(){
    this.canvas=document.getElementById('gameCanvas');
    this.ctx=this.canvas.getContext('2d');
    this.resize();
    window.addEventListener('resize',()=>this.resize());

    this.state='menu';
    this.score=0;
    this.coins=0;
    this.totalCoins=parseInt(localStorage.getItem('sw_coins')||'0');
    this.level=1;
    this.lives=3;
    this.maxLives=5;
    this.weapon='single';
    this.weaponTimer=0;
    this.droneCount=0;
    this.fireRing=false;
    this.username=localStorage.getItem('sw_name')||'';
    this.highScore=parseInt(localStorage.getItem('sw_hs')||'0');

    this.ship={x:this.canvas.width/2,y:this.canvas.height/2,vx:0,vy:0,angle:0,speed:5,friction:.92,size:18};
    this.bullets=[];
    this.enemies=[];
    this.particles=[];
    this.coinsList=[];
    this.powerups=[];
    this.boss=null;
    this.stars=[];
    this.keys={};

    // Touch state for Android
    this.touch={
      active:false,
      moveActive:false,
      moveX:0,moveY:0,
      moveStartX:0,moveStartY:0,
      fireActive:false,
      fireTouchId:null,
      moveTouchId:null
    };

    this.enemySpawnTimer=0;
    this.bossSpawned=false;
    this.levelKills=0;
    this.killsNeeded=10;
    this.shake=0;
    this.invulnerable=0;
    this.lastTime=0;
    this.deltaTime=0;
    this.lastShot=0;
    this.audioCtx=null;
    this.soundOn=localStorage.getItem('sw_sound')!=='false';
    this.isMobile=/Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
    this.gameReady=false;

    this.initAudio();
    this.initStars();
    this.setupEvents();

    // Delay game start to ensure DOM ready
    setTimeout(()=>{
      this.gameReady=true;
      document.getElementById('loadingScreen').classList.add('hidden');
      this.loop(0);
    },500);
  }

  resize(){
    const dpr=Math.min(window.devicePixelRatio||1,2);
    const w=window.innerWidth;
    const h=window.innerHeight;
    this.canvas.width=w*dpr;
    this.canvas.height=h*dpr;
    this.canvas.style.width=w+'px';
    this.canvas.style.height=h+'px';
    this.ctx.setTransform(dpr,0,0,dpr,0,0);
    this.ship.x=Math.min(this.ship.x,w);
    this.ship.y=Math.min(this.ship.y,h);
  }

  initAudio(){
    try{
      const AudioContext=window.AudioContext||window.webkitAudioContext;
      if(AudioContext){
        this.audioCtx=new AudioContext();
        // Resume on first interaction (required for mobile)
        const resumeAudio=()=>{
          if(this.audioCtx&&this.audioCtx.state==='suspended'){
            this.audioCtx.resume();
          }
        };
        document.addEventListener('touchstart',resumeAudio,{once:true});
        document.addEventListener('click',resumeAudio,{once:true});
      }
    }catch(e){console.log('Audio init failed',e)}
  }

  play(type){
    if(!this.soundOn||!this.audioCtx)return;
    try{
      const c=this.audioCtx,o=c.createOscillator(),g=c.createGain();
      o.connect(g);g.connect(c.destination);
      const now=c.currentTime;
      switch(type){
        case'shoot':
          o.type='square';
          o.frequency.setValueAtTime(900,now);
          o.frequency.exponentialRampToValueAtTime(300,now+.08);
          g.gain.setValueAtTime(.08,now);
          g.gain.exponentialRampToValueAtTime(.001,now+.08);
          o.start(now);o.stop(now+.08);
          break;
        case'explode':
          o.type='sawtooth';
          o.frequency.setValueAtTime(300,now);
          o.frequency.exponentialRampToValueAtTime(60,now+.25);
          g.gain.setValueAtTime(.15,now);
          g.gain.exponentialRampToValueAtTime(.001,now+.25);
          o.start(now);o.stop(now+.25);
          break;
        case'coin':
          o.type='sine';
          o.frequency.setValueAtTime(1500,now);
          o.frequency.exponentialRampToValueAtTime(2200,now+.08);
          g.gain.setValueAtTime(.08,now);
          g.gain.exponentialRampToValueAtTime(.001,now+.12);
          o.start(now);o.stop(now+.12);
          break;
        case'powerup':
          [523,659,784,1047].forEach((f,i)=>{
            const os=c.createOscillator(),ga=c.createGain();
            os.connect(ga);ga.connect(c.destination);
            os.frequency.value=f;
            ga.gain.setValueAtTime(.1,now+i*.08);
            ga.gain.exponentialRampToValueAtTime(.001,now+i*.08+.15);
            os.start(now+i*.08);os.stop(now+i*.08+.15);
          });
          break;
        case'hit':
          o.type='square';
          o.frequency.setValueAtTime(180,now);
          o.frequency.exponentialRampToValueAtTime(90,now+.15);
          g.gain.setValueAtTime(.15,now);
          g.gain.exponentialRampToValueAtTime(.001,now+.15);
          o.start(now);o.stop(now+.15);
          break;
        case'boss':
          o.type='sawtooth';
          o.frequency.setValueAtTime(120,now);
          o.frequency.linearRampToValueAtTime(350,now+.4);
          g.gain.setValueAtTime(.12,now);
          g.gain.exponentialRampToValueAtTime(.001,now+.4);
          o.start(now);o.stop(now+.4);
          break;
        case'win':
          [784,880,988,1047].forEach((f,i)=>{
            const os=c.createOscillator(),ga=c.createGain();
            os.connect(ga);ga.connect(c.destination);
            os.frequency.value=f;
            ga.gain.setValueAtTime(.1,now+i*.12);
            ga.gain.exponentialRampToValueAtTime(.001,now+i*.12+.25);
            os.start(now+i*.12);os.stop(now+i*.12+.25);
          });
          break;
      }
    }catch(e){}
  }

  initStars(){
    this.stars=[];
    const count=this.isMobile?80:150;
    for(let i=0;i<count;i++){
      this.stars.push({
        x:Math.random()*window.innerWidth,
        y:Math.random()*window.innerHeight,
        size:Math.random()*1.5+.5,
        speed:Math.random()*.4+.15,
        layer:Math.random()>.5?1:2
      });
    }
  }

  setupEvents(){
    // Keyboard
    window.addEventListener('keydown',e=>{
      this.keys[e.code]=true;
      if(e.code==='Space')e.preventDefault();
      if(e.code==='Escape'&&this.state==='playing')this.togglePause();
    });
    window.addEventListener('keyup',e=>this.keys[e.code]=false);

    // Touch - Multi-touch support for Android
    const canvas=this.canvas;

    canvas.addEventListener('touchstart',e=>{
      e.preventDefault();
      for(let i=0;i<e.changedTouches.length;i++){
        const t=e.changedTouches[i];
        const rect=canvas.getBoundingClientRect();
        const tx=t.clientX-rect.left;
        const ty=t.clientY-rect.top;

        // Check if touch is on fire button
        const fireBtn=document.getElementById('fireBtn');
        const fireRect=fireBtn.getBoundingClientRect();
        if(t.clientX>=fireRect.left&&t.clientX<=fireRect.right&&
           t.clientY>=fireRect.top&&t.clientY<=fireRect.bottom){
          this.touch.fireActive=true;
          this.touch.fireTouchId=t.identifier;
          fireBtn.style.transform='scale(0.9)';
          continue;
        }

        // Check if touch is on move zone
        const moveZone=document.getElementById('moveZone');
        const moveRect=moveZone.getBoundingClientRect();
        if(t.clientX>=moveRect.left-30&&t.clientX<=moveRect.right+30&&
           t.clientY>=moveRect.top-30&&t.clientY<=moveRect.bottom+30){
          this.touch.moveActive=true;
          this.touch.moveTouchId=t.identifier;
          this.touch.moveStartX=moveRect.left+moveRect.width/2;
          this.touch.moveStartY=moveRect.top+moveRect.height/2;
          this.touch.moveX=t.clientX;
          this.touch.moveY=t.clientY;
          this.updateJoystick();
        }
      }
    },{passive:false});

    canvas.addEventListener('touchmove',e=>{
      e.preventDefault();
      for(let i=0;i<e.changedTouches.length;i++){
        const t=e.changedTouches[i];
        if(t.identifier===this.touch.moveTouchId){
          this.touch.moveX=t.clientX;
          this.touch.moveY=t.clientY;
          this.updateJoystick();
        }
      }
    },{passive:false});

    canvas.addEventListener('touchend',e=>{
      e.preventDefault();
      for(let i=0;i<e.changedTouches.length;i++){
        const t=e.changedTouches[i];
        if(t.identifier===this.touch.fireTouchId){
          this.touch.fireActive=false;
          this.touch.fireTouchId=null;
          document.getElementById('fireBtn').style.transform='';
        }
        if(t.identifier===this.touch.moveTouchId){
          this.touch.moveActive=false;
          this.touch.moveTouchId=null;
          this.resetJoystick();
        }
      }
    },{passive:false});

    canvas.addEventListener('touchcancel',e=>{
      e.preventDefault();
      this.touch.fireActive=false;
      this.touch.moveActive=false;
      this.touch.fireTouchId=null;
      this.touch.moveTouchId=null;
      document.getElementById('fireBtn').style.transform='';
      this.resetJoystick();
    },{passive:false});

    // UI Buttons
    document.getElementById('startBtn').addEventListener('click',()=>this.startGame());
    document.getElementById('restartBtn').addEventListener('click',()=>this.startGame());
    document.getElementById('shopBtn').addEventListener('click',()=>this.openShop());
    document.getElementById('shopBtn2').addEventListener('click',()=>this.openShop());
    document.getElementById('shopBtn3').addEventListener('click',()=>this.openShop());
    document.getElementById('closeShop').addEventListener('click',()=>this.closeShop());
    document.getElementById('resumeBtn').addEventListener('click',()=>this.togglePause());

    const soundBtn=document.getElementById('soundToggle');
    soundBtn.addEventListener('click',()=>{
      this.soundOn=!this.soundOn;
      localStorage.setItem('sw_sound',this.soundOn);
      soundBtn.textContent=this.soundOn?'🔊':'🔇';
    });
    soundBtn.textContent=this.soundOn?'🔊':'🔇';

    const nameInput=document.getElementById('nameInput');
    if(nameInput){
      nameInput.value=this.username;
      nameInput.addEventListener('input',e=>{
        this.username=e.target.value.trim().substring(0,20);
        localStorage.setItem('sw_name',this.username);
      });
    }

    // Visibility change - pause when app backgrounded
    document.addEventListener('visibilitychange',()=>{
      if(document.hidden&&this.state==='playing'){
        this.state='paused';
        document.getElementById('pauseOverlay').classList.remove('hidden');
      }
    });
  }

  updateJoystick(){
    const knob=document.getElementById('moveKnob');
    const zone=document.getElementById('moveZone');
    const rect=zone.getBoundingClientRect();
    const cx=rect.left+rect.width/2;
    const cy=rect.top+rect.height/2;
    const dx=this.touch.moveX-cx;
    const dy=this.touch.moveY-cy;
    const dist=Math.sqrt(dx*dx+dy*dy);
    const maxDist=35;
    const scale=dist>maxDist?maxDist/dist:1;
    knob.style.transform=`translate(calc(-50% + ${dx*scale}px), calc(-50% + ${dy*scale}px))`;
  }

  resetJoystick(){
    const knob=document.getElementById('moveKnob');
    knob.style.transform='translate(-50%,-50%)';
  }

  startGame(){
    this.state='playing';
    this.score=0;
    this.coins=0;
    this.level=1;
    this.lives=3;
    this.weapon='single';
    this.weaponTimer=0;
    this.droneCount=0;
    this.fireRing=false;
    this.bullets=[];
    this.enemies=[];
    this.particles=[];
    this.coinsList=[];
    this.powerups=[];
    this.boss=null;
    this.bossSpawned=false;
    this.levelKills=0;
    this.killsNeeded=10;
    this.shake=0;
    this.invulnerable=0;
    this.ship.x=window.innerWidth/2;
    this.ship.y=window.innerHeight/2;
    this.ship.vx=0;
    this.ship.vy=0;
    this.enemySpawnTimer=0;
    this.lastShot=0;

    this.hideOverlay('menuOverlay');
    this.hideOverlay('gameOverOverlay');
    this.hideOverlay('pauseOverlay');
    this.hideOverlay('shopPanel');
    document.getElementById('bossBar').style.display='none';
    document.getElementById('bossName').style.display='none';
    this.updateUI();
    this.updateWeaponUI();

    // Haptic feedback
    if(window.Telegram&&Telegram.WebApp&&Telegram.WebApp.HapticFeedback){
      Telegram.WebApp.HapticFeedback.impactOccurred('light');
    }
  }

  togglePause(){
    if(this.state==='playing'){
      this.state='paused';
      document.getElementById('pauseOverlay').classList.remove('hidden');
    }else if(this.state==='paused'){
      this.state='playing';
      document.getElementById('pauseOverlay').classList.add('hidden');
      this.lastTime=performance.now();
    }
  }

  hideOverlay(id){
    const el=document.getElementById(id);
    if(el)el.classList.add('hidden');
  }
  showOverlay(id){
    const el=document.getElementById(id);
    if(el)el.classList.remove('hidden');
  }

  updateShip(dt){
    const accel=7*dt;
    const maxSpeed=this.isMobile?5:6;

    if(this.touch.moveActive){
      const zone=document.getElementById('moveZone');
      const rect=zone.getBoundingClientRect();
      const cx=rect.left+rect.width/2;
      const cy=rect.top+rect.height/2;
      const dx=this.touch.moveX-cx;
      const dy=this.touch.moveY-cy;
      const dist=Math.sqrt(dx*dx+dy*dy);
      if(dist>10){
        const nx=dx/dist,ny=dy/dist;
        this.ship.vx+=nx*accel*1.5;
        this.ship.vy+=ny*accel*1.5;
      }
    }else{
      if(this.keys['ArrowLeft']||this.keys['KeyA'])this.ship.vx-=accel;
      if(this.keys['ArrowRight']||this.keys['KeyD'])this.ship.vx+=accel;
      if(this.keys['ArrowUp']||this.keys['KeyW'])this.ship.vy-=accel;
      if(this.keys['ArrowDown']||this.keys['KeyS'])this.ship.vy+=accel;
    }

    this.ship.vx*=this.ship.friction;
    this.ship.vy*=this.ship.friction;
    this.ship.x+=this.ship.vx;
    this.ship.y+=this.ship.vy;

    const margin=25;
    this.ship.x=Math.max(margin,Math.min(window.innerWidth-margin,this.ship.x));
    this.ship.y=Math.max(margin,Math.min(window.innerHeight-margin,this.ship.y));

    if(Math.abs(this.ship.vx)>.2||Math.abs(this.ship.vy)>.2){
      this.ship.angle=Math.atan2(this.ship.vy,this.ship.vx);
    }
  }

  shoot(){
    const now=Date.now();
    const fireRate=this.weapon==='rapid'?80:120;
    if(this.lastShot&&now-this.lastShot<fireRate)return;
    this.lastShot=now;
    this.play('shoot');

    const spread=this.weapon==='triple'?3:this.weapon==='penta'?5:1;
    for(let i=0;i<spread;i++){
      const angle=-Math.PI/2+(i-(spread-1)/2)*.25;
      this.bullets.push({
        x:this.ship.x,y:this.ship.y-15,
        vx:Math.cos(angle)*10,vy:Math.sin(angle)*10,
        damage:this.weapon==='heavy'?3:1,
        size:this.weapon==='heavy'?5:3,
        color:this.weapon==='plasma'?'#f0f':'#0ff',
        life:100
      });
    }

    if(this.droneCount>0){
      for(let i=0;i<this.droneCount;i++){
        const angle=(Date.now()/1000+i*Math.PI*2/this.droneCount);
        this.bullets.push({
          x:this.ship.x+Math.cos(angle)*35,
          y:this.ship.y+Math.sin(angle)*35,
          vx:Math.cos(angle)*7,vy:Math.sin(angle)*7,
          damage:1,size:3,color:'#0f0',life:70,drone:true
        });
      }
    }
  }

  spawnEnemy(){
    const types=['basic','fast','tank','zigzag','chaser'];
    const type=types[Math.min(Math.floor(Math.random()*types.length),Math.min(this.level,types.length)-1)];
    const side=Math.floor(Math.random()*4);
    let x,y,vx,vy,hp=1,speed=2,size=14,color='#ff4444';
    const W=window.innerWidth,H=window.innerHeight;
    switch(side){
      case 0:x=Math.random()*W;y=-30;break;
      case 1:x=W+30;y=Math.random()*H;break;
      case 2:x=Math.random()*W;y=H+30;break;
      case 3:x=-30;y=Math.random()*H;break;
    }
    const angle=Math.atan2(this.ship.y-y,this.ship.x-x);
    switch(type){
      case'basic':vx=Math.cos(angle)*speed;vy=Math.sin(angle)*speed;break;
      case'fast':speed=3.5;vx=Math.cos(angle)*speed;vy=Math.sin(angle)*speed;size=11;color='#ff8844';break;
      case'tank':speed=.9;vx=Math.cos(angle)*speed;vy=Math.sin(angle)*speed;size=22;color='#ff0044';hp=3;break;
      case'zigzag':speed=2.2;vx=Math.cos(angle)*speed;vy=Math.sin(angle)*speed;size=13;color='#ff44ff';break;
      case'chaser':speed=1.8;vx=Math.cos(angle)*speed;vy=Math.sin(angle)*speed;size=15;color='#ff0000';hp=2;break;
    }
    this.enemies.push({x,y,vx,vy,hp,maxHp:hp,type,size,color,angle,wobble:Math.random()*Math.PI*2,shootTimer:0});
  }

  spawnBoss(){
    this.bossSpawned=true;
    this.play('boss');
    const bosses=[
      {name:'STAR DESTROYER',hp:40,size:55,color:'#ff00ff',speed:.9},
      {name:'COSMIC TITAN',hp:65,size:70,color:'#ff0088',speed:.7},
      {name:'GALACTUS',hp:100,size:85,color:'#ff0044',speed:.5}
    ];
    const b=bosses[Math.min(Math.floor((this.level-1)/3),bosses.length-1)];
    this.boss={x:window.innerWidth/2,y:-80,vx:0,vy:b.speed,hp:b.hp,maxHp:b.hp,name:b.name,size:b.size,color:b.color,phase:0,shootTimer:0,angle:0};
    document.getElementById('bossBar').style.display='block';
    document.getElementById('bossName').style.display='block';
    document.getElementById('bossName').textContent=b.name;
  }

  spawnCoin(x,y,value){
    this.coinsList.push({x,y,vx:(Math.random()-.5)*2.5,vy:(Math.random()-.5)*2.5,value:value||1,size:10,life:350,magnet:false});
  }

  spawnPowerup(x,y){
    const types=['heart','triple','penta','rapid','heavy','plasma','drone','ring'];
    const type=types[Math.floor(Math.random()*types.length)];
    this.powerups.push({x,y,vx:(Math.random()-.5)*1.5,vy:(Math.random()-.5)*1.5,type,size:18,life:350});
  }

  updateBullets(dt){
    for(let i=this.bullets.length-1;i>=0;i--){
      const b=this.bullets[i];
      b.x+=b.vx;b.y+=b.vy;b.life--;
      if(b.x<-30||b.x>window.innerWidth+30||b.y<-30||b.y>window.innerHeight+30||b.life<=0){
        this.bullets.splice(i,1);continue;
      }
      if(!b.drone){
        for(let j=this.enemies.length-1;j>=0;j--){
          const e=this.enemies[j];
          const dx=b.x-e.x,dy=b.y-e.y,dist=Math.sqrt(dx*dx+dy*dy);
          if(dist<e.size+b.size){
            e.hp-=b.damage;this.createParticles(e.x,e.y,e.color,4);
            this.bullets.splice(i,1);
            if(e.hp<=0){this.destroyEnemy(e,j)}
            break;
          }
        }
        if(this.boss){
          const dx=b.x-this.boss.x,dy=b.y-this.boss.y,dist=Math.sqrt(dx*dx+dy*dy);
          if(dist<this.boss.size+b.size){
            this.boss.hp-=b.damage;
            this.createParticles(this.boss.x,this.boss.y,this.boss.color,6);
            this.bullets.splice(i,1);
            if(this.boss.hp<=0){this.destroyBoss()}
          }
        }
      }
    }
  }

  updateEnemies(dt){
    this.enemySpawnTimer+=dt;
    if(!this.bossSpawned&&this.levelKills>=this.killsNeeded){
      this.spawnBoss();
    }else if(!this.bossSpawned&&this.enemySpawnTimer>Math.max(.6,2.2-this.level*.12)){
      this.enemySpawnTimer=0;this.spawnEnemy();
    }
    for(let i=this.enemies.length-1;i>=0;i--){
      const e=this.enemies[i];
      switch(e.type){
        case'zigzag':
          e.wobble+=dt*4;
          e.vx+=Math.cos(e.wobble)*.08;
          e.vy+=Math.sin(e.wobble)*.08;
          break;
        case'chaser':
          const a=Math.atan2(this.ship.y-e.y,this.ship.x-e.x);
          e.vx+=Math.cos(a)*.04;
          e.vy+=Math.sin(a)*.04;
          const spd=Math.sqrt(e.vx*e.vx+e.vy*e.vy);
          if(spd>2.8){e.vx=(e.vx/spd)*2.8;e.vy=(e.vy/spd)*2.8}
          break;
      }
      e.x+=e.vx;e.y+=e.vy;
      e.shootTimer+=dt;
      if(e.shootTimer>2.5&&e.type==='tank'){
        e.shootTimer=0;
        this.bullets.push({x:e.x,y:e.y,vx:Math.cos(e.angle)*4,vy:Math.sin(e.angle)*4,damage:1,size:3,color:'#ff4444',life:100,enemy:true});
      }
      if(e.x<-60||e.x>window.innerWidth+60||e.y<-60||e.y>window.innerHeight+60){
        this.enemies.splice(i,1);continue;
      }
      const dx=this.ship.x-e.x,dy=this.ship.y-e.y,dist=Math.sqrt(dx*dx+dy*dy);
      if(dist<e.size+this.ship.size&&this.invulnerable<=0){
        this.hit();this.enemies.splice(i,1);
      }
    }
  }

  updateBoss(dt){
    if(!this.boss)return;
    this.boss.y+=this.boss.vy;
    if(this.boss.y>140)this.boss.vy*=-1;
    if(this.boss.y<40)this.boss.vy*=-1;
    this.boss.x+=Math.sin(Date.now()/1000)*1.5;
    this.boss.shootTimer+=dt;
    if(this.boss.shootTimer>1.8){
      this.boss.shootTimer=0;
      const bulletCount=this.isMobile?6:8;
      for(let i=0;i<bulletCount;i++){
        const angle=(Math.PI*2/bulletCount)*i+this.boss.phase;
        this.bullets.push({x:this.boss.x,y:this.boss.y,vx:Math.cos(angle)*3.5,vy:Math.sin(angle)*3.5,damage:1,size:4,color:'#ff00ff',life:140,enemy:true});
      }
      this.boss.phase+=.15;
    }
    document.getElementById('bossFill').style.width=(this.boss.hp/this.boss.maxHp*100)+'%';
  }

  destroyEnemy(e,i){
    this.play('explode');
    this.score+=10*this.level;
    this.levelKills++;
    this.createParticles(e.x,e.y,e.color,12);
    const coinCount=Math.floor(Math.random()*2)+1+Math.floor(this.level/3);
    for(let c=0;c<coinCount;c++)this.spawnCoin(e.x+(Math.random()-.5)*16,e.y+(Math.random()-.5)*16,Math.floor(this.level/2)+1);
    if(Math.random()<.12)this.spawnPowerup(e.x,e.y);
    this.enemies.splice(i,1);
    if(this.levelKills>=this.killsNeeded&&!this.bossSpawned)this.spawnBoss();
  }

  destroyBoss(){
    this.play('win');
    this.score+=400*this.level;
    this.coins+=40*this.level;
    this.totalCoins+=40*this.level;
    localStorage.setItem('sw_coins',this.totalCoins);
    this.createParticles(this.boss.x,this.boss.y,this.boss.color,40);
    for(let c=0;c<15;c++)this.spawnCoin(this.boss.x+(Math.random()-.5)*50,this.boss.y+(Math.random()-.5)*50,4);
    this.boss=null;this.bossSpawned=false;
    this.level++;this.levelKills=0;
    this.killsNeeded=10+this.level*4;
    document.getElementById('bossBar').style.display='none';
    document.getElementById('bossName').style.display='none';
    this.shake=15;
    this.showLevelUp();
  }

  showLevelUp(){
    const div=document.createElement('div');
    div.style.cssText='position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);font-size:clamp(32px,10vw,48px);color:#0ff;text-shadow:0 0 25px #0ff;z-index:500;font-weight:900;pointer-events:none;animation:levelUpAnim 1.8s forwards';
    div.textContent='LEVEL '+this.level;
    document.body.appendChild(div);
    setTimeout(()=>div.remove(),1800);
  }

  updateCoins(dt){
    for(let i=this.coinsList.length-1;i>=0;i--){
      const c=this.coinsList[i];
      const dx=this.ship.x-c.x,dy=this.ship.y-c.y,dist=Math.sqrt(dx*dx+dy*dy);
      if(dist<120){c.x+=(dx/dist)*4;c.y+=(dy/dist)*4}
      c.x+=c.vx;c.y+=c.vy;c.life--;
      if(c.life<=0){this.coinsList.splice(i,1);continue}
      if(dist<this.ship.size+c.size){
        this.play('coin');
        this.coins+=c.value;this.totalCoins+=c.value;
        localStorage.setItem('sw_coins',this.totalCoins);
        this.createParticles(c.x,c.y,'#ffd700',3);
        this.coinsList.splice(i,1);
      }
    }
  }

  updatePowerups(dt){
    for(let i=this.powerups.length-1;i>=0;i--){
      const p=this.powerups[i];
      p.x+=p.vx;p.y+=p.vy;p.life--;
      if(p.life<=0){this.powerups.splice(i,1);continue}
      const dx=this.ship.x-p.x,dy=this.ship.y-p.y,dist=Math.sqrt(dx*dx+dy*dy);
      if(dist<this.ship.size+p.size){
        this.play('powerup');
        this.applyPowerup(p.type);
        this.createParticles(p.x,p.y,'#0ff',8);
        this.powerups.splice(i,1);
      }
    }
  }

  applyPowerup(type){
    this.weaponTimer=500;
    switch(type){
      case'heart':this.lives=Math.min(this.lives+1,this.maxLives);break;
      case'triple':this.weapon='triple';break;
      case'penta':this.weapon='penta';break;
      case'rapid':this.weapon='rapid';break;
      case'heavy':this.weapon='heavy';break;
      case'plasma':this.weapon='plasma';break;
      case'drone':this.droneCount=Math.min(this.droneCount+1,3);break;
      case'ring':this.fireRing=true;setTimeout(()=>this.fireRing=false,5000);break;
    }
    this.updateWeaponUI();
  }

  updateWeaponUI(){
    document.querySelectorAll('.weapon-icon').forEach(el=>{
      el.classList.remove('active');
      if(el.dataset.w===this.weapon)el.classList.add('active');
    });
  }

  hit(){
    if(this.invulnerable>0)return;
    this.play('hit');
    this.lives--;this.shake=8;this.invulnerable=1.8;
    this.createParticles(this.ship.x,this.ship.y,'#0ff',15);
    if(this.lives<=0)this.gameOver();
  }

  gameOver(){
    this.state='gameover';
    if(this.score>this.highScore){
      this.highScore=this.score;
      localStorage.setItem('sw_hs',this.highScore);
    }
    document.getElementById('finalScore').textContent=this.score;
    document.getElementById('finalLevel').textContent=this.level;
    document.getElementById('finalCoins').textContent=this.coins;
    document.getElementById('gameOverOverlay').classList.remove('hidden');
    this.saveScore();

    if(window.Telegram&&Telegram.WebApp&&Telegram.WebApp.HapticFeedback){
      Telegram.WebApp.HapticFeedback.notificationOccurred('error');
    }
  }

  async saveScore(){
    if(!this.username)return;
    try{
      await fetch('/api/spacewar/score',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          username:this.username,
          score:this.score,
          level:this.level,
          coins:this.coins,
          date:new Date().toISOString()
        })
      });
    }catch(e){console.log('Save failed',e)}
  }

  createParticles(x,y,color,count){
    for(let i=0;i<count;i++){
      const angle=Math.random()*Math.PI*2;
      this.particles.push({
        x,y,
        vx:Math.cos(angle)*Math.random()*4,
        vy:Math.sin(angle)*Math.random()*4,
        life:25+Math.random()*15,
        size:Math.random()*3+1,color
      });
    }
  }

  updateParticles(dt){
    for(let i=this.particles.length-1;i>=0;i--){
      const p=this.particles[i];
      p.x+=p.vx;p.y+=p.vy;p.life--;
      if(p.life<=0)this.particles.splice(i,1);
    }
  }

  updateStars(dt){
    for(const s of this.stars){
      s.y+=s.speed*(this.state==='playing'?2.5:1)*dt*s.layer;
      if(s.y>window.innerHeight){s.y=0;s.x=Math.random()*window.innerWidth}
    }
  }

  updateUI(){
    document.getElementById('scoreVal').textContent=this.score;
    document.getElementById('levelVal').textContent=this.level;
    document.getElementById('coinVal').textContent=this.coins;
    document.getElementById('hpFill').style.width=(this.lives/this.maxLives*100)+'%';
  }

  openShop(){
    this.showOverlay('shopPanel');
    document.getElementById('shopCoins').textContent='🪙 '+this.totalCoins;
    const items=[
      {id:'heart',name:'Extra Leben',icon:'❤️',desc:'+1 Leben',price:100},
      {id:'speed',name:'Speed Boost',icon:'🚀',desc:'Schneller',price:150},
      {id:'drone1',name:'Drohne I',icon:'🛸',desc:'1 Drohne',price:200},
      {id:'drone2',name:'Drohne II',icon:'🛸🛸',desc:'2 Drohnen',price:350},
      {id:'drone3',name:'Drohne III',icon:'🛸🛸🛸',desc:'3 Drohnen',price:500},
      {id:'shield',name:'Schild',icon:'🛡️',desc:'5s Unverwundbar',price:250}
    ];
    const container=document.getElementById('shopItems');
    container.innerHTML=items.map(item=>{
      const owned=this.isOwned(item.id);
      return `<div class="shop-item${owned?' owned':''}" data-id="${item.id}"><div class="icon">${item.icon}</div><div class="name">${item.name}</div><div class="desc">${item.desc}</div><div class="price">${owned?'✅':'🪙 '+item.price}</div></div>`;
    }).join('');
    container.querySelectorAll('.shop-item').forEach(el=>{
      el.addEventListener('click',()=>{
        const item=items.find(i=>i.id===el.dataset.id);
        if(item)this.buyItem(el.dataset.id,item.price);
      });
    });
  }

  isOwned(id){
    return localStorage.getItem('sw_owned_'+id)==='true';
  }

  buyItem(id,price){
    if(this.totalCoins<price||this.isOwned(id))return;
    this.totalCoins-=price;
    localStorage.setItem('sw_coins',this.totalCoins);
    localStorage.setItem('sw_owned_'+id,'true');
    this.play('powerup');
    document.getElementById('shopCoins').textContent='🪙 '+this.totalCoins;
    this.openShop();
    switch(id){
      case'heart':this.maxLives++;this.lives++;break;
      case'speed':this.ship.speed+=.8;break;
      case'drone1':this.droneCount=Math.max(this.droneCount,1);break;
      case'drone2':this.droneCount=Math.max(this.droneCount,2);break;
      case'drone3':this.droneCount=3;break;
      case'shield':this.invulnerable=5;break;
    }
  }

  closeShop(){
    this.hideOverlay('shopPanel');
  }

  draw(){
    this.ctx.save();
    if(this.shake>0){
      this.shake--;
      this.ctx.translate((Math.random()-.5)*this.shake,(Math.random()-.5)*this.shake);
    }
    this.ctx.fillStyle='#050510';
    this.ctx.fillRect(0,0,window.innerWidth,window.innerHeight);

    for(const s of this.stars){
      this.ctx.fillStyle=`rgba(255,255,255,${s.size/3})`;
      this.ctx.beginPath();
      this.ctx.arc(s.x,s.y,s.size,0,Math.PI*2);
      this.ctx.fill();
    }

    if(this.state==='playing'||this.state==='paused'){
      this.drawShip();
      for(const b of this.bullets)this.drawBullet(b);
      for(const e of this.enemies)this.drawEnemy(e);
      if(this.boss)this.drawBoss();
      for(const c of this.coinsList)this.drawCoin(c);
      for(const p of this.powerups)this.drawPowerup(p);
      for(const p of this.particles)this.drawParticle(p);

      if(this.fireRing){
        this.ctx.strokeStyle='#ff0';
        this.ctx.lineWidth=3;
        this.ctx.beginPath();
        this.ctx.arc(this.ship.x,this.ship.y,55,0,Math.PI*2);
        this.ctx.stroke();
        for(let i=this.enemies.length-1;i>=0;i--){
          const e=this.enemies[i];
          const dx=e.x-this.ship.x,dy=e.y-this.ship.y,dist=Math.sqrt(dx*dx+dy*dy);
          if(dist<55){
            e.hp-=2;
            this.createParticles(e.x,e.y,'#ff0',3);
            if(e.hp<=0){this.destroyEnemy(e,i);i--}
          }
        }
      }

      if(this.invulnerable>0){
        this.invulnerable-=this.deltaTime;
        this.ctx.globalAlpha=.5+Math.sin(Date.now()/80)*.3;
        this.drawShip();
        this.ctx.globalAlpha=1;
      }
    }
    this.ctx.restore();
  }

  drawShip(){
    this.ctx.save();
    this.ctx.translate(this.ship.x,this.ship.y);
    this.ctx.rotate(this.ship.angle+Math.PI/2);
    this.ctx.shadowBlur=12;
    this.ctx.shadowColor='#0ff';
    this.ctx.fillStyle='#4ecdc4';
    this.ctx.beginPath();
    this.ctx.moveTo(0,-18);
    this.ctx.lineTo(-10,13);
    this.ctx.lineTo(0,9);
    this.ctx.lineTo(10,13);
    this.ctx.closePath();
    this.ctx.fill();
    this.ctx.fillStyle='#7fdbda';
    this.ctx.beginPath();
    this.ctx.moveTo(0,-13);
    this.ctx.lineTo(-5,9);
    this.ctx.lineTo(0,7);
    this.ctx.lineTo(5,9);
    this.ctx.closePath();
    this.ctx.fill();
    this.ctx.fillStyle='#ff6b35';
    const flame=3+Math.random()*4;
    this.ctx.beginPath();
    this.ctx.moveTo(-6,13);
    this.ctx.lineTo(-3,20+flame);
    this.ctx.lineTo(-1,13);
    this.ctx.fill();
    this.ctx.beginPath();
    this.ctx.moveTo(1,13);
    this.ctx.lineTo(3,20+flame);
    this.ctx.lineTo(6,13);
    this.ctx.fill();
    this.ctx.restore();
  }

  drawBullet(b){
    this.ctx.save();
    this.ctx.shadowBlur=8;
    this.ctx.shadowColor=b.color;
    this.ctx.fillStyle=b.color;
    this.ctx.beginPath();
    this.ctx.arc(b.x,b.y,b.size,0,Math.PI*2);
    this.ctx.fill();
    this.ctx.restore();
  }

  drawEnemy(e){
    this.ctx.save();
    this.ctx.translate(e.x,e.y);
    this.ctx.shadowBlur=8;
    this.ctx.shadowColor=e.color;
    this.ctx.fillStyle=e.color;
    this.ctx.beginPath();
    if(e.type==='fast'){
      this.ctx.moveTo(0,-e.size);
      this.ctx.lineTo(-e.size*.6,e.size*.6);
      this.ctx.lineTo(e.size*.6,e.size*.6);
    }else if(e.type==='tank'){
      this.ctx.rect(-e.size*.7,-e.size*.7,e.size*1.4,e.size*1.4);
    }else if(e.type==='zigzag'){
      this.ctx.moveTo(0,-e.size);
      this.ctx.lineTo(-e.size,e.size*.4);
      this.ctx.lineTo(0,0);
      this.ctx.lineTo(e.size,e.size*.4);
    }else{
      this.ctx.moveTo(0,-e.size);
      this.ctx.lineTo(-e.size*.7,e.size*.4);
      this.ctx.lineTo(0,e.size*.2);
      this.ctx.lineTo(e.size*.7,e.size*.4);
    }
    this.ctx.closePath();
    this.ctx.fill();
    if(e.hp<e.maxHp){
      this.ctx.fillStyle='#f00';
      this.ctx.fillRect(-e.size,-e.size-6,e.size*2*(e.hp/e.maxHp),3);
    }
    this.ctx.restore();
  }

  drawBoss(){
    const b=this.boss;
    this.ctx.save();
    this.ctx.translate(b.x,b.y);
    this.ctx.shadowBlur=25;
    this.ctx.shadowColor=b.color;
    this.ctx.fillStyle=b.color;
    this.ctx.beginPath();
    this.ctx.arc(0,0,b.size*.55,0,Math.PI*2);
    this.ctx.fill();
    this.ctx.fillStyle='#fff';
    this.ctx.beginPath();
    this.ctx.arc(-b.size*.18,-b.size*.18,b.size*.12,0,Math.PI*2);
    this.ctx.arc(b.size*.18,-b.size*.18,b.size*.12,0,Math.PI*2);
    this.ctx.fill();
    this.ctx.fillStyle='#f00';
    this.ctx.beginPath();
    this.ctx.arc(0,b.size*.08,b.size*.18,0,Math.PI);
    this.ctx.fill();
    const orbCount=this.isMobile?4:6;
    for(let i=0;i<orbCount;i++){
      const angle=(Date.now()/600)+i*(Math.PI*2/orbCount);
      this.ctx.fillStyle=b.color;
      this.ctx.beginPath();
      this.ctx.arc(Math.cos(angle)*b.size*.7,Math.sin(angle)*b.size*.7,b.size*.12,0,Math.PI*2);
      this.ctx.fill();
    }
    this.ctx.restore();
  }

  drawCoin(c){
    this.ctx.save();
    this.ctx.translate(c.x,c.y);
    this.ctx.shadowBlur=8;
    this.ctx.shadowColor='#ffd700';
    this.ctx.fillStyle='#ffd700';
    this.ctx.beginPath();
    this.ctx.arc(0,0,c.size,0,Math.PI*2);
    this.ctx.fill();
    this.ctx.fillStyle='#ff8c00';
    this.ctx.beginPath();
    this.ctx.arc(0,0,c.size*.6,0,Math.PI*2);
    this.ctx.fill();
    this.ctx.fillStyle='#ffd700';
    this.ctx.font='bold 11px Arial';
    this.ctx.textAlign='center';
    this.ctx.textBaseline='middle';
    this.ctx.fillText('$',0,1);
    this.ctx.restore();
  }

  drawPowerup(p){
    this.ctx.save();
    this.ctx.translate(p.x,p.y);
    this.ctx.shadowBlur=12;
    this.ctx.shadowColor='#0ff';
    const icons={heart:'❤️',triple:'🔫',penta:'🔫🔫',rapid:'⚡',heavy:'💥',plasma:'🔮',drone:'🛸',ring:'⭕'};
    this.ctx.font='18px Arial';
    this.ctx.textAlign='center';
    this.ctx.textBaseline='middle';
    this.ctx.fillText(icons[p.type]||'⭐',0,0);
    this.ctx.restore();
  }

  drawParticle(p){
    this.ctx.globalAlpha=p.life/40;
    this.ctx.fillStyle=p.color;
    this.ctx.beginPath();
    this.ctx.arc(p.x,p.y,p.size*(p.life/40),0,Math.PI*2);
    this.ctx.fill();
    this.ctx.globalAlpha=1;
  }

  loop(timestamp){
    this.deltaTime=(timestamp-this.lastTime)/1000;
    this.lastTime=timestamp;
    if(this.deltaTime>.1)this.deltaTime=.1;

    if(this.state==='playing'){
      this.updateShip(this.deltaTime);
      this.updateBullets(this.deltaTime);
      this.updateEnemies(this.deltaTime);
      if(this.boss)this.updateBoss(this.deltaTime);
      this.updateCoins(this.deltaTime);
      this.updatePowerups(this.deltaTime);
      this.updateParticles(this.deltaTime);
      this.updateStars(this.deltaTime);

      if(this.weaponTimer>0){
        this.weaponTimer-=this.deltaTime*60;
        if(this.weaponTimer<=0){this.weapon='single';this.updateWeaponUI()}
      }

      // Fire from touch button OR space key
      if(this.touch.fireActive||this.keys['Space'])this.shoot();

      this.updateUI();
    }else{
      this.updateStars(this.deltaTime);
    }

    this.draw();
    requestAnimationFrame(t=>this.loop(t));
  }
}

// Initialize when DOM ready
if(document.readyState==='loading'){
  document.addEventListener('DOMContentLoaded',()=>new SpaceWar());
}else{
  new SpaceWar();
}
