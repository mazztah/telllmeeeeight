# rig3d_handler.py – GLB/OBJ → Auto-Rig + Animation
from telegram import Update
from telegram.ext import ContextTypes

async def cmd_rig3d(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text(
        "🦴 **GLB/OBJ → Auto-Rig + Animation**\n\n"
        "Schick mir eine 3D-Datei (.glb oder .obj).\n"
        "Mesh2Motion riggt sie automatisch und fügt Animationen hinzu.\n\n"
        "Verfügbare Animationen: Spin, Float, Walk, Dance, Idle usw."
    )

