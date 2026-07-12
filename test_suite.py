# test_suite.py – ULTIMATE DIAGNOSTICS SUITE
# Testet ALLE Module des telllmeeedrei Bots

import asyncio
import os
import sys
import time
import json
import tempfile
import importlib
import inspect
from datetime import datetime
from typing import Dict, List, Any, Optional
from io import BytesIO
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class UltimateDiagnostics:
    def __init__(self):
        self.results = []
        self.start_time = time.time()
        self.test_env = {}
        
    def add_result(self, module: str, test: str, status: bool, 
                   message: str = "", duration: float = 0, critical: bool = False):
        self.results.append({
            "module": module,
            "test": test,
            "status": "✅" if status else "❌",
            "ok": status,
            "critical": critical,
            "message": str(message)[:200],
            "duration": f"{duration:.3f}s",
            "timestamp": datetime.now().isoformat()
        })
        
    async def run_all_tests(self) -> Dict[str, Any]:
        """Master-Test-Runner"""
        test_groups = [
            ("CORE", self.test_core_modules),
            ("AI_APIS", self.test_ai_apis),
            ("BRAIN_MEMORY", self.test_brain_system),
            ("MEDIA_GENERATION", self.test_media_modules),
            ("VOICE_AUDIO", self.test_voice_system),
            ("3D_GRAPHICS", self.test_3d_system),
            ("WEB_INTEGRATION", self.test_web_modules),
            ("UTILITIES", self.test_utility_modules),
            ("HANDLERS", self.test_handlers),
            ("MINI_APPS", self.test_mini_apps),
            ("SECURITY", self.test_security),
        ]
        
        for category, test_func in test_groups:
            try:
                await test_func()
            except Exception as e:
                self.add_result(category, "GROUP_ERROR", False, f"Crash: {str(e)}", critical=True)
                
        return self._compile_report()
    
    def _compile_report(self) -> Dict[str, Any]:
        total = len(self.results)
        passed = sum(1 for r in self.results if r["ok"])
        critical_failed = sum(1 for r in self.results if r["critical"] and not r["ok"])
        
        return {
            "overall_status": "healthy" if critical_failed == 0 else "critical_issues" if critical_failed > 0 else "issues",
            "total_tests": total,
            "passed": passed,
            "failed": total - passed,
            "critical_failures": critical_failed,
            "duration": f"{time.time() - self.start_time:.2f}s",
            "timestamp": datetime.now().isoformat(),
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "results_by_module": self._group_results(),
            "results": self.results
        }
    
    def _group_results(self) -> Dict[str, List[Dict]]:
        groups = {}
        for r in self.results:
            mod = r["module"]
            if mod not in groups:
                groups[mod] = []
            groups[mod].append(r)
        return groups

    # ───────────────────────────────────────────────
    # CORE MODULES
    # ───────────────────────────────────────────────
    
    async def test_core_modules(self):
        """Testet Kern-Module"""
        start = time.time()
        
        # 1. bot_state.py
        try:
            from bot_state import application, client, TELEGRAM_BOT_TOKEN
            self.add_result("bot_state", "Import", True, "Core geladen", time.time()-start)
            
            # Prüfe ob Client initialisiert
            has_client = client is not None
            self.add_result("bot_state", "Groq_Client", has_client, 
                          "Groq-Client initialisiert" if has_client else "Fehlt!", critical=True)
        except Exception as e:
            self.add_result("bot_state", "Import", False, str(e), critical=True)
        
        # 2. guard.py
        try:
            from guard import check_rate_limit, toggle_privacy_mode, can_process_text
            test_decision = check_rate_limit("test123", "chat")
            self.add_result("guard", "Import_Functions", True, 
                          f"Rate-Limit: {test_decision.allowed}", time.time()-start)
        except Exception as e:
            self.add_result("guard", "Import", False, str(e), critical=True)
        
        # 3. bot_utils.py
        try:
            from bot_utils import build_agent_tools, create_download_buffer
            tools = build_agent_tools("test_chat")
            self.add_result("bot_utils", "Agent_Tools", len(tools) > 0, 
                          f"{len(tools)} Tools verfügbar", time.time()-start)
        except Exception as e:
            self.add_result("bot_utils", "Import", False, str(e))
        
        # 4. agent.py
        try:
            from agent import run_agent_loop, AgentTool
            self.add_result("agent", "Import", True, "Agent-Loop verfügbar", time.time()-start)
        except Exception as e:
            self.add_result("agent", "Import", False, str(e), critical=True)

    # ───────────────────────────────────────────────
    # AI APIS
    # ───────────────────────────────────────────────
    
    async def test_ai_apis(self):
        """Testet alle KI-APIs"""
        
        # Groq Test (Ping)
        try:
            from bot_state import client as groq_client
            start = time.time()
            # Billigster Test: Models auflisten
            models = await asyncio.to_thread(lambda: groq_client.models.list())
            self.add_result("api_groq", "Connection", True, 
                          f"Models: {len(models.data)}", time.time()-start)
        except Exception as e:
            self.add_result("api_groq", "Connection", False, str(e), critical=True)
        
        # Anthropic (Claude)
        try:
            import anthropic
            key = os.getenv("ANTHROPIC_API_KEY")
            if key:
                self.add_result("api_anthropic", "Key_Present", True, "Key vorhanden")
            else:
                self.add_result("api_anthropic", "Key_Present", False, "Key fehlt", critical=False)
        except Exception as e:
            self.add_result("api_anthropic", "Import", False, str(e))
        
        # HuggingFace
        try:
            import huggingface_hub
            key = os.getenv("HF_TOKEN")
            self.add_result("api_huggingface", "Config", True, 
                          f"Token: {'✅' if key else '❌'}", critical=False)
        except Exception as e:
            self.add_result("api_huggingface", "Import", False, str(e))
        
        # DashScope (Video/Bild)
        try:
            key = os.getenv("DASHSCOPE_API_KEY")
            self.add_result("api_dashscope", "Config", bool(key), 
                          "Video/Edit API konfiguriert" if key else "Fehlt", critical=False)
        except Exception as e:
            self.add_result("api_dashscope", "Check", False, str(e))
        
        # Google (Lyria)
        try:
            key = os.getenv("GEMINI_API_KEY")
            self.add_result("api_google", "Config", bool(key), 
                          f"Lyria/GenAI: {'✅' if key else '❌'}", critical=False)
        except Exception as e:
            self.add_result("api_google", "Check", False, str(e))

    # ───────────────────────────────────────────────
    # BRAIN & MEMORY
    # ───────────────────────────────────────────────
    
    async def test_brain_system(self):
        """Testet alle Brain-Module"""
        
        modules_to_test = [
            ("brain", "CRUD Operations"),
            ("vectorbrain", "Vector Search"),
            ("brainlist_handler", "UI Handler")
        ]
        
        for mod_name, desc in modules_to_test:
            try:
                start = time.time()
                module = importlib.import_module(mod_name)
                self.add_result(f"brain_{mod_name}", "Import", True, 
                              f"{desc} geladen", time.time()-start)
                
                # Spezifische Tests für brain.py
                if mod_name == "brain":
                    from brain import save_text, is_enabled
                    start = time.time()
                    result = await save_text("test", "Hallo Welt")
                    is_async = time.time() - start < 2.0
                    self.add_result("brain", "Async_Save", is_async, 
                                  f"Response: {result[:30]}...", time.time()-start)
                    
            except Exception as e:
                self.add_result(f"brain_{mod_name}", "Import", False, str(e), 
                              critical=(mod_name=="brain"))

    # ───────────────────────────────────────────────
    # MEDIA GENERATION
    # ───────────────────────────────────────────────
    
    async def test_media_modules(self):
        """Bild, Video, Musik"""
        
        # Image Generation (FLUX)
        try:
            from imgrem import generate_image
            self.add_result("media_imgrem", "Import", True, "FLUX bereit")
        except Exception as e:
            self.add_result("media_imgrem", "Import", False, str(e))
        
        # Image Editing
        try:
            from imgedi import edit_image
            from imagedit import edit_image_kontext
            self.add_result("media_imgedi", "Import", True, "Edit-Module bereit")
        except Exception as e:
            self.add_result("media_imgedi", "Import", False, str(e))
        
        # Video Generation
        try:
            from textvideo import generate_text_to_video
            from ttv26 import generate_text_to_video as ttv26_gen
            self.add_result("media_video", "Import", True, "Video-Module bereit")
        except Exception as e:
            self.add_result("media_video", "Import", False, str(e))
        
        # Musik-Module
        music_modules = [
            ("lyria_music", "Lyria 3"),
            ("suno_music", "Suno"),
            ("free_music", "MusicGen"),
            ("hybrid_music", "Hybrid"),
            ("musika_music", "Musika")
        ]
        
        for mod, name in music_modules:
            try:
                importlib.import_module(mod)
                self.add_result(f"music_{mod}", "Import", True, f"{name} geladen")
            except Exception as e:
                self.add_result(f"music_{mod}", "Import", False, str(e))

    # ───────────────────────────────────────────────
    # VOICE & AUDIO
    # ───────────────────────────────────────────────
    
    async def test_voice_system(self):
        """Voice Cloning, TTS, Stream"""
        
        voice_modules = [
            ("voicecl", "Voice Cloning"),
            ("voicestream", "Voice Stream"),
            ("voice_mini_app", "Mini App"),
            ("bot_ai", "TTS/Whisper")
        ]
        
        for mod, desc in voice_modules:
            try:
                m = importlib.import_module(mod)
                self.add_result(f"voice_{mod}", "Import", True, desc)
            except Exception as e:
                self.add_result(f"voice_{mod}", "Import", False, str(e))
        
        # Spezifischer Whisper-Test
        try:
            from bot_ai import transcribe_voice
            self.add_result("voice_whisper", "Function", True, "Transkription bereit")
        except Exception as e:
            self.add_result("voice_whisper", "Function", False, str(e))
        
        # Song-Erkennung
        try:
            from thesong import recognize_song, recognize_humming
            self.add_result("voice_thesong", "Import", True, "AudD bereit")
        except Exception as e:
            self.add_result("voice_thesong", "Import", False, str(e))

    # ───────────────────────────────────────────────
    # 3D SYSTEM
    # ───────────────────────────────────────────────
    
    async def test_3d_system(self):
        """3D Konvertierung, Text-to-3D, InstantMesh"""
        
        # Converter3D
        try:
            from converter3d import converter3d, Converter3D
            providers = ["_try_trimesh", "_try_pyrender", "_try_assimp", 
                        "_try_blender", "_try_f3d", "_try_convertio"]
            available = sum(1 for p in providers if hasattr(converter3d, p))
            self.add_result("3d_converter", "Providers", available >= 3, 
                          f"{available}/8 Provider verfügbar", critical=True)
        except Exception as e:
            self.add_result("3d_converter", "Import", False, str(e), critical=True)
        
        # Handler
        try:
            from handler_convert3d import cmd_convert3d, handle_3d_document
            self.add_result("3d_handler", "Import", True, "Telegram Handler bereit")
        except Exception as e:
            self.add_result("3d_handler", "Import", False, str(e))
        
        # Text-to-3D
        try:
            from text_to_3d import text_to_3d
            self.add_result("3d_text2mesh", "Import", True, "Text-to-3D bereit")
        except Exception as e:
            self.add_result("3d_text2mesh", "Import", False, str(e))
        
        # InstantMesh (lokal)
        try:
            from instantmesh import mesh_handler
            self.add_result("3d_instantmesh", "Import", True, "InstantMesh bereit (schwer)")
        except Exception as e:
            self.add_result("3d_instantmesh", "Import", False, str(e), critical=False)

    # ───────────────────────────────────────────────
    # WEB & SEARCH
    # ───────────────────────────────────────────────
    
    async def test_web_modules(self):
        """YouTube, Web-Suche, Email"""
        
        # YouTube
        try:
            from ytscript import get_youtube_script, extract_youtube_url
            from youtube import extract_video_id
            test_url = "https://youtube.com/watch?v=dQw4w9WgXcQ"
            vid_id = extract_video_id(test_url)
            self.add_result("web_youtube", "Parser", vid_id == "dQw4w9WgXcQ", 
                          f"ID Extraction: {vid_id}")
        except Exception as e:
            self.add_result("web_youtube", "Import", False, str(e))
        
        # Web Search
        try:
            from search import web_search, has_valid_serpapi_key
            has_key = has_valid_serpapi_key()
            self.add_result("web_search", "Config", True, 
                          f"SerpAPI: {'✅' if has_key else '❌'}", critical=False)
        except Exception as e:
            self.add_result("web_search", "Import", False, str(e))
        
        # Email
        try:
            from emgen import start_gmail_auth, parse_email_list
            self.add_result("web_email", "Import", True, "Gmail-Integration bereit")
        except Exception as e:
            self.add_result("web_email", "Import", False, str(e))
        
        # Social
        try:
            from social import build_social_pack, schedule_buffer_post
            self.add_result("web_social", "Import", True, "Social-Pack bereit")
        except Exception as e:
            self.add_result("web_social", "Import", False, str(e))

    # ───────────────────────────────────────────────
    # UTILITIES
    # ───────────────────────────────────────────────
    
    async def test_utility_modules(self):
        """Parser, Code, Vision, Workflow"""
        
        utils = [
            ("parser", "Universal Parser"),
            ("dv", "Data Processor"),
            ("codeinterpreter", "Code Execution"),
            ("vision", "Vision Analysis"),
            ("workflow", "Workflow Engine"),
            ("openclaw", "OpenClaw Agent"),
            ("superagent", "SuperAgent"),
            ("claude_code", "Claude Code"),
            ("olko", "Claude Helper")
        ]
        
        for mod, desc in utils:
            try:
                importlib.import_module(mod)
                self.add_result(f"util_{mod}", "Import", True, desc)
            except Exception as e:
                self.add_result(f"util_{mod}", "Import", False, str(e), 
                              critical=(mod in ["parser", "codeinterpreter"]))
        
        # Vision spezifisch
        try:
            from vision import analyze_images, VISION_MODELS
            self.add_result("util_vision", "Models", len(VISION_MODELS) > 0, 
                          f"{len(VISION_MODELS)} Vision Models")
        except Exception as e:
            self.add_result("util_vision", "Check", False, str(e))

    # ───────────────────────────────────────────────
    # HANDLERS (Telegram)
    # ───────────────────────────────────────────────
    
    async def test_handlers(self):
        """Telegram Handler"""
        
        handler_files = [
            ("handlers_chat", "Chat Handler"),
            ("handlers_cmd", "Command Handler"),
            ("handlers_media", "Media Handler"),
        ]
        
        for file, desc in handler_files:
            try:
                importlib.import_module(file)
                self.add_result(f"handler_{file}", "Import", True, desc)
            except Exception as e:
                self.add_result(f"handler_{file}", "Import", False, str(e), critical=True)

    # ───────────────────────────────────────────────
    # MINI APPS
    # ───────────────────────────────────────────────
    
    async def test_mini_apps(self):
        """Flask/FastAPI Mini Apps"""
        
        apps = [
            ("mini_app", "Aura Defense Game"),
            ("youtube_mini_app", "YouTube Viewer"),
            ("soundcloud_backend", "SoundCloud"),
            ("diagnose_app", "Diese Diagnose"),
        ]
        
        for app, desc in apps:
            try:
                importlib.import_module(app)
                self.add_result(f"miniapp_{app}", "Import", True, desc)
            except Exception as e:
                self.add_result(f"miniapp_{app}", "Import", False, str(e), critical=False)

    # ───────────────────────────────────────────────
    # SECURITY & MISC
    # ───────────────────────────────────────────────
    
    async def test_security(self):
        """Security Checks"""
        
        # Prüfe auf hardcoded Keys (nach den Fixes sollte das passen)
        dangerous_patterns = ["1e321224bf459ba411062764eb89e97f", "hf_GmKchic"]
        found_issues = []
        
        for root, dirs, files in os.walk("/app"):
            for file in files:
                if file.endswith(".py") and not file.startswith("test_"):
                    try:
                        with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                            content = f.read()
                            for pattern in dangerous_patterns:
                                if pattern in content:
                                    found_issues.append(f"{file}: Hardcoded Key!")
                    except:
                        pass
        
        self.add_result("security", "Hardcoded_Keys", len(found_issues) == 0, 
                      f"Issues: {len(found_issues)}", critical=len(found_issues) > 0)
        
        # File Permissions
        try:
            test_file = "/tmp/security_test"
            with open(test_file, 'w') as f:
                f.write("test")
            os.chmod(test_file, 0o777)
            os.unlink(test_file)
            self.add_result("security", "File_Permissions", True, "R/W/X OK")
        except Exception as e:
            self.add_result("security", "File_Permissions", False, str(e))

# ─── Singleton ───
diagnostics = UltimateDiagnostics()

async def run_diagnostics():
    return await diagnostics.run_all_tests()
