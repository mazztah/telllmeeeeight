from __future__ import annotations

import asyncio
import base64
import logging
import os
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any, Optional, Sequence

import httpx

try:
    import trimesh
except ImportError:
    trimesh = None

try:
    import pyrender
except ImportError:
    pyrender = None

try:
    import pyassimp
    import pyassimp.export
except ImportError:
    pyassimp = None

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Konstanten & Konfiguration
# ─────────────────────────────────────────────────────────────────────────────

SUPPORTED_INPUT  = {".obj", ".glb", ".gltf", ".stl", ".fbx", ".dae", ".ply", ".3ds", ".svg"}
SUPPORTED_OUTPUT = {".glb", ".gltf", ".obj", ".stl", ".fbx", ".svg", ".mp4", ".png", ".ply"}

FORMAT_ALIASES: dict[str, str] = {
    "gltf": "glb",
    "model": "glb",
    "3dmodel": "glb",
    "video": "mp4",
    "animation": "mp4",
    "image": "png",
    "screenshot": "png",
    "mesh": "obj",
}

ConvertResult = tuple[Optional[BytesIO], Optional[str], str]


def _normalize_format(fmt: str) -> str:
    """'GLB' → '.glb', 'gltf' → '.glb' usw."""
    fmt = fmt.strip().lower().lstrip(".")
    fmt = FORMAT_ALIASES.get(fmt, fmt)
    return f".{fmt}"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _cmd_available(cmd: str) -> bool:
    return shutil.which(cmd) is not None


async def _run_subprocess(
    args: Sequence[str],
    timeout: float = 120.0,
    cwd: Optional[str] = None,
) -> tuple[int, str, str]:
    """Führt einen Subprocess async aus."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")
    except asyncio.TimeoutError:
        logger.warning("Subprocess timeout: %s", args[0])
        return -1, "", "timeout"
    except Exception as exc:
        logger.warning("Subprocess error (%s): %s", args[0], exc)
        return -1, "", str(exc)


# ─────────────────────────────────────────────────────────────────────────────
# Haupt-Klasse
# ─────────────────────────────────────────────────────────────────────────────

class Converter3D:
    """
    3D-Multitool mit 8-stufiger Fallback-Kette (pure Python + Cloud).
    """

    def __init__(self) -> None:
        self.http_timeout = _env_float("C3D_HTTP_TIMEOUT", 60.0)
        self.max_mb       = _env_int("C3D_MAX_MB", 50)
        self.proc_timeout = _env_float("C3D_PROC_TIMEOUT", 120.0)

    # ── Public API ────────────────────────────────────────────────────────────

    async def convert(
        self,
        input_path: str,
        target_format: str,
        *,
        chat_id: Optional[str] = None,
    ) -> ConvertResult:
        """
        Konvertiert eine 3D-Datei ins Zielformat.
        
        Args:
            input_path: Lokaler Pfad zur Quelldatei
            target_format: Zielformat ohne Punkt (z.B. "glb", "png", "mp4")
            chat_id: Optional für Logging/Rate-Limiting
            
        Returns:
            (BytesIO | None, url_str | None, provider_name_str)
        """
        _ = chat_id
        target_ext = _normalize_format(target_format)
        src_ext    = Path(input_path).suffix.lower()

        if src_ext not in SUPPORTED_INPUT:
            logger.warning("C3D: Nicht unterstütztes Input-Format: %s", src_ext)
            return None, None, "unsupported_input"

        if target_ext not in SUPPORTED_OUTPUT:
            logger.warning("C3D: Nicht unterstütztes Output-Format: %s", target_ext)
            return None, None, "unsupported_output"

        providers = [
            self._try_trimesh,
            self._try_pyrender,
            self._try_assimp,
            self._try_blender,
            self._try_f3d,
            self._try_convertio,
            self._try_imagetostl,
            self._try_o3dv_node,
        ]

        for provider in providers:
            try:
                result = await provider(input_path, target_ext)
                if result and result[0]:
                    logger.info("C3D: Erfolg via %s → %s", provider.__name__, target_ext)
                    return result
            except Exception:
                logger.exception("C3D: %s hat einen Fehler geworfen", provider.__name__)

        logger.error("C3D: Alle 8 Provider gescheitert für %s → %s", src_ext, target_ext)
        return None, None, "all_failed"

    # ── Provider 1 – Trimesh (Pure Python) ────────────────────────────────────

    async def _try_trimesh(self, src: str, target_ext: str) -> ConvertResult:
        """Trimesh – Pure Python 3D mesh library."""
        if not trimesh:
            return None, None, "trimesh_not_installed"

        try:
            mesh = trimesh.load(src)
            stem = Path(src).stem
            out_path = f"/tmp/{stem}{target_ext}"
            
            if target_ext == ".obj":
                mesh.export(out_path)
            elif target_ext == ".stl":
                mesh.export(out_path, file_type="stl")
            elif target_ext == ".ply":
                mesh.export(out_path, file_type="ply")
            elif target_ext in {".glb", ".gltf"}:
                scene = trimesh.Scene(mesh)
                scene.export(out_path, file_type="gltf")
            else:
                return None, None, "trimesh_format_skipped"

            if os.path.exists(out_path):
                with open(out_path, "rb") as f:
                    return BytesIO(f.read()), None, "Trimesh"
            return None, None, "trimesh_export_failed"
            
        except Exception as e:
            logger.warning("Trimesh failed: %s", e)
            return None, None, "trimesh_error"

    # ── Provider 2 – Pyrender (PNG Render) ────────────────────────────────────

    async def _try_pyrender(self, src: str, target_ext: str) -> ConvertResult:
        """Pyrender – Render 3D to PNG."""
        if target_ext != ".png":
            return None, None, "pyrender_skipped"

        if not pyrender or not trimesh:
            return None, None, "pyrender_not_installed"

        try:
            mesh = trimesh.load(src)
            scene = pyrender.Scene()
            rm = pyrender.Mesh.from_trimesh(mesh)
            scene.add(rm)
            
            r = pyrender.OffscreenRenderer(1024, 1024)
            color, _ = r.render(scene)
            r.delete()
            
            bio = BytesIO()
            from PIL import Image
            Image.fromarray(color).save(bio, "PNG")
            bio.seek(0)
            return bio, None, "Pyrender"
        except Exception as e:
            logger.warning("Pyrender failed: %s", e)
            return None, None, "pyrender_error"

    # ── Provider 3 – Assimp (pyassimp) ──────────────────────────────────────

    async def _try_assimp(self, src: str, target_ext: str) -> ConvertResult:
        """Assimp über pyassimp."""
        if target_ext in {".mp4", ".svg", ".png"}:
            return None, None, "assimp_skipped"
            
        if not pyassimp:
            return None, None, "pyassimp_not_installed"

        def _run_sync() -> Optional[bytes]:
            fmt_map = {
                ".glb": "glb2",
                ".gltf": "gltf2",
                ".obj": "obj",
                ".stl": "stl",
                ".fbx": "fbx",
                ".ply": "ply",
                ".dae": "collada",
            }
            assimp_fmt = fmt_map.get(target_ext)
            if not assimp_fmt:
                return None
                
            with tempfile.NamedTemporaryFile(suffix=target_ext, delete=False) as out_f:
                out_path = out_f.name
                
            try:
                scene = pyassimp.load(src)
                pyassimp.export(scene, out_path, file_type=assimp_fmt)
                pyassimp.release(scene)
                
                with open(out_path, "rb") as f:
                    return f.read()
            finally:
                if os.path.exists(out_path):
                    os.unlink(out_path)

        try:
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, _run_sync)
            if data:
                return BytesIO(data), None, "Assimp"
            return None, None, "assimp_failed"
        except Exception as e:
            logger.warning("Assimp failed: %s", e)
            return None, None, "assimp_error"

    # ── Provider 4 – Blender ─────────────────────────────────────────────────

    async def _try_blender(self, src: str, target_ext: str) -> ConvertResult:
        """Blender CLI."""
        blender = os.getenv("BLENDER_BIN", "blender")
        if not _cmd_available(blender):
            return None, None, "blender_not_found"

        try:
            stem = Path(src).stem
            out_path = f"/tmp/blender_{stem}{target_ext}"
            
            # Blender Python Script für Import/Export
            if target_ext in {".glb", ".gltf"}:
                script = f"""
