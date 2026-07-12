"""
handler_convert3d.py – Telegram Handler für /convert3d
=======================================================
Nutzer schickt eine 3D-Datei (OBJ, GLB, STL, FBX, DAE …) an den Bot
und ruft dann /convert3d <format> auf – oder direkt beim Upload als Caption.

Unterstützte Formate:
    Input:  obj, glb, gltf, stl, fbx, dae, ply, 3ds, svg
    Output: glb, obj, stl, fbx, svg, png, mp4

Befehle:
    /convert3d glb          → letztes Upload → GLB
    /convert3d obj          → letztes Upload → OBJ
    /convert3d mp4          → letztes Upload → MP4 (Animation)
    /convert3d png          → Screenshot / Render
    /convert3d info         → Zeigt verfügbare Provider & Formate

Beim Datei-Upload mit Caption "to glb" oder "→ obj" wird direkt konvertiert.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from converter3d import (
    SUPPORTED_INPUT,
    SUPPORTED_OUTPUT,
    converter3d,
)

logger = logging.getLogger(__name__)

# In-Memory: letztes 3D-Upload pro Chat (file_id, filename, suffix)
_last_3d_upload: dict[str, tuple[str, str, str]] = {}

# ─────────────────────────────────────────────────────────────────────────────
# Hilfsfunktionen
# ─────────────────────────────────────────────────────────────────────────────

def _is_3d_document(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_INPUT


def _parse_target_from_caption(caption: str) -> str | None:
    """'to glb', '→ obj', 'convert to mp4' → 'glb' / 'obj' / 'mp4'"""
    cap = caption.lower().strip()
    for kw in ("to ", "→ ", "-> ", "nach ", "in ", "als "):
        idx = cap.find(kw)
        if idx != -1:
            rest = cap[idx + len(kw):].split()[0].strip(".")
            if f".{rest}" in SUPPORTED_OUTPUT:
                return rest
    return None


def _fmt_list(exts: set) -> str:
    return ", ".join(sorted(e.lstrip(".") for e in exts))


# ─────────────────────────────────────────────────────────────────────────────
# Handler: Dokument-Upload (3D-Datei speichern)
# ─────────────────────────────────────────────────────────────────────────────

async def handle_3d_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Wird aus handlers_media.py aufgerufen.
    Gibt True zurück, wenn die Datei eine 3D-Datei war (und verarbeitet wurde).
    """
    doc = update.message.document
    if not doc or not doc.file_name:
        return False

    filename = doc.file_name
    if not _is_3d_document(filename):
        return False

    chat_id = str(update.effective_chat.id)
    caption = (update.message.caption or "").strip()

    # 3D-Datei merken
    suffix = Path(filename).suffix.lower()
    _last_3d_upload[chat_id] = (doc.file_id, filename, suffix)

    # Caption enthält direkte Konvertierungsanweisung?
    target = _parse_target_from_caption(caption)
    if target:
        await _do_convert(update, context, chat_id, doc.file_id, filename, suffix, target)
    else:
        fmts = _fmt_list(SUPPORTED_OUTPUT)
        await update.message.reply_text(
            f"📦 3D-Datei erkannt: <b>{filename}</b>\n\n"
            f"Nutze /convert3d &lt;format&gt; zum Konvertieren.\n"
            f"Verfügbare Zielformate: <code>{fmts}</code>\n\n"
            f"Beispiel: <code>/convert3d glb</code>",
            parse_mode="HTML",
        )
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Handler: /convert3d Befehl
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_convert3d(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    args = context.args or []

    # Info-Modus
    if args and args[0].lower() == "info":
        await _send_info(update)
        return

    # Zielformat ermitteln
    if not args:
        await update.message.reply_text(
            "⚙️ <b>3D-Konverter</b>\n\n"
            "Nutzung: <code>/convert3d &lt;format&gt;</code>\n"
            "Beispiel: <code>/convert3d glb</code>\n\n"
            f"Input:  <code>{_fmt_list(SUPPORTED_INPUT)}</code>\n"
            f"Output: <code>{_fmt_list(SUPPORTED_OUTPUT)}</code>\n\n"
            "Lade zuerst eine 3D-Datei hoch, dann diesen Befehl senden.\n"
            "Oder: Datei mit Caption <code>to glb</code> hochladen.",
            parse_mode="HTML",
        )
        return

    target = args[0].lower().lstrip(".")
    if f".{target}" not in SUPPORTED_OUTPUT:
        await update.message.reply_text(
            f"❌ Format <code>{target}</code> nicht unterstützt.\n"
            f"Verfügbar: <code>{_fmt_list(SUPPORTED_OUTPUT)}</code>",
            parse_mode="HTML",
        )
        return

    # Letztes Upload holen
    if chat_id not in _last_3d_upload:
        await update.message.reply_text(
            "❌ Keine 3D-Datei im Speicher.\nLade zuerst eine OBJ/GLB/STL/… Datei hoch.",
        )
        return

    file_id, filename, suffix = _last_3d_upload[chat_id]

    # Gleiche Format-Konvertierung verhindern
    if suffix.lstrip(".") == target:
        await update.message.reply_text(
            f"ℹ️ Die Datei ist bereits im Format <code>{target}</code>.",
            parse_mode="HTML",
        )
        return

    await _do_convert(update, context, chat_id, file_id, filename, suffix, target)


# ─────────────────────────────────────────────────────────────────────────────
# Kern-Konvertierung
# ─────────────────────────────────────────────────────────────────────────────

async def _do_convert(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: str,
    file_id: str,
    filename: str,
    src_ext: str,
    target: str,
) -> None:
    src_fmt = src_ext.lstrip(".")
    status_msg = await update.message.reply_text(
        f"⏳ Konvertiere <b>{filename}</b>\n"
        f"<code>{src_fmt.upper()} → {target.upper()}</code>\n\n"
        f"🔄 Lade Provider …",
        parse_mode="HTML",
    )

    # Datei von Telegram downloaden
    try:
        tg_file = await context.bot.get_file(file_id)
        file_bytes = bytes(await tg_file.download_as_bytearray())
    except Exception as exc:
        logger.exception("handle_3d: Download fehlgeschlagen")
        await status_msg.edit_text(f"❌ Datei-Download fehlgeschlagen: {exc}")
        return

    # In temporäre Datei schreiben
    with tempfile.NamedTemporaryFile(suffix=src_ext, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        await status_msg.edit_text(
            f"⏳ Konvertiere <b>{filename}</b>\n"
            f"<code>{src_fmt.upper()} → {target.upper()}</code>\n\n"
            f"🔄 Starte Fallback-Kette …",
            parse_mode="HTML",
        )

        # Try providers with status updates
        status_providers = [
            ("Trimesh", converter3d._try_trimesh),
            ("Pyrender PNG", converter3d._try_pyrender),
            ("Assimp", converter3d._try_assimp),
            ("Blender", converter3d._try_blender),
            ("F3D", converter3d._try_f3d),
            ("Convertio", converter3d._try_convertio),
            ("ImageToStl", converter3d._try_imagetostl),
            ("O3DV", converter3d._try_o3dv_node),
        ]
        result_bytes = None
        dl_url = None
        provider = "none"
        for p_name, p_func in status_providers:
            try:
                await status_msg.edit_text(
                    f"⏳ Konvertiere <b>{filename}</b>\n"
                    f"<code>{src_fmt.upper()} → {target.upper()}</code>\n\n"
                    f"🔄 {p_name} ...",
                    parse_mode="HTML"
                )
                result_bytes, dl_url, provider = await p_func(tmp_path, target)
                if result_bytes:
                    break
            except Exception:
                pass

        if not result_bytes:
            provider = "all_failed"
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    # Ergebnis senden
    if result_bytes is None:
        await status_msg.edit_text(
            "❌ <b>Konvertierung fehlgeschlagen.</b>\n\n"
            "Alle 6 Provider haben es versucht – leider ohne Erfolg.\n"
            "Mögliche Ursachen:\n"
            "• Format-Kombination nicht unterstützt\n"
            "• Assimp/Blender/F3D nicht installiert\n"
            "• Cloud-API-Keys fehlen (<code>CONVERTIO_API_KEY</code>)\n"
            "• Datei beschädigt oder zu groß",
            parse_mode="HTML",
        )
        return

    stem = Path(filename).stem
    out_filename = f"{stem}.{target}"
    result_bytes.name = out_filename
    result_bytes.seek(0)

    caption = (
        f"✅ <b>Konvertierung abgeschlossen</b>\n"
        f"<code>{src_fmt.upper()} → {target.upper()}</code>\n"
        f"Provider: <b>{provider}</b>"
    )
    if dl_url:
        caption += f"\n🔗 <a href='{dl_url}'>Download-Link</a>"

    try:
        if target == "mp4":
            await context.bot.send_video(
                chat_id=chat_id,
                video=result_bytes,
                caption=caption,
                parse_mode="HTML",
                filename=out_filename,
            )
        elif target == "png":
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=result_bytes,
                caption=caption,
                parse_mode="HTML",
            )
        else:
            await context.bot.send_document(
                chat_id=chat_id,
                document=result_bytes,
                caption=caption,
                parse_mode="HTML",
                filename=out_filename,
            )
        await status_msg.delete()
    except Exception as exc:
        logger.exception("handle_3d: Senden fehlgeschlagen")
        await status_msg.edit_text(f"❌ Senden fehlgeschlagen: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Info-Ausgabe
# ─────────────────────────────────────────────────────────────────────────────

async def _send_info(update: Update) -> None:
    text = (
        "🔧 <b>3D-Konverter – Provider & Formate</b>\n\n"

        "<b>Fallback-Kette (6 Provider):</b>\n"
        "1️⃣ <b>Assimp</b> – Lokal, 40+ Formate, kein Key\n"
        "   <code>pip install pyassimp</code>\n\n"
        "2️⃣ <b>Blender</b> – Lokal headless, inkl. MP4-Render\n"
        "   <code>BLENDER_BIN=/usr/bin/blender</code>\n\n"
        "3️⃣ <b>F3D</b> – Lokal, Screenshot-Render (PNG)\n"
        "   <code>F3D_BIN=/usr/local/bin/f3d</code>\n\n"
        "4️⃣ <b>Convertio</b> – Cloud, 200+ Formate\n"
        "   <code>CONVERTIO_API_KEY=xxx</code>\n\n"
        "5️⃣ <b>imagetostl.com</b> – Cloud, kostenlos\n"
        "   Kein Key nötig (Rate-Limit: ~10/h)\n\n"
        "6️⃣ <b>Online3DViewer CLI</b> – Node.js lokal\n"
        "   <code>npm install -g o3dv</code>\n\n"

        f"<b>Input:</b>  <code>{_fmt_list(SUPPORTED_INPUT)}</code>\n"
        f"<b>Output:</b> <code>{_fmt_list(SUPPORTED_OUTPUT)}</code>\n\n"

        "<b>Umgebungsvariablen (alle optional):</b>\n"
        "<code>BLENDER_BIN</code>      – Blender-Pfad\n"
        "<code>F3D_BIN</code>          – F3D-Pfad\n"
        "<code>O3DV_BIN</code>         – o3dv-Pfad\n"
        "<code>CONVERTIO_API_KEY</code> – Convertio API-Key\n"
        "<code>C3D_HTTP_TIMEOUT</code>  – HTTP-Timeout in Sek. (default: 60)\n"
        "<code>C3D_MAX_MB</code>        – Max. Dateigröße in MB (default: 50)\n"
        "<code>C3D_PROC_TIMEOUT</code>  – Prozess-Timeout in Sek. (default: 120)\n"
    )
    await update.message.reply_text(text, parse_mode="HTML")
