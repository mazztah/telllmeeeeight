# musika_music.py – FIXED für Railway (Lazy Loading)
import os
import shutil
import logging
import asyncio
import subprocess
from io import BytesIO
from pathlib import Path

import torch
from huggingface_hub import hf_hub_download

logger = logging.getLogger(__name__)

class MusikaGenerator:
    def __init__(self, base_path="musika_models"):
        self.base_path = Path(base_path).absolute()
        self.base_path.mkdir(exist_ok=True)
        self.ready = False
        self._models_downloaded = False
        # WICHTIG: Hier KEIN self._download_models() mehr!
        
    async def _download_models(self):
        """Lädt Modelle nur wenn wirklich gebraucht (Lazy)"""
        if self._models_downloaded:
            return
            
        print("🔄 Musika: Downloading / Checking models (~1.5-2 GB)...")

        configs = [
            ("ae", "marcop/musika_ae", ["enc.h5", "enc2.h5", "dec.h5", "dec2.h5"]),
            ("techno", "marcop/musika_techno", ["critic.h5", "gen.h5", "gen_ema.h5", "opt_dec.npy", "opt_disc.npy", "switch.npy"]),
            ("misc", "marcop/musika_misc", ["critic.h5", "gen.h5", "gen_ema.h5", "opt_dec.npy", "opt_disc.npy", "switch.npy"]),
            ("misc_small", "marcop/musika_misc_small", ["critic.h5", "gen.h5", "gen_ema.h5", "opt_dec.npy", "opt_disc.npy", "switch.npy"]),
        ]

        for folder, repo_id, files in configs:
            folder_path = self.base_path / folder
            folder_path.mkdir(exist_ok=True)
            for file in files:
                target = folder_path / file
                if not target.exists():
                    try:
                        cached = hf_hub_download(repo_id=repo_id, filename=file, cache_dir=str(self.base_path))
                        shutil.copy2(cached, target)
                        logger.info(f"✅ Downloaded {folder}/{file}")
                    except Exception as e:
                        logger.error(f"❌ Download failed {folder}/{file}: {e}")

        self._models_downloaded = True
        print("✅ Musika models ready!")

    def _check_ready(self):
        """Prüft ob alle wichtigen Dateien vorhanden sind"""
        required = ["ae/enc.h5", "techno/gen_ema.h5", "misc/gen_ema.h5"]
        missing = [f for f in required if not (self.base_path / f).exists()]
        if missing:
            logger.warning(f"Musika missing files: {missing}")
            self.ready = False
        else:
            self.ready = True
            logger.info("🎼 Musika fully ready!")

    async def generate(self, prompt: str, duration: int = 30, style: str = "techno") -> BytesIO | None:
        """Generiert Musik mit Musika (Lazy Loading)"""
        
        # LAZY: Erst jetzt laden!
        if not self._models_downloaded:
            await self._download_models()
            self._check_ready()
            
        if not self.ready:
            logger.error("Musika models not ready")
            return None

        try:
            logger.info(f"🎹 Musika start: '{prompt}' | Style: {style} | Duration: {duration}s")
            
            # Rest deiner Logik bleibt gleich...
            # ... (deine bisherige generate Logik)
            
            style = style.lower()
            if "techno" in prompt.lower() or "bass" in prompt.lower() or "drop" in prompt.lower():
                style = "techno"
            else:
                style = "misc"

            output_dir = self.base_path / "generations"
            output_dir.mkdir(exist_ok=True)
            
            # Hier deine bisherige Generierungs-Logik...
            # (Code aus deiner Originaldatei ab Zeile 78)
            
            return None  # Platzhalter - deine Original-Logik hier einfügen

        except Exception as e:
            logger.error(f"Musika generation error: {e}")
            return None


# Globale Instanz (jetzt ohne sofortigen Download!)
musika_generator = MusikaGenerator()

async def generate_musika_music(prompt: str, style: str = "techno", duration: int = 30) -> BytesIO | None:
    """Öffentliche async Funktion für den Bot"""
    return await musika_generator.generate(prompt, duration, style)
