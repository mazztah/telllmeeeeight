# 3d_svg_handler.py – SVG → animiertes 3D
import logging
from io import BytesIO
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

async def cmd_svg3d(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    
    # Prüfe auf SVG-Datei in Reply oder aktueller Nachricht
    doc = None
    if update.message.document and update.message.document.file_name.lower().endswith('.svg'):
        doc = update.message.document
    elif update.message.reply_to_message and update.message.reply_to_message.document:
        if update.message.reply_to_message.document.file_name.lower().endswith('.svg'):
            doc = update.message.reply_to_message.document
    
    if not doc:
        await update.message.reply_text(
            "🧊 **SVG → 3D Konverter**\n\n"
            "Schick mir eine SVG-Datei (oder antworte auf eine) und ich konvertiere sie zu einem 3D-Modell (GLB).\n\n"
            "Unterstützt: Extrusion von SVG-Pfaden zu 3D-Mesh."
        )
        return
    
    loading = await update.message.reply_text("🧊 Lade SVG und extrudiere zu 3D...")
    
    try:
        file = await context.bot.get_file(doc.file_id)
        svg_bytes = await file.download_as_bytearray()
        
        # Versuche mit trimesh
        try:
            import trimesh
            
            # Lade SVG als Path2D oder Scene
            mesh = trimesh.load(BytesIO(svg_bytes), file_type='svg')
            
            # Wenn es ein 2D-Path ist, extrudiere zu 3D
            if hasattr(mesh, 'extrude'):
                mesh_3d = mesh.extrude(5.0)  # Extrude um 5 Einheiten
                mesh = mesh_3d
            
            # Wenn es eine Szene ist, konvertiere zu einem Mesh
            if isinstance(mesh, trimesh.Scene):
                # Vereinfache zu einem Mesh
                meshes = []
                for name, geom in mesh.geometry.items():
                    meshes.append(geom)
                if meshes:
                    mesh = trimesh.util.concatenate(meshes)
            
            # Exportiere als GLB
            output = BytesIO()
            mesh.export(output, file_type='glb')
            output.seek(0)
            output.name = "svg_3d_converted.glb"
            
            await context.bot.send_document(
                chat_id=chat_id,
                document=output,
                filename="svg_3d_converted.glb",
                caption="✅ SVG zu 3D konvertiert!\n\n"
                        "🎨 Original: 2D Vektorgrafik\n"
                        "🧊 Extrusion: 5.0 Einheiten\n"
                        "📦 Format: GLB (GLTF Binary)"
            )
            await context.bot.delete_message(chat_id=chat_id, message_id=loading.message_id)
            
        except ImportError:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading.message_id,
                text="❌ **trimesh nicht installiert**\n\n"
                     "Installiere: `pip install trimesh[png]`\n"
                     "Für SVG-Support auch: `pip install svg.path`",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.exception("SVG Konvertierung Fehler")
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading.message_id,
                text=f"❌ Fehler bei Konvertierung:\n{str(e)[:200]}\n\n"
                     "Mögliche Ursachen: Komplexe SVGs mit nicht unterstützten Elementen."
            )
            
    except Exception as e:
        logger.exception("SVG 3D Handler Fehler")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=f"❌ Fehler: {str(e)[:200]}"
        )
