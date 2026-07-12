---
title: Telllmeeedrei BOT
emoji: 😈
colorFrom: purple
colorTo: blue
sdk: docker
sdk_version: "3.11"
python_version: "3.11"
app_file: main.py
pinned: false
---

# 🤖 telllmeeedrei – Telegram AI Bot


**Vollständiger modularer Telegram-Bot** mit KI-Chat (Groq LLaMA-4/3.3), Voice-Klonung, Bild-/Video-Generierung, Musik-AI (Lyria/Suno), Brain-Speicher (Supabase), Tool-Agents, E-Mail-Batches und YouTube-Analyse. Optimiert für Railway (Polling Mode uvm).

[![Status](https://img.shields.io/badge/Status-Live-brightgreen)](https://telllmeeedrei-production.up.railway.app) [![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://python.org) [![Groq](https://img.shields.io/badge/Groq-LLM%2FTTS-orange)](https://groq.com) [![Railway](https://img.shields.io/badge/Deploy-Railway-blue)](https://railway.app)

---

## 🎯 Kern-Features (Übersicht)

| Kategorie | Features & Module | Key-Tech |
|-----------|-------------------|-----------|
| **🤖 KI & Agents** | /agent, /superagent, /openclaw, Claude Code (/clcode), Tool-Use-Loop | Groq LLaMA-4, Claude 3.5 |
| **🎤 Voice/TTS** | Whisper-V3 Turbo, Groq Orpheus, Voice-Klonung (/voiceclone), Live-Stream | XTTS-v2, gTTS |
| **🖼️ Media** | FLUX.1 (/imagine), Image-Edit (/edit), Vision-Analyse (/vision) | HuggingFace, DashScope |
| **🎬 Video** | Text-to-Video (/ttv26), Image-to-Video (/textvideo) | Wan2.2, DashScope |
| **🎵 Musik** | Lyria 3 (/musik), Suno v3.5, MusicGen (/freebeat), Humming-Erkennung | Google GenAI, AudD |
| **💾 Brain** | /upload, /brainlist (UI), /semantic (Vektorsuche), Sync-System | Supabase, pgvector |
| **🔄 Converter** | Universal-Konverter (12 Formate), /textconvert | PDF, DOCX, MP3, etc. |
| **📺📧 Extras** | /yt (YouTube-PDF), /mailbatch (Gmail OAuth), /workflow, /social | Gmail API, YT-Transcript |

---

## 📋 Alle Commands (Vollständige Referenz)

### **🤖 KI & Agents**
| Command | Beschreibung | Beispiel |
|---------|--------------|----------|
| `/chat <text>` | Direkt-Chat mit KI (Alias für Textnachricht) | `/chat Wie funktioniert Quantenphysik?` |
| `/agent <task>` | Tool-Agent (Web, Brain, Konvertierung) | `/agent Suche nach X und erstelle PDF` |
| `/superagent <task>` | Master-Agent (12-Schritt-Loop) | `/superagent Analyse von Markttrends` |
| `/openclaw <task>` | Agent mit Preset-Prompts & Buttons | `/openclaw debugge diesen Python Code` |
| `/clcode <prompt>` | Claude 3.5 Code-Agent (Pydantic JSON) | `/clcode erstelle eine FastAPI App` |
| `/code <prompt>` | Code-Generierung via Groq | `/code schreibe ein Bash-Script` |

### **🎤 Voice & Audio**
| Command | Beschreibung | Beispiel |
|---------|--------------|----------|
| `/voicetoggle` | Automatische Sprachantworten an/aus | `/voicetoggle` |
| `/voiceclone <name>` | Stimme klonen (reply Audio) | `/voiceclone Hannah` |
| `/myvoices` | Liste alle geklonten Stimmen | `/myvoices` |
| `/speak <voice> \| <text>` | Text mit geklonter Stimme sprechen | `/speak Hannah Hallo Welt` |
| `/livevoice` | WebSocket Voice-Chat Mini App öffnen | `/livevoice` |
| `/startstream` / `/endstream` | Live-Voice-Stream aktivieren/beenden | `/startstream` |

### **🖼️ Media & Video**
| Command | Beschreibung | Beispiel |
|---------|--------------|----------|
| `/imagine <prompt>` | FLUX.1-schnell Bildgenerierung | `/imagine cyberpunk city, 8k` |
| `/edit <anweisung>` | Bild-Edit-Modus (reply Bild) | `/edit mache den Hintergrund rot` |
| `/vision` / `/analyze` | Bild per KI analysieren (reply Bild) | `/vision Was ist auf diesem Bild?` |
| `/ttv26 <prompt>` | Text-to-Video (Wan2.2) | `/ttv26 Astronaut auf dem Mars` |
| `/textvideo <prompt>` | Image-to-Video (reply Bild) | `/textvideo lass das Bild tanzen` |
| `/stopvideo` / `/cancel` | Laufende Video-Generierung abbrechen | `/stopvideo` |

### **🎵 Musik & Sound**
| Command | Beschreibung | Beispiel |
|---------|--------------|----------|
| `/musik <prompt>` | Kaskade: Lyria $\rightarrow$ Suno $\rightarrow$ MusicGen | `/musik lofi hiphop beat` |
| `/suno <prompt>` | Direkte Suno v3.5 Generierung | `/suno dark synthwave` |
| `/freebeat <prompt>` | MusicGen via HuggingFace | `/freebeat cinematic orchestral` |
| `/humming` / `/summen` | Song per Summen erkennen (AudD) | (reply Audio) |

### **💾 Brain & Converter**
| Command | Beschreibung | Beispiel |
|---------|--------------|----------|
| `/upload` | Datei/Text dauerhaft im Brain speichern | (reply Datei) `/upload` |
| `/brainlist` | Brain-UI mit Checkbox-Löschfunktion | `/brainlist` |
| `/semantic <query>` | Semantische Vektorsuche im Brain | `/semantic Notizen zu KI` |
| `/synchdata <id>` | Einzelnen Brain-Eintrag in Kontext laden | `/synchdata 12345` |
| `/synchroall` | Gesamtes Brain in Kontext laden | `/synchroall` |
| `/convert <ziel>` | Datei konvertieren (reply Datei) | `/convert pdf` |
| `/textconvert <ziel> \|\| <text>` | Text zu Dateiformat konvertieren | `/textconvert docx Hallo` |

### **📺 YouTube & Social**
| Command | Beschreibung | Beispiel |
|---------|--------------|----------|
| `/yt <url>` | Transcript + Zusammenfassung (PDF/TXT) | `/yt https://youtube.com/...` |
| `/workflow <idee>` | Content-Paket (Hook, Script, Shotlist) | `/workflow TikTok Reel KI` |
| `/social <idee>` | Social-Media-Plan (IG, TikTok, LinkedIn) | `/social Launch Kampagne` |
| `/mailbatch <betreff>` | E-Mail-Batch vorbereiten (reply Datei) | `/mailbatch Newsletter Januar` |

### **⚙️ System & Utils**
| Command | Beschreibung | Modul |
|---------|--------------|-------|
| `/privacy` | Privacy-Modus (kein Chat-Logging) | `guard.py` |
| `/guard` | Rate-Limit-Status anzeigen | `guard.py` |
| `/audit` | Modul-Selbsttest / System-Check | `handlers_cmd.py` |
| `/gmail_auth` | Gmail OAuth-Flow starten | `emgen.py` |

---

## 🔍 System Audit (Health Check)

| Status | Komponente | Analyse / Empfehlung |
|:---:|---|---|
| ✅ | **Polling & Watchdog** | Robust mit Exponential Backoff & Webhook-Cleanup. |
| ✅ | **AI Fallbacks** | LLaMA-4 $\rightarrow$ 3.3 $\rightarrow$ Mixtral $\rightarrow$ Gemma2 (Stabil). |
| ✅ | **Brain Storage** | Hybride Vektorsuche (82% Vektor / 18% Lexikalisch). |
| ⚠️ | **Sicherheit** | API-Keys in `suno_music.py` & `free_music.py` $\rightarrow$ `os.getenv`. |
| ⚠️ | **Cleanup** | Lösche `_fixed.py` Duplikate und `youtube.py`. |
| ⚠️ | **Bug** | Fix Timeout-Logik in `ttv26.py`. |
| 🔴 | **Kritisch** | Synchrone Aufrufe in `brain.py` & `claude_code.py` $\rightarrow$ `asyncio.to_thread`. |

---

## ⚙️ Setup & Env Vars (Railway)

```bash
# Quickstart
git clone https://github.com/dein-user/telllmeeedrei.git && cd telllmeeedrei
pip install -r requirements.txt
railway up
```

**Wichtige Variablen:**
- `TELEGRAM_BOT_TOKEN` (Pflicht)
- `GROQ_API_KEY` (Pflicht: LLM/Whisper/TTS)
- `SUPABASE_URL` / `SUPABASE_KEY` (Pflicht: Brain)
- `ANTHROPIC_API_KEY` (Optional: Claude Code)
- `DASHSCOPE_API_KEY` (Optional: Video/Edit)
- `HF_TOKEN` (Optional: FLUX/MusicGen)
- `GEMINI_API_KEY` (Optional: Lyria)

---

## 🏗️ Architektur & Struktur

**Flow:** `User` $\rightarrow$ `FastAPI Polling` $\rightarrow$ `Handlers` $\rightarrow$ `Core (AI/Brain/Guard)` $\rightarrow$ `API`

**Datenbank (Supabase):**
- `brain_entries`: CRUD für Texte und Dateien.
- `brain_vectors`: `vector(384)` für semantische Suche.

**Modul-Tree (Highlights):**
- `main.py`: Entrypoint & Polling-Watchdog.
- `bot_ai.py`: KI-Logik & TTS-Kaskade.
- `agent.py`: Generischer Tool-Loop.
- `parser.py`: Universal-Dateikonverter.
- `voicecl.py`: XTTS-v2 Klonung.

---
**Powered by Groq · Claude · FLUX.1 · Lyria · Suno · Dashscope · Supabase · Railway**
```
