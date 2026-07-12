# chess_engine.py – Groq Edition v2
import re
import random
import os
from chess import Board
from groq import Groq

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "llama-3.3-70b-versatile"


async def get_llama_chess_move(fen: str) -> dict:
    board = Board(fen)
    legal_ucis = [m.uci() for m in board.legal_moves]

    if not legal_ucis:
        return {"thought": "Keine legalen Züge mehr.", "move": ""}

    prompt = (
        f"Du bist Queen Llama, eine kreative, leicht freche Schach-Großmeisterin.\n"
        f"Aktuelle FEN: {fen}\n"
        f"Legale Züge (UCI): {', '.join(legal_ucis[:30])}\n\n"
        f"Analysiere die Position (1 kurzer Satz), dann wähle den BESTEN Zug "
        f"AUS DER LISTE oben.\n"
        f"Antworte EXAKT in diesem Format – keine Extra-Zeilen:\n"
        f"THOUGHT: <deine Analyse>\n"
        f"MOVE: <ein Zug aus der Liste, z.B. e2e4>"
    )

    try:
        completion = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=200,
        )
        text = completion.choices[0].message.content

        thought = "Denke nach..."
        if "THOUGHT:" in text:
            thought = text.split("THOUGHT:")[1].split("MOVE:")[0].strip()

        move = ""
        if "MOVE:" in text:
            raw = text.split("MOVE:")[-1].strip()
            match = re.search(r"[a-h][1-8][a-h][1-8][qrbn]?", raw)
            if match:
                move = match.group(0)

        # Validierung – Zug muss legal sein
        if move not in legal_ucis:
            base = move[:4] if len(move) >= 4 else ""
            base_matches = [u for u in legal_ucis if u[:4] == base]
            if base_matches:
                move = base_matches[0]
            else:
                move = random.choice(legal_ucis)
                thought += " (Zug korrigiert → Zufallszug)"

        return {"thought": thought, "move": move}

    except Exception as e:
        return {
            "thought": f"Groq nicht erreichbar: {e} → Zufallszug",
            "move": random.choice(legal_ucis) if legal_ucis else "",
        }


async def get_llama_chat_reply(message: str, fen: str) -> str:
    """Dynamische Chat-Antwort von Queen Llama via Groq."""
    try:
        board = Board(fen)
        turn = "Weiß (Du)" if board.turn else "Schwarz (Llama)"
        prompt = (
            f"Du bist Queen Llama – eine freche, witzige Schach-Großmeisterin mit viel Persönlichkeit.\n"
            f"Aktuelle Spielposition (FEN): {fen}\n"
            f"Am Zug: {turn}\n"
            f"Der Spieler fragt/sagt: {message}\n\n"
            f"Antworte auf Deutsch, kurz (1-3 Sätze), witzig und im Charakter. "
            f"Beziehe dich auf die aktuelle Spielsituation wenn möglich."
        )
        completion = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=150,
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        return f"Ich bin kurz abgelenkt von dieser genialen Stellung... ({e})"