import bpy
bpy.ops.wm.read_factory_settings()
bpy.ops.import_scene.obj(filepath="{src}")
bpy.ops.export_scene.gltf(filepath="{out_path}", export_format='GLB')
"""
            else:
                script = f"""
import bpy
bpy.ops.wm.read_factory_settings()
bpy.ops.import_scene.obj(filepath="{src}")
bpy.ops.export_scene.obj(filepath="{out_path}")
"""
            
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
                f.write(script)
                script_path = f.name

            cmd = [
                blender,
                "--background",
                "--python", script_path
            ]
            
            returncode, stdout, stderr = await _run_subprocess(cmd, timeout=self.proc_timeout)
            
            os.unlink(script_path)
            
            if returncode == 0 and os.path.exists(out_path):
                with open(out_path, "rb") as f:
                    return BytesIO(f.read()), None, "Blender"
            return None, None, "blender_failed"
            
        except Exception as e:
            logger.warning("Blender failed: %s", e)
            return None, None, "blender_error"

    # ── Provider 5 – F3D ─────────────────────────────────────────────────────

    async def _try_f3d(self, src: str, target_ext: str) -> ConvertResult:
        """F3D – Fast 3D Viewer."""
        if target_ext != ".png":
            return None, None, "f3d_skipped"
            
        f3d_bin = os.getenv("F3D_BIN", "f3d")
        if not _cmd_available(f3d_bin):
            return None, None, "f3d_not_found"

        try:
            stem = Path(src).stem
            out_png = f"/tmp/f3d_{stem}.png"
            
            cmd = [
                f3d_bin,
                src,
                "--output", out_png,
                "--resolution", "1024,1024",
                "--no-interaction"
            ]
            
            returncode, stdout, stderr = await _run_subprocess(cmd, timeout=60.0)
            
            if os.path.exists(out_png):
                with open(out_png, "rb") as f:
                    return BytesIO(f.read()), None, "F3D"
            return None, None, "f3d_failed"
            
        except Exception as e:
            logger.warning("F3D failed: %s", e)
            return None, None, "f3d_error"

    # ── Provider 6 – Convertio (Cloud) ───────────────────────────────────────

    async def _try_convertio(self, src: str, target_ext: str) -> ConvertResult:
        """Convertio Cloud API."""
        api_key = os.getenv("CONVERTIO_API_KEY")
        if not api_key:
            return None, None, "convertio_no_key"

        try:
            file_size = os.path.getsize(src)
            if file_size > self.max_mb * 1024 * 1024:
                return None, None, "convertio_too_large"

            base_url = "https://api.convertio.co/convert"
            
            async with httpx.AsyncClient(timeout=self.http_timeout) as client:
                # 1. Upload & Convert
                with open(src, "rb") as f:
                    file_data = base64.b64encode(f.read()).decode()
                
                payload = {
                    "apikey": api_key,
                    "file": file_data,
                    "filename": os.path.basename(src),
                    "outputformat": target_ext.lstrip(".")
                }
                
                resp = await client.post(base_url, json=payload)
                if resp.status_code != 200:
                    return None, None, "convertio_api_error"
                
                data = resp.json()
                if data.get("status") != "ok":
                    return None, None, "convertio_failed"
                
                # 2. Polling
                task_id = data.get("data", {}).get("id")
                if not task_id:
                    return None, None, "convertio_no_task"
                
                poll_url = f"{base_url}/{task_id}"
                for _ in range(30):  # 30 attempts
                    await asyncio.sleep(2.0)
                    poll_resp = await client.get(poll_url)
                    poll_data = poll_resp.json()
                    
                    if poll_data.get("status") == "ok":
                        result_url = poll_data.get("data", {}).get("output", {}).get("url")
                        if result_url:
                            # 3. Download
                            dl_resp = await client.get(result_url)
                            if dl_resp.status_code == 200:
                                return BytesIO(dl_resp.content), result_url, "Convertio"
                
                return None, None, "convertio_timeout"
                
        except Exception as e:
            logger.warning("Convertio failed: %s", e)
            return None, None, "convertio_error"

    # ── Provider 7 – ImageToStl (Cloud) ──────────────────────────────────────

    async def _try_imagetostl(self, src: str, target_ext: str) -> ConvertResult:
        """ImageToStl Cloud API."""
        try:
            # ImageToStl hat eine simple API für 3D-Modelle
            api_url = "https://api.imagetostl.com/api/v1/convert"
            
            async with httpx.AsyncClient(timeout=self.http_timeout) as client:
                with open(src, "rb") as f:
                    files = {"file": (os.path.basename(src), f, "application/octet-stream")}
                    data = {"format": target_ext.lstrip(".")}
                    
                    resp = await client.post(api_url, files=files, data=data)
                    
                    if resp.status_code == 200:
                        result = resp.json()
                        download_url = result.get("download_url")
                        if download_url:
                            dl_resp = await client.get(download_url)
                            if dl_resp.status_code == 200:
                                return BytesIO(dl_resp.content), download_url, "ImageToStl"
            
            return None, None, "imagetostl_failed"
        except Exception as e:
            logger.warning("ImageToStl failed: %s", e)
            return None, None, "imagetostl_error"

    # ── Provider 8 – O3DV Node ─────────────────────────────────────────────────

    async def _try_o3dv_node(self, src: str, target_ext: str) -> ConvertResult:
        """Online3DViewer Node.js CLI."""
        o3dv_bin = os.getenv("O3DV_BIN", "o3dv")
        if not _cmd_available(o3dv_bin):
            return None, None, "o3dv_not_found"

        try:
            stem = Path(src).stem
            out_dir = f"/tmp/o3dv_{stem}"
            os.makedirs(out_dir, exist_ok=True)
            
            cmd = [
                o3dv_bin,
                "convert",
                src,
                "--output", out_dir,
                "--format", target_ext.lstrip(".")
            ]
            
            returncode, stdout, stderr = await _run_subprocess(cmd, timeout=self.proc_timeout)
            
            if returncode == 0:
                # Suche Ausgabedatei
                for f in os.listdir(out_dir):
                    if f.endswith(target_ext):
                        with open(os.path.join(out_dir, f), "rb") as file:
                            return BytesIO(file.read()), None, "O3DV"
            
            return None, None, "o3dv_failed"
            
        except Exception as e:
            logger.warning("O3DV failed: %s", e)
            return None, None, "o3dv_error"


# ─────────────────────────────────────────────────────────────────────────────
# Singleton-Instanz
# ─────────────────────────────────────────────────────────────────────────────

converter3d = Converter3D()
