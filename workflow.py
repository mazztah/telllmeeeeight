import asyncio
import json
import logging
import os
import re
from io import BytesIO
from typing import Any

from social import build_social_pack

logger = logging.getLogger(__name__)

DEFAULT_WORKFLOW_MODELS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama3-70b-8192",
    "codex/gpt-5.2",
    "mixtral-8x7b-32768",
]


def _workflow_models() -> list[str]:
    raw = os.getenv("WORKFLOW_MODELS", "")
    if not raw.strip():
        return DEFAULT_WORKFLOW_MODELS
    models = [item.strip() for item in raw.split(",") if item.strip()]
    return models or DEFAULT_WORKFLOW_MODELS


def _extract_json_block(text: str) -> dict[str, Any] | None:
    raw_text = (text or "").strip()
    if not raw_text:
        return None

    fenced_match = re.search(r"```json\s*(\{.*?\})\s*```", raw_text, re.DOTALL | re.IGNORECASE)
    if fenced_match:
        raw_text = fenced_match.group(1)

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", raw_text):
        try:
            payload, _ = decoder.raw_decode(raw_text[match.start() :])
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _ensure_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [line.strip("- ").strip() for line in value.splitlines() if line.strip()]
    return []


def _build_fallback_bundle(request_text: str, raw_text: str) -> dict[str, Any]:
    preview = raw_text.strip() or request_text.strip()
    return {
        "title": request_text[:70] or "Workflow",
        "concept": preview[:500],
        "hook": request_text[:140],
        "script": preview[:1800],
        "caption": preview[:600],
        "hashtags": [],
        "shotlist": [
            "Opening Hook im ersten Shot platzieren",
            "Kernaussage in 2 bis 4 Szenen visualisieren",
            "Abschluss mit CTA und Branding",
        ],
        "image_prompt": request_text,
        "video_prompt": request_text,
        "checklist": [
            "Hook pruefen",
            "Script finalisieren",
            "Visuals rendern",
            "Caption freigeben",
        ],
    }


def _workflow_messages(history: list[dict[str, Any]], request_text: str) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": (
                "Du bist eine Workflow-Engine fuer Social-, Video- und Content-Pakete. "
                "Antworte strikt als JSON mit den Keys: title, concept, hook, script, caption, hashtags, "
                "shotlist, image_prompt, video_prompt, checklist. hashtags, shotlist und checklist muessen Arrays sein. "
                "Die Outputs sollen produktionsreif, konkret und kurz genug fuer direkte Umsetzung sein."
            ),
        },
        *(list(history[-8:]) if history else []),
        {"role": "user", "content": request_text},
    ]


async def _request_workflow_raw(client, messages: list[dict[str, Any]]) -> tuple[str, str | None]:
    last_error = None

    for model_name in _workflow_models():
        try:
            completion = await asyncio.to_thread(
                client.chat.completions.create,
                model=model_name,
                messages=messages,
                temperature=0.45,
                max_tokens=1600,
                top_p=0.95,
                stream=False,
                response_format={"type": "json_object"},
            )
            raw_text = completion.choices[0].message.content or ""
            if raw_text.strip():
                return raw_text, model_name
        except Exception as exc:
            last_error = exc
            logger.warning("Workflow-Modell %s fehlgeschlagen: %s", model_name, exc)

    if last_error:
        raise last_error
    return "", None


async def create_workflow_bundle(
    client,
    history: list[dict[str, Any]],
    request_text: str,
    model: str = "compound-mini",
) -> dict[str, Any]:
    messages = _workflow_messages(history, request_text)
    raw_text = ""
    parsed = None
    used_model = None

    custom_model = (model or "").strip()
    if custom_model and custom_model not in _workflow_models():
        try:
            completion = await asyncio.to_thread(
                client.chat.completions.create,
                model=custom_model,
                messages=messages,
                temperature=0.45,
                max_tokens=1600,
                top_p=0.95,
                stream=False,
                response_format={"type": "json_object"},
            )
            raw_text = completion.choices[0].message.content or ""
            used_model = custom_model
            parsed = _extract_json_block(raw_text)
        except Exception as exc:
            logger.warning("Workflow-Wunschmodell %s fehlgeschlagen: %s", custom_model, exc)

    if not parsed:
        raw_text, used_model = await _request_workflow_raw(client, messages)
        parsed = _extract_json_block(raw_text)

    if not parsed:
        logger.warning("Workflow-JSON konnte nicht geparst werden, nutze Fallback.")
        parsed = _build_fallback_bundle(request_text, raw_text)

    parsed["title"] = str(parsed.get("title") or request_text[:70] or "Workflow").strip()
    parsed["concept"] = str(parsed.get("concept") or "")[:1200]
    parsed["hook"] = str(parsed.get("hook") or request_text[:160]).strip()
    parsed["script"] = str(parsed.get("script") or raw_text or request_text)[:4000]
    parsed["caption"] = str(parsed.get("caption") or parsed["script"][:600]).strip()
    parsed["hashtags"] = _ensure_list(parsed.get("hashtags"))
    parsed["shotlist"] = _ensure_list(parsed.get("shotlist"))
    parsed["checklist"] = _ensure_list(parsed.get("checklist"))
    parsed["image_prompt"] = str(parsed.get("image_prompt") or request_text).strip()
    parsed["video_prompt"] = str(parsed.get("video_prompt") or parsed["image_prompt"]).strip()
    parsed["model_used"] = used_model
    parsed["social_pack"] = build_social_pack(
        title=parsed["title"],
        caption=parsed["caption"],
        script=parsed["script"],
        platforms=["instagram", "tiktok", "linkedin"],
        hook=parsed["hook"],
    )
    return parsed


def format_workflow_bundle(bundle: dict[str, Any]) -> str:
    hashtags = " ".join(bundle.get("hashtags", [])[:10]) or "keine"
    shotlist = bundle.get("shotlist", [])[:6]
    checklist = bundle.get("checklist", [])[:6]

    lines = [
        f"Workflow: {bundle.get('title', 'Unbenannt')}",
        "",
        f"Konzept: {bundle.get('concept', '')[:450]}",
        "",
        f"Hook: {bundle.get('hook', '')[:220]}",
        "",
        f"Caption: {bundle.get('caption', '')[:500]}",
        "",
        f"Hashtags: {hashtags}",
    ]

    if bundle.get("model_used"):
        lines.extend(["", f"Workflow-Modell: {bundle['model_used']}"])

    if shotlist:
        lines.append("")
        lines.append("Shotlist:")
        lines.extend(f"- {item}" for item in shotlist)

    if checklist:
        lines.append("")
        lines.append("Checklist:")
        lines.extend(f"- {item}" for item in checklist)

    return "\n".join(lines).strip()


def build_workflow_export(bundle: dict[str, Any]) -> BytesIO:
    payload = json.dumps(bundle, ensure_ascii=False, indent=2)
    buffer = BytesIO(payload.encode("utf-8"))
    buffer.name = f"{bundle.get('title', 'workflow').replace(' ', '_')[:40] or 'workflow'}.json"
    buffer.seek(0)
    return buffer
