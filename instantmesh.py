import asyncio
import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from guard import check_rate_limit

PROJECT_ROOT = Path(__file__).resolve().parent
INSTANTMESH_DIR = PROJECT_ROOT / "modules" / "instantmesh"
RUN_SCRIPT = INSTANTMESH_DIR / "run.py"
CONFIG_PATH = INSTANTMESH_DIR / "configs" / "instant-mesh-large.yaml"

# rembg stays optional because we execute with --no_rembg by default.
REQUIRED_PACKAGES = [
    "torch",
    "pytorch_lightning",
    "omegaconf",
    "einops",
    "trimesh",
    "mcubes",
    "diffusers",
    "transformers",
    "nvdiffrast",
]


def _collect_preflight_errors() -> list[str]:
    errors: list[str] = []

    if not INSTANTMESH_DIR.exists():
        errors.append("Ordner fehlt: modules/instantmesh")
    if not RUN_SCRIPT.exists():
        errors.append("Datei fehlt: modules/instantmesh/run.py")
    if not CONFIG_PATH.exists():
        errors.append("Datei fehlt: modules/instantmesh/configs/instant-mesh-large.yaml")

    missing = [pkg for pkg in REQUIRED_PACKAGES if importlib.util.find_spec(pkg) is None]
    if missing:
        errors.append("Fehlende Python-Pakete: " + ", ".join(missing))

    torch_spec = importlib.util.find_spec("torch")
    if torch_spec is not None:
        try:
            import torch  # type: ignore

            if not torch.cuda.is_available():
                errors.append("Keine CUDA-GPU verfuegbar (InstantMesh braucht GPU).")
        except Exception as exc:
            errors.append(f"Torch-Check fehlgeschlagen: {exc}")

    return errors


def _format_preflight_message(errors: list[str]) -> str:
    lines = ["InstantMesh kann gerade nicht gestartet werden:", ""]
    lines.extend(f"- {item}" for item in errors)
    lines.extend(
        [
            "",
            "Hinweis: Im schlanken Railway-Deploy ist /3d (API-Kaskade) empfohlen.",
            "Lokales /mesh braucht eine CUDA-GPU und schwere Zusatzpakete.",
        ]
    )
    return "\n".join(lines)


async def generate_mesh(
    image_path: str,
    output_dir: str,
    export_texmap: bool = False,
) -> tuple[Optional[Path], Optional[Path], str]:
    """
    Run InstantMesh run.py asynchronously.
    Returns: (obj_path, video_path, logs_or_error)
    """
    cmd = [
        sys.executable,
        str(RUN_SCRIPT),
        str(CONFIG_PATH),
        image_path,
        "--save_video",
        "--no_rembg",
        "--output_path",
        output_dir,
    ]
    if export_texmap:
        cmd.append("--export_texmap")

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(INSTANTMESH_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        std_out = stdout.decode(errors="replace")
        std_err = stderr.decode(errors="replace")
        combined_logs = (std_out + "\n" + std_err).strip()

        if process.returncode != 0:
            return None, None, combined_logs or "Unbekannter InstantMesh-Fehler."

        obj_files = list(Path(output_dir).rglob("*.obj"))
        if not obj_files:
            return None, None, combined_logs or "Kein OBJ im Output gefunden."

        obj_path = max(obj_files, key=os.path.getctime)
        candidate_videos = list(Path(output_dir).rglob(f"{obj_path.stem}.mp4"))
        video_path = max(candidate_videos, key=os.path.getctime) if candidate_videos else None
        return obj_path, video_path, combined_logs
    except Exception as exc:
        return None, None, f"Subprocess-Fehler: {exc}"


async def mesh_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    payload = " ".join(context.args).strip()

    decision = check_rate_limit(chat_id, "mesh")
    if not decision.allowed:
        await update.message.reply_text(decision.message)
        return

    loading = await update.message.reply_text("InstantMesh startet. Das kann mehrere Minuten dauern.")

    preflight_errors = _collect_preflight_errors()
    if preflight_errors:
        await loading.edit_text(_format_preflight_message(preflight_errors))
        return

    image_path: Optional[str] = None
    output_dir: Optional[Path] = None

    try:
        if update.message.reply_to_message and update.message.reply_to_message.photo:
            file = await context.bot.get_file(update.message.reply_to_message.photo[-1].file_id)
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_file:
                await file.download_to_drive(temp_file.name)
                image_path = temp_file.name
        elif payload:
            try:
                from imgrem import generate_image

                img_bytes = await generate_image(payload)
            except ImportError:
                await loading.edit_text("Bildgenerator nicht verfuegbar. Bitte antworte auf ein Bild mit /mesh.")
                return

            if not img_bytes:
                await loading.edit_text("Bildgenerierung fehlgeschlagen. Bitte mit Reply-Bild erneut probieren.")
                return

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
                temp_file.write(img_bytes)
                image_path = temp_file.name
        else:
            await loading.edit_text("Nutzung: Antworte auf ein Bild mit /mesh oder nutze /mesh <prompt>.")
            return

        output_dir = Path(tempfile.mkdtemp(prefix="instantmesh_"))
        obj_path, video_path, logs = await generate_mesh(image_path=image_path, output_dir=str(output_dir))

        if not obj_path:
            truncated_logs = logs[-1200:] if logs else "Keine Logs vorhanden."
            await loading.edit_text(
                "Mesh-Generierung fehlgeschlagen.\n\n"
                "Kurzlog:\n"
                f"{truncated_logs}"
            )
            return

        with open(obj_path, "rb") as mesh_file:
            await context.bot.send_document(
                chat_id=chat_id,
                document=mesh_file,
                caption=f"3D Mesh fertig: {obj_path.name}\nImport in Blender oder MeshLab.",
            )

        if video_path and video_path.exists():
            with open(video_path, "rb") as render_video:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=render_video,
                    caption="Render-Video",
                )

        await loading.edit_text("InstantMesh abgeschlossen.")

    except Exception as exc:
        await loading.edit_text(f"Fehler in /mesh: {exc}")
    finally:
        if image_path and os.path.exists(image_path):
            try:
                os.unlink(image_path)
            except Exception:
                pass

        if output_dir and output_dir.exists():
            try:
                shutil.rmtree(output_dir, ignore_errors=True)
            except Exception:
                pass


__all__ = ["mesh_handler"]
