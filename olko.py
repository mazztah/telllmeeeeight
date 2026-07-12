import os
import json
import base64
import tempfile
from io import BytesIO
from typing import Dict, Any, Tuple, Optional
from anthropic import Anthropic

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY fehlt!")

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

client = Anthropic(api_key=ANTHROPIC_API_KEY)

async def generate_code(prompt: str, language: str = "python", max_tokens: int = 4000) -> Dict[str, Any]:
    """
    Generiert neuen Code mit Claude.
    Returns: {'success': bool, 'code': str, 'language': str, 'explanation': str}
    """
    user_content = (
        f"Erstelle sauberen, funktionalen {language}-Code.\n\n"
        f"PROMPT: {prompt}\n\n"
        f"Antworte IMMER nur mit JSON:\n"
        f'{{"code": "<vollständiger {language}-Code>", "explanation": "kurze Erklärung auf Deutsch"}}'
    )

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=max_tokens,
            system="Du generierst perfekten, fehlerfreien Code. JSON-only Output, kein Markdown.",
            messages=[{"role": "user", "content": user_content}]
        )
        content = response.content[0].text.strip()

        if '{' in content and '}' in content:
            json_str = content[content.find('{'):content.rfind('}')+1]
            result = json.loads(json_str)
            return {
                'success': True,
                'code': result.get('code', ''),
                'language': language,
                'explanation': result.get('explanation', 'Code generiert.')
            }
        return {'success': False, 'error': 'Kein gültiges JSON von Claude erhalten.'}
    except Exception as e:
        return {'success': False, 'error': str(e)}

async def edit_code(existing_code: str, instructions: str, language: str = "python") -> Dict[str, Any]:
    """Bearbeitet bestehenden Code mit Claude."""
    user_content = (
        f"Bestehender {language}-Code:\n```{language}\n{existing_code}\n```\n\n"
        f"ANWEISUNGEN: {instructions}\n\n"
        f"Generiere den vollständig aktualisierten Code als JSON:\n"
        f'{{"code": "<vollständiger neuer Code>", "changes": "Zusammenfassung der Änderungen"}}'
    )

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4000,
            system="Du bearbeitest Code präzise. JSON-only Output, kein Markdown.",
            messages=[{"role": "user", "content": user_content}]
        )
        content = response.content[0].text.strip()

        json_str = content[content.find('{'):content.rfind('}')+1]
        result = json.loads(json_str)
        return {
            'success': True,
            'code': result.get('code', existing_code),
            'language': language,
            'changes': result.get('changes', 'Code bearbeitet.')
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}

async def analyze_file(file_content: str, filename: str, language: str = None) -> Dict[str, Any]:
    """Analysiert Datei-Inhalt mit Claude."""
    detected_lang = language or filename.split('.')[-1] or 'text'

    user_content = (
        f"Analysiere diese Datei: {filename}\n\n"
        f"Inhalt:\n{file_content[:4000]}\n\n"
        "Beschreibe: 1. Zweck/Funktion  2. Struktur  3. Verbesserungsvorschläge  4. Fehler\n\n"
        'Antworte als JSON: {"summary": "...", "issues": ["..."], "suggestions": ["..."]}'
    )

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2000,
            system="Du analysierst Code und Dateien präzise. JSON-only Output.",
            messages=[{"role": "user", "content": user_content}]
        )
        content = response.content[0].text.strip()
        json_str = content[content.find('{'):content.rfind('}')+1]
        result = json.loads(json_str)
        return {'success': True, **result, 'language': detected_lang}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def create_download_buffer(code: str, language: str, stem: str = "generated") -> Tuple[BytesIO, str]:
    """Erstellt downloadbare Datei aus Code."""
    ext = {'python': 'py', 'html': 'html', 'js': 'js', 'css': 'css', 'json': 'json'}.get(language, 'txt')
    filename = f"{stem}.{ext}"
    content = code.encode('utf-8')
    buffer = BytesIO(content)
    buffer.seek(0)
    return buffer, filename

# Test-Function (für main.py Integration)
async def claude_code_handler(chat_id: str, user_input: str, existing_code: str = None) -> Dict[str, Any]:
    """
    Haupt-Handler für Chat-Integration.
    user_input: z.B. 'erstelle python script für webscraper' oder 'füge login hinzu'
    Returns structured result for Telegram.
    """
    if existing_code:
        return await edit_code(existing_code, user_input)
    return await generate_code(user_input)
