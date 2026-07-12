# brainlist_handler_fixed.py - Brain DB UI with Checkboxes/Delete
import json
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from brain import load_all_entries, delete_entry
from bot_state import selected_brain_deletes


def _get_message_and_chat_id(update):
    message = getattr(update, "message", None) or update
    chat = getattr(update, "effective_chat", None) or getattr(message, "chat", None)
    if chat is None:
        raise RuntimeError("Chat-Kontext fehlt")
    return message, str(chat.id)


def _entry_preview(entry: dict) -> str:
    metadata = entry.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}
    preview = (metadata.get("extracted_preview") or entry.get("content") or "")
    return str(preview).replace("\n", " ").strip()[:60]


async def cmd_brainlist(update, context):
    """
    /brainlist - Listet Brain-Eintraege mit Checkboxen zum Loeschen.
    """
    message, chat_id = _get_message_and_chat_id(update)
    query = " ".join(getattr(context, "args", []) or []).strip().lower()

    entries = await load_all_entries(chat_id)
    if query:
        def match(entry: dict) -> bool:
            title = str(entry.get("title") or "").lower()
            preview = _entry_preview(entry).lower()
            return query in title or query in preview
        entries = [entry for entry in entries if match(entry)]

    entries = entries[:20]
    keyboard = []
    selected_brain_deletes.setdefault(chat_id, [])

    for entry in entries:
        entry_id = str(entry.get("id", ""))
        title = str(entry.get("title") or "ohne Titel")[:40]
        preview = _entry_preview(entry)
        checked = "[x]" if entry_id in selected_brain_deletes[chat_id] else "[ ]"
        keyboard.append([
            InlineKeyboardButton(
                f"{checked} {title} | {preview}",
                callback_data=f"brain:{entry_id}",
            )
        ])

    keyboard.append([InlineKeyboardButton("Delete Selected", callback_data="brain:delete")])
    keyboard.append([InlineKeyboardButton("Clear Selection", callback_data="brain:clear")])

    await message.reply_text(
        f"Brain ({len(entries)} entries)\nSelect for delete:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def brain_callback(update, context):
    query = update.callback_query
    if not query or not query.data:
        return

    chat_id = str(query.message.chat.id)
    data = query.data
    selected_brain_deletes.setdefault(chat_id, [])

    if data.startswith("brain:") and data not in {"brain:delete", "brain:clear"}:
        entry_id = data[6:]
        if entry_id in selected_brain_deletes[chat_id]:
            selected_brain_deletes[chat_id].remove(entry_id)
        else:
            selected_brain_deletes[chat_id].append(entry_id)

        await query.answer("Selection updated")
        await cmd_brainlist(query.message, context)
        return

    if data == "brain:delete":
        deleted = 0
        for entry_id in selected_brain_deletes.get(chat_id, []):
            result = await delete_entry(chat_id, entry_id)
            low = result.lower()
            if "erfolgreich" in low or "deleted" in low:
                deleted += 1
        selected_brain_deletes[chat_id] = []
        await query.edit_message_text(f"Deleted {deleted} entries")
        return

    if data == "brain:clear":
        selected_brain_deletes[chat_id] = []
        await query.edit_message_text("Selection cleared")
