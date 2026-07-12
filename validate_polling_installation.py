#!/usr/bin/env python3
"""
🔍 Validierungs-Script für Telegram Bot Polling-Installation
Überprüft ob die Polling-Version korrekt installiert ist
"""

import os
import sys
import re
from pathlib import Path

# Farben für Terminal-Ausgabe
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_header(text):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text:^60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.RESET}\n")

def check_ok(text):
    print(f"{Colors.GREEN}✅ {text}{Colors.RESET}")

def check_fail(text):
    print(f"{Colors.RED}❌ {text}{Colors.RESET}")

def check_warn(text):
    print(f"{Colors.YELLOW}⚠️  {text}{Colors.RESET}")

def check_info(text):
    print(f"{Colors.BLUE}ℹ️  {text}{Colors.RESET}")

# ────────────────────────────────────────────────────────────────────────────

print_header("🔍 Telegram Bot Polling Installation Validator")

results = {
    'passed': 0,
    'failed': 0,
    'warnings': 0
}

# ────────────────────────────────────────────────────────────────────────────
print(f"{Colors.BOLD}1. Überprüfe main.py vorhanden...{Colors.RESET}")

main_py_path = Path("main.py")
if not main_py_path.exists():
    check_fail(f"main.py nicht gefunden im Verzeichnis: {os.getcwd()}")
    results['failed'] += 1
    sys.exit(1)
else:
    check_ok(f"main.py gefunden ({main_py_path.stat().st_size} bytes)")
    results['passed'] += 1

# ────────────────────────────────────────────────────────────────────────────
print(f"\n{Colors.BOLD}2. Überprüfe Polling-Implementation...{Colors.RESET}")

