# lightmeter_handler.py – Telegram Handler für Queen’s Light & Health Meter
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes

async def cmd_lightmeter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /lightmeter – Öffnet den professionellen Plant Light & Health Meter """
    chat_id = str(update.effective_chat.id)
    
    keyboard = [
        [
            InlineKeyboardButton(
                "🌿 Light & Health Meter öffnen",
                web_app=WebAppInfo(url="https://telllmeeesevn.onrender.com/lightmeter")
            )
        ],
        [
            InlineKeyboardButton("📖 Anleitung & Tipps", callback_data="lightmeter:help")
        ]
    ]

    await update.message.reply_text(
        "🌿 **Queen’s Light & Health Meter** aktiviert\n\n"
        "• Echtzeit PPFD, Lux, Chlorophyll, VPD, Leaf-Temp, Abstand & 8 weitere Werte\n"
        "• Multi-Leaf-Scan (6 Blätter) mit wissenschaftlichen Formeln\n"
        "• Vibrierende Werte + animierter Health-Border\n"
        "• Thinking-Terminal (Matrix-Style) + Voice-Feedback\n"
        "• Automatischer Brain-Sync\n\n"
        "Halte das Handy nah über die Blätter – die Queen misst live.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def lightmeter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Callback für den Hilfe-Button """
    query = update.callback_query
    await query.answer()

    if query.data == "lightmeter:help":
        await query.edit_message_text(
            "🔬 **Tipps für perfekte Messungen**\n\n"
            "• Halte das Handy ca. 5–15 cm über dem Blatt (Environment-Kamera)\n"
            "• Für Multi-Scan: 6 verschiedene Blätter auf unterschiedlichen Höhen scannen\n"
            "• Gute Beleuchtung = PPFD > 650 + Vigor > 65 → grüner Rand\n"
            "• Schlechte Werte = roter Rand + Queen gibt direkte Tipps\n\n"
            "Der Bot speichert alles automatisch ins Brain.",
            parse_mode="Markdown"
        )
