# voice_mini_app.py – Live Voice Chat mit Parallel Text-Streaming + Voice
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
import asyncio
import json
import logging

from bot_ai import generate_response_stream, generate_voice, strip_voice_tags
from bot_state import GROQ_API_KEY
from groq import AsyncGroq

logger = logging.getLogger(__name__)
app = FastAPI(title="Queen Live Voice Chat")

_groq_client = None

def get_groq_client():
    global _groq_client
    if _groq_client is None:
        if not GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY fehlt!")
        _groq_client = AsyncGroq(api_key=GROQ_API_KEY)
    return _groq_client


HTML_CONTENT = """<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Queen Live Voice</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
    body { margin:0; background:#2a0044; color:#ffccff; font-family:system-ui, -apple-system, sans-serif; text-align:center; padding-top:20px; touch-action: manipulation; }
    h1 { font-size:1.8rem; margin-bottom:10px; }
    #status { font-size:1.1rem; margin:15px; min-height:50px; padding:0 10px; }
    #chat { margin:10px 15px; padding:12px; background:rgba(255,255,255,0.08); border-radius:15px; height:300px; overflow-y:auto; text-align:left; font-size:1rem; }
    .msg { margin:6px 0; padding:10px; border-radius:10px; word-break:break-word; line-height:1.4; }
    .user { background:#ffffff22; }
    .bot { background:#ff66cc22; }
    .bot-typing { opacity:0.7; }
    .speaking { animation: pulse 1s infinite; }
    @keyframes pulse { 0% { opacity: 0.7; } 50% { opacity: 1; } 100% { opacity: 0.7; } }
    #startBtn {
      display:inline-block; margin:20px auto; padding:18px 40px;
      font-size:1.3rem; font-weight:bold; color:#2a0044; background:#ff66cc;
      border:none; border-radius:50px; cursor:pointer; box-shadow:0 4px 15px rgba(255,102,204,0.4);
      transition: transform 0.1s, opacity 0.2s;
    }
    #startBtn:active { transform: scale(0.96); }
    #startBtn:disabled { opacity: 0.5; cursor: not-allowed; }
    .hidden { display: none !important; }
  </style>
</head>
<body>
  <h1>Queen Live Voice 💖</h1>
  <button id="startBtn">🎙️ Chat starten</button>
  <div id="status">Tippe auf den Button, um den Voice-Chat zu starten.</div>
  <div id="chat"></div>

  <script>
    const tg = window.Telegram.WebApp;
    tg.expand();
    tg.ready();

    let ws, mediaRecorder, audioContext, analyser, source, dataArray;
    let audioChunks = [];
    let silenceTimeout = null;
    let isSpeaking = false;
    let isRunning = false;
    let recorderMimeType = '';

    const statusEl = document.getElementById('status');
    const chatEl = document.getElementById('chat');
    const startBtn = document.getElementById('startBtn');

    let audioQueue = [];
    let isPlayingAudio = false;
    let currentAudio = null;
    let activeBotBubble = null;
    let botIsResponding = false;

    function addToChat(text, isBot = false, append = false) {
      if (append && isBot && activeBotBubble) {
        activeBotBubble.textContent += text;
        chatEl.scrollTop = chatEl.scrollHeight;
        return;
      }
      const div = document.createElement('div');
      div.className = 'msg ' + (isBot ? 'bot' : 'user') + (isBot ? ' bot-typing' : '');
      div.textContent = text;
      chatEl.appendChild(div);
      chatEl.scrollTop = chatEl.scrollHeight;
      if (isBot) activeBotBubble = div;
      return div;
    }

    function finalizeBotBubble() {
      if (activeBotBubble) {
        activeBotBubble.classList.remove('bot-typing');
        activeBotBubble = null;
      }
      botIsResponding = false;
      statusEl.textContent = "🟢 Dauerhaft aktiv – ich höre zu...";
    }

    function getSupportedMimeType() {
      const types = [
        'audio/webm;codecs=opus',
        'audio/webm',
        'audio/mp4',
        'audio/ogg;codecs=opus',
        'audio/ogg'
      ];
      for (const t of types) {
        if (MediaRecorder.isTypeSupported(t)) {
          console.log('✅ MediaRecorder supported:', t);
          return t;
        }
      }
      console.warn('⚠️ Kein spezifischer MIME-Type supported, nehme Standard');
      return '';
    }

    async function ensureAudioContext() {
      if (!audioContext) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
      }
      if (audioContext.state === 'suspended') {
        try {
          await audioContext.resume();
          console.log('🔓 AudioContext resumed');
        } catch (e) {
          console.error('AudioContext resume failed:', e);
        }
      }
    }

    async function playNextAudio() {
      if (isPlayingAudio || audioQueue.length === 0) return;
      isPlayingAudio = true;
      await ensureAudioContext();

      const blob = audioQueue.shift();
      const url = URL.createObjectURL(blob);
      currentAudio = new Audio(url);

      currentAudio.onended = () => {
        URL.revokeObjectURL(url);
        isPlayingAudio = false;
        currentAudio = null;
        playNextAudio();
      };
      currentAudio.onerror = (err) => {
        console.error("Audio Error:", err);
        URL.revokeObjectURL(url);
        isPlayingAudio = false;
        currentAudio = null;
        playNextAudio();
      };

      try {
        currentAudio.volume = 1.0;
        await currentAudio.play();
        console.log("▶️ Audio spielt");
      } catch (e) {
        console.error("Audio Play Error:", e);
        URL.revokeObjectURL(url);
        isPlayingAudio = false;
        currentAudio = null;
        playNextAudio();
      }
    }

    function stopAudio() {
      audioQueue = [];
      if (currentAudio) {
        currentAudio.pause();
        currentAudio.currentTime = 0;
        currentAudio = null;
      }
      isPlayingAudio = false;
    }

    async function startVoiceChat() {
      try {
        recorderMimeType = getSupportedMimeType();
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
        });

        const options = recorderMimeType ? { mimeType: recorderMimeType } : {};
        mediaRecorder = new MediaRecorder(stream, options);
        audioChunks = [];

        mediaRecorder.ondataavailable = e => {
          if (e.data.size > 0) audioChunks.push(e.data);
        };

        mediaRecorder.onstop = () => {
          const blobType = recorderMimeType || 'audio/webm';
          const blob = new Blob(audioChunks, { type: blobType });
          if (ws && ws.readyState === WebSocket.OPEN && blob.size > 0) {
            ws.send(blob);
          }
          audioChunks = [];
          // Sauberes Neustarten nach kurzem Delay (vermeidet Race-Condition auf Android)
          if (mediaRecorder && mediaRecorder.state !== 'recording' && isRunning) {
            setTimeout(() => {
              try { mediaRecorder.start(700); } catch(e) { console.error('Restart failed', e); }
            }, 150);
          }
        };

        mediaRecorder.start(700);
        statusEl.textContent = "🟢 Dauerhaft aktiv – ich höre zu...";

        await ensureAudioContext();
        source = audioContext.createMediaStreamSource(stream);
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 512;
        source.connect(analyser);
        dataArray = new Uint8Array(analyser.fftSize);

        function checkSilence() {
          if (!isRunning || !analyser) return;
          analyser.getByteTimeDomainData(dataArray);
          let sum = 0;
          for (let i = 0; i < dataArray.length; i++) {
            sum += Math.abs(dataArray[i] - 128);
          }
          const volume = sum / dataArray.length;

          if (volume > 12) {
            if (!isSpeaking) {
              stopAudio();
              finalizeBotBubble();
              if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({type: "interrupt"}));
              }
            }
            isSpeaking = true;
            clearTimeout(silenceTimeout);
          } else if (isSpeaking) {
            isSpeaking = false;
            silenceTimeout = setTimeout(() => {
              if (mediaRecorder && mediaRecorder.state === "recording") {
                mediaRecorder.stop();
              }
            }, 1400);
          }
          requestAnimationFrame(checkSilence);
        }
        checkSilence();

      } catch (err) {
        console.error(err);
        let msg = "❌ Mikrofon-Zugriff verweigert";
        if (err.name === 'NotAllowedError') msg = "❌ Mikrofon-Berechtigung verweigert. Bitte in den Einstellungen erlauben.";
        if (err.name === 'NotFoundError') msg = "❌ Kein Mikrofon gefunden.";
        statusEl.textContent = msg;
        isRunning = false;
        startBtn.disabled = false;
        startBtn.textContent = "🎙️ Erneut versuchen";
      }
    }

    async function connectWebSocket() {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = window.location.host;
      ws = new WebSocket(`${protocol}//${host}/livevoice/ws/voice`);
      ws.binaryType = 'blob';

      ws.onopen = () => {
        console.log('🔌 WebSocket verbunden');
        statusEl.textContent = "🟢 Verbindung hergestellt – ich höre zu...";
      };

      ws.onmessage = (event) => {
        // 🔊 Audio-Daten empfangen (Blob oder ArrayBuffer)
        if (event.data instanceof Blob) {
          console.log("🎵 Audio Blob empfangen:", event.data.size, "bytes, type:", event.data.type);
          const typedBlob = event.data.type ? event.data : new Blob([event.data], { type: 'audio/mpeg' });
          audioQueue.push(typedBlob);
          playNextAudio();
          return;
        }
        if (event.data instanceof ArrayBuffer) {
          console.log("🎵 Audio ArrayBuffer empfangen:", event.data.byteLength, "bytes");
          audioQueue.push(new Blob([event.data], { type: 'audio/mpeg' }));
          playNextAudio();
          return;
        }

        try {
          const data = JSON.parse(event.data);

          if (data.type === "user_text") {
            addToChat("Du: " + data.text, false);
          }

          if (data.type === "status") {
            statusEl.textContent = data.text;
          }

          if (data.type === "text_chunk") {
            botIsResponding = true;
            if (!activeBotBubble) {
              addToChat("Bot: " + data.text, true);
            } else {
              addToChat(data.text, true, true);
            }
          }

          if (data.type === "text_done") {
            finalizeBotBubble();
          }

          if (data.type === "error") {
            addToChat("❌ " + data.text, true);
            finalizeBotBubble();
          }
        } catch (e) {
          console.log("Unbekannte Nachricht:", event.data);
        }
      };

      ws.onclose = () => {
        statusEl.textContent = "🔴 Verbindung getrennt – lade neu...";
        setTimeout(() => location.reload(), 3000);
      };

      ws.onerror = (err) => {
        console.error("WS Error", err);
        statusEl.textContent = "❌ Verbindungsfehler";
      };
    }

    startBtn.addEventListener('click', async () => {
      if (isRunning) return;
      isRunning = true;
      startBtn.disabled = true;
      startBtn.classList.add('hidden');
      statusEl.textContent = "Starte Voice-Chat...";
      
      await ensureAudioContext();
      connectWebSocket();
      startVoiceChat();
    });
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def voice_chat_page(request: Request):
    return HTMLResponse(HTML_CONTENT)


@app.websocket("/ws/voice")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("✅ Live Voice Chat Verbindung hergestellt")

    try:
        while True:
            raw = await websocket.receive()
            audio_data = None

            if "text" in raw:
                try:
                    cmd = json.loads(raw["text"])
                    if cmd.get("type") == "interrupt":
                        logger.info("🛑 Interrupt empfangen")
                        continue
                except Exception:
                    pass
                continue

            elif "bytes" in raw:
                audio_data = raw["bytes"]
            else:
                continue

            try:
                client = get_groq_client()
                transcription = await client.audio.transcriptions.create(
                    file=("audio.webm", audio_data, "audio/webm"),
                    model="whisper-large-v3-turbo",
                    language="de",
                    response_format="text"
                )
                user_text = transcription.strip()
            except Exception as e:
                logger.error(f"Whisper Fehler: {e}")
                await websocket.send_json({"type": "error", "text": "Konnte dich nicht verstehen."})
                continue

            if not user_text or len(user_text) < 3:
                continue

            logger.info(f"User sagte: {user_text}")
            await websocket.send_json({"type": "user_text", "text": user_text})
            await websocket.send_json({"type": "status", "text": "🗣️ Bot antwortet..."})

            full_reply = ""
            text_done_sent = False

            try:
                async for tag, content in generate_response_stream(chat_id="miniapp", message=user_text):
                    if tag == "text":
                        full_reply += content
                        await websocket.send_json({"type": "text_chunk", "text": content})

                    elif tag == "done":
                        full_reply = content
                        await websocket.send_json({"type": "text_done"})
                        text_done_sent = True

                        # TTS erst nach vollständiger Antwort
                        tts_task = asyncio.create_task(_tts_and_send(websocket, full_reply.strip()))

            except Exception as e:
                logger.error(f"Stream Fehler: {e}")
                if not text_done_sent:
                    await websocket.send_json({"type": "error", "text": "Antwort wurde unterbrochen."})

    except Exception as e:
        logger.info(f"WebSocket Verbindung geschlossen: {e}")


async def _tts_and_send(websocket: WebSocket, text: str):
    """Generiert Voice für den kompletten Text und sendet ihn als Blob."""
    clean_text = strip_voice_tags(text)
    if not clean_text:
        return
    try:
        logger.info(f"🔊 TTS startet für: {clean_text[:50]}...")
        audio_bytes = await generate_voice(clean_text, voice="hannah")
        if audio_bytes:
            logger.info(f"✅ TTS fertig ({len(audio_bytes.getvalue())} bytes)")
            try:
                await websocket.send_bytes(audio_bytes.getvalue())
            except Exception:
                pass
        else:
            logger.warning("⚠️ TTS lieferte kein Audio")
    except Exception as e:
        logger.warning(f"TTS Fehler: {e}")