with open(main_py_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Überprüfe ob polling_loop existiert
if 'async def polling_loop' in content:
    check_ok("polling_loop() Funktion vorhanden ✨")
    results['passed'] += 1
else:
    check_fail("polling_loop() Funktion NICHT GEFUNDEN - Ist dies die alte Webhook-Version?")
    results['failed'] += 1

# Überprüfe ob keep_alive NICHT existiert (alte Version)
if 'async def keep_alive' in content:
    check_fail("keep_alive() Funktion NOCH VORHANDEN - Das ist die ALTE Webhook-Version!")
    check_warn("Bitte verwende main_POLLING_FIXED.py statt der alten Version")
    results['failed'] += 1
else:
    check_ok("keep_alive() nicht vorhanden (alte Version entfernt) ✨")
    results['passed'] += 1

# Überprüfe ob Webhook-Route vorhanden ist (OK für Fallback)
if '@app.post("/webhook")' in content:
    check_ok("Webhook-Route vorhanden (Fallback-Mode) ✨")
    results['passed'] += 1
else:
    check_warn("Webhook-Route nicht vorhanden")
    results['warnings'] += 1

# ────────────────────────────────────────────────────────────────────────────
print(f"\n{Colors.BOLD}3. Überprüfe Imports...{Colors.RESET}")

# Überprüfe ob asynccontextmanager importiert wird (neuer Lifespan-Mode)
if 'from contextlib import asynccontextmanager' in content:
    check_ok("asynccontextmanager importiert (moderner Lifespan-Mode) ✨")
    results['passed'] += 1
else:
    check_fail("asynccontextmanager NICHT importiert - wird für Lifespan benötigt!")
    results['failed'] += 1

# Überprüfe FastAPI import
if 'from fastapi import FastAPI' in content:
    check_ok("FastAPI korrekt importiert ✨")
    results['passed'] += 1
else:
    check_fail("FastAPI import NICHT GEFUNDEN")
    results['failed'] += 1

# Überprüfe telegram imports (entweder direkt oder via bot_state)
if 'from telegram.ext import Application' in content or 'from bot_state import application' in content:
    check_ok("telegram.ext.Application korrekt importiert ✨")
    results['passed'] += 1
else:
    check_fail("telegram.ext.Application import NICHT GEFUNDEN")
    results['failed'] += 1

# Überprüfe httpx import (für Timeout-Exceptions)
if 'import httpx' in content:
    check_ok("httpx importiert (für Timeout-Handling) ✨")
    results['passed'] += 1
else:
    check_warn("httpx nicht importiert - Timeout-Handling könnte fehlen")
    results['warnings'] += 1

# ────────────────────────────────────────────────────────────────────────────
print(f"\n{Colors.BOLD}4. Überprüfe FastAPI Lifespan...{Colors.RESET}")

if '@asynccontextmanager' in content and 'async def lifespan' in content:
    check_ok("Lifespan-Context-Manager vorhanden (moderner Ansatz) ✨")
    results['passed'] += 1
else:
    check_fail("Lifespan-Context-Manager nicht gefunden")
    results['failed'] += 1

if 'lifespan=lifespan' in content or 'lifespan = lifespan' in content:
    check_ok("FastAPI mit Lifespan konfiguriert ✨")
    results['passed'] += 1
else:
    check_warn("FastAPI Lifespan-Parameter nicht gefunden")
    results['warnings'] += 1

# ────────────────────────────────────────────────────────────────────────────
print(f"\n{Colors.BOLD}5. Überprüfe Offset-Persistenz...{Colors.RESET}")

if '_load_offset' in content and '_save_offset' in content:
    check_ok("Offset-Persistenz implementiert ✨")
    results['passed'] += 1
else:
    check_fail("Offset-Persistenz NICHT GEFUNDEN")
    results['failed'] += 1

if 'last_update_offset.txt' in content or 'OFFSET_FILE' in content:
    check_ok("Offset-Datei konfiguriert ✨")
    results['passed'] += 1
else:
    check_warn("Offset-Datei nicht explizit konfiguriert")
    results['warnings'] += 1

# ────────────────────────────────────────────────────────────────────────────
print(f"\n{Colors.BOLD}6. Überprüfe Watchdog...{Colors.RESET}")

if 'async def _webhook_watchdog' in content:
    check_ok("Webhook-Watchdog vorhanden ✨")
    results['passed'] += 1
else:
    check_fail("Webhook-Watchdog NICHT GEFUNDEN")
    results['failed'] += 1

if 'delete_webhook' in content:
    check_ok("delete_webhook im Watchdog vorhanden ✨")
    results['passed'] += 1
else:
    check_fail("delete_webhook nicht im Watchdog gefunden")
    results['failed'] += 1

# ────────────────────────────────────────────────────────────────────────────
print(f"\n{Colors.BOLD}7. Überprüfe Token & Umgebungsvariablen...{Colors.RESET}")

if 'TELEGRAM_BOT_TOKEN' in content or 'OWNER_CHAT_ID' in content:
    check_ok("TELEGRAM_BOT_TOKEN Handling vorhanden ✨")
    results['passed'] += 1
else:
    check_fail("TELEGRAM_BOT_TOKEN Handling nicht gefunden")
    results['failed'] += 1

if os.getenv('TELEGRAM_BOT_TOKEN'):
    check_ok(f"TELEGRAM_BOT_TOKEN Umgebungsvariable gesetzt ✨")
    results['passed'] += 1
else:
    check_warn(f"TELEGRAM_BOT_TOKEN Umgebungsvariable nicht gesetzt")
    check_info("Das ist OK wenn du lokal testest, aber WICHTIG für Deployment!")
    results['warnings'] += 1

# ────────────────────────────────────────────────────────────────────────────
print(f"\n{Colors.BOLD}8. Überprüfe Handler...{Colors.RESET}")

# Zähle Handlers
handlers = re.findall(r'application\.add_handler', content)
if len(handlers) > 20:
    check_ok(f"{len(handlers)} Handler registriert ✨")
    results['passed'] += 1
else:
    check_warn(f"Nur {len(handlers)} Handler gefunden - erwartet 20+")
    results['warnings'] += 1

# Überprüfe wichtige Handler
important_handlers = [
    ('CommandHandler("start"', "start"),
    ('CommandHandler("imagine"', "imagine"),
    ('MessageHandler(filters.TEXT', "message text"),
    ('MessageHandler(filters.VOICE', "voice"),
]

for pattern, name in important_handlers:
    if pattern in content:
        check_ok(f"{name} Handler vorhanden ✨")
        results['passed'] += 1
    else:
        check_fail(f"{name} Handler NICHT GEFUNDEN")
        results['failed'] += 1

# ────────────────────────────────────────────────────────────────────────────
print(f"\n{Colors.BOLD}9. Überprüfe Syntax...{Colors.RESET}")

try:
    compile(content, 'main.py', 'exec')
    check_ok("Python Syntax ist korrekt ✨")
    results['passed'] += 1
except SyntaxError as e:
    check_fail(f"Syntax Fehler gefunden: {e}")
    results['failed'] += 1

# ────────────────────────────────────────────────────────────────────────────
print(f"\n{Colors.BOLD}10. Überprüfe requirements...{Colors.RESET}")

requirements_path = Path("requirements.txt")
if requirements_path.exists():
    with open(requirements_path, 'r') as f:
        req_content = f.read()
    
    required_packages = [
        ('python-telegram-bot', 'Telegram Bot Library'),
        ('fastapi', 'FastAPI Framework'),
        ('uvicorn', 'ASGI Server'),
        ('groq', 'Groq API'),
    ]
    
    for package, name in required_packages:
        if package in req_content:
            check_ok(f"{name} ({package}) in requirements.txt ✨")
            results['passed'] += 1
        else:
            check_warn(f"{name} ({package}) nicht in requirements.txt")
            results['warnings'] += 1
else:
    check_warn("requirements.txt nicht gefunden")
    results['warnings'] += 1

# ────────────────────────────────────────────────────────────────────────────
print(f"\n{Colors.BOLD}11. Überprüfe externe Module...{Colors.RESET}")

external_modules = [
    'search.py',
    'brain.py',
    'vision.py',
    'imgrem.py',
]

for module in external_modules:
    if Path(module).exists():
        check_ok(f"{module} vorhanden ✨")
        results['passed'] += 1
    else:
        check_warn(f"{module} nicht gefunden (aber könnte OK sein)")
        results['warnings'] += 1

# ────────────────────────────────────────────────────────────────────────────
print(f"\n{Colors.BOLD}12. Überprüfe render.yaml...{Colors.RESET}")

render_yaml_path = Path("render.yaml")
if render_yaml_path.exists():
    with open(render_yaml_path, 'r') as f:
        render_content = f.read()
    
    if 'USE_WEBHOOK' in render_content:
        if 'false' in render_content.lower():
            check_ok("render.yaml: USE_WEBHOOK=false ✨")
            results['passed'] += 1
        else:
            check_fail("render.yaml: USE_WEBHOOK ist nicht auf false gesetzt!")
            results['failed'] += 1
    else:
        check_warn("USE_WEBHOOK nicht in render.yaml gefunden")
        results['warnings'] += 1
else:
    check_warn("render.yaml nicht gefunden")
    results['warnings'] += 1

# ────────────────────────────────────────────────────────────────────────────
print_header("📊 Validierungs-Ergebnis")

print(f"\n{Colors.GREEN}✅ Bestanden: {results['passed']}{Colors.RESET}")
print(f"{Colors.RED}❌ Fehler: {results['failed']}{Colors.RESET}")
print(f"{Colors.YELLOW}⚠️  Warnungen: {results['warnings']}{Colors.RESET}")

# ────────────────────────────────────────────────────────────────────────────

if results['failed'] == 0:
    print(f"\n{Colors.GREEN}{Colors.BOLD}🚀 PERFEKT! Deine main.py ist richtig für Polling konfiguriert!{Colors.RESET}")
    print(f"\n{Colors.BOLD}Nächste Schritte:{Colors.RESET}")
    print(f"1. Setze deine Umgebungsvariablen:")
    print(f"   export TELEGRAM_BOT_TOKEN='dein-token'")
    print(f"   export GROQ_API_KEY='dein-key'")
    print(f"\n2. Starte den Bot:")
    print(f"   python main.py")
    print(f"\n3. Teste in Telegram:")
    print(f"   Schreibe /start")
    print(f"   Bot sollte SOFORT antworten (nicht nach 4 Min!)")
    print(f"\n4. Für Render/Railway Free Tier:")
    print(f"   - Registriere einen Ping-Service (z.B. UptimeRobot)")
    print(f"   - Pinge alle 5 Minuten auf /ping")
    print(f"   - Siehe POLLING_KEEPALIVE.md für Details")
    sys.exit(0)
else:
    print(f"\n{Colors.RED}{Colors.BOLD}❌ Es gibt Fehler zu beheben!{Colors.RESET}")
    print(f"\n{Colors.BOLD}Überprüfe:{Colors.RESET}")
    if 'keep_alive' in content:
        print(f"  - Du verwendest noch die ALTE Webhook-Version")
        print(f"  - Verwende stattdessen: main_POLLING_FIXED.py")
    if 'asynccontextmanager' not in content:
        print(f"  - asynccontextmanager fehlt - wird für Lifespan benötigt")
    if '_load_offset' not in content:
        print(f"  - Offset-Persistenz fehlt - wichtig für Restart-Verhalten")
    print(f"\n{Colors.BOLD}Lösung:{Colors.RESET}")
    print(f"  Siehe POLLING_KEEPALIVE.md für Setup-Anleitung")
    sys.exit(1)

