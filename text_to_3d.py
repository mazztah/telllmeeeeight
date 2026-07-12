import asyncio
import logging
import os
from io import BytesIO
from typing import Any, Optional, Sequence

import httpx

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _extract_path(data: Any, path: str) -> Any:
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            if not part.isdigit():
                return None
            idx = int(part)
            if idx < 0 or idx >= len(cur):
                return None
            cur = cur[idx]
        else:
            return None
    return cur


def _first_string(data: Any, paths: Sequence[str]) -> Optional[str]:
    for path in paths:
        value = _extract_path(data, path)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_task_id(data: Any) -> Optional[str]:
    if not isinstance(data, dict):
        return None

    # Direkte Treffer
    for key in ["task_id", "id"]:
        if key in data:
            return str(data[key])

    # Unter "data"
    if "data" in data and isinstance(data["data"], dict):
        for key in ["task_id", "id"]:
            if key in data["data"]:
                return str(data["data"][key])

    return None


def _extract_status(data: Any) -> str:
    status = _first_string(data, ["status", "state", "data.status", "result.status"])
    return (status or "").upper()


def _extract_model_url(data: Any) -> Optional[str]:
    if not isinstance(data, dict):
        return None

    candidates = []

    # Neue Tripo v2 Struktur priorisieren
    output = _extract_path(data, "data.output")
    if isinstance(output, dict):
        for key in ["pbr_model", "model", "base_model"]:
            url = output.get(key)
            if isinstance(url, str) and url.startswith("http"):
                candidates.append(url)

    # Direkte Felder unter data
    data_dict = data.get("data") if isinstance(data.get("data"), dict) else data
    for key in ["model_url", "download_url", "url", "output_url", "pbr_model", "model", "base_model"]:
        url = data_dict.get(key)
        if isinstance(url, str) and url.startswith("http"):
            candidates.append(url)

    # Alte Strukturen als Fallback
    direct = _first_string(
        data,
        [
            "model_url", "download_url", "url", "output_url",
            "result.model_url", "result.download_url",
            "data.model_url", "data.download_url",
            "model.glb", "result.model.glb", "data.model.glb"
        ]
    )
    if direct and direct.startswith("http"):
        candidates.append(direct)

    # Erste gültige URL zurückgeben
    return candidates[0] if candidates else None


class TextTo3D:
    """Text-to-3D cascade: Tripo -> Meshy -> Luma -> TRELLIS -> Local fallback."""

    def __init__(self):
        self.default_timeout = float(os.getenv("TEXT3D_HTTP_TIMEOUT", "45"))
        self.max_poll_attempts = int(os.getenv("TEXT3D_MAX_POLL_ATTEMPTS", "60"))
        self.poll_delay_seconds = float(os.getenv("TEXT3D_POLL_DELAY_SECONDS", "3.0"))
        self.max_download_mb = int(os.getenv("TEXT3D_MAX_DOWNLOAD_MB", "45"))

    async def generate(self, prompt: str, chat_id: str | None = None):
        _ = chat_id  # reserved for future per-chat routing/limits
        prompt = (prompt or "").strip()
        if not prompt:
            return None, None, "invalid_prompt"

        providers = [
            self._try_tripo,
            self._try_meshy,
            self._try_luma,
            self._try_trellis,
        ]

        for provider in providers:
            try:
                result = await provider(prompt)
                if result:
                    return result
            except Exception as exc:
                logger.exception("%s failed: %s", provider.__name__, exc)

        return await self._try_local_fallback(prompt)

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        headers: Optional[dict[str, str]] = None,
        json_payload: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        response = await client.request(method, url, headers=headers, json=json_payload)
        if response.status_code >= 400:
            logger.warning("HTTP %s %s -> %s: %s", method, url, response.status_code, response.text[:250])
            return None
        try:
            data = response.json()
        except Exception:
            logger.warning("Non-JSON response from %s", url)
            return None
        return data if isinstance(data, dict) else None

    async def _poll_task(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        done_statuses: Optional[set[str]] = None,
        fail_statuses: Optional[set[str]] = None,
    ) -> Optional[dict[str, Any]]:
        done = done_statuses or {"SUCCEEDED", "SUCCESS", "COMPLETED", "DONE"}
        failed = fail_statuses or {"FAILED", "ERROR", "CANCELED", "CANCELLED"}

        for _ in range(self.max_poll_attempts):
            task = await self._request_json(client, "GET", url, headers=headers)
            if not task:
                await asyncio.sleep(self.poll_delay_seconds)
                continue

            model_url = _extract_model_url(task)
            status = _extract_status(task)

            if model_url and not status:
                return task
            if status in done:
                return task
            if status in failed:
                logger.warning("Task %s failed with status=%s", url, status)
                return None

            await asyncio.sleep(self.poll_delay_seconds)

        logger.warning("Polling timeout for %s", url)
        return None

    async def _download_model(self, client: httpx.AsyncClient, url: str) -> Optional[BytesIO]:
        max_bytes = self.max_download_mb * 1024 * 1024
        try:
            async with client.stream("GET", url, follow_redirects=True) as response:
                if response.status_code >= 400:
                    logger.warning("Model download failed %s -> %s", url, response.status_code)
                    return None

                content_len = response.headers.get("content-length")
                if content_len and content_len.isdigit() and int(content_len) > max_bytes:
                    logger.warning("Model too large (%s bytes > %s)", content_len, max_bytes)
                    return None

                buffer = BytesIO()
                async for chunk in response.aiter_bytes():
                    buffer.write(chunk)
                    if buffer.tell() > max_bytes:
                        logger.warning("Model exceeded max size while downloading: %s", url)
                        return None

                buffer.seek(0)
                return buffer
        except Exception as exc:
            logger.warning("Download exception for %s: %s", url, exc)
            return None

    async def _try_tripo(self, prompt: str):
        api_key = os.getenv("TRIPO_API_KEY")
        if not api_key:
            return None

        base_url = os.getenv("TRIPO_BASE_URL", "https://api.tripo3d.ai").rstrip("/")
        task_url = f"{base_url}/v2/openapi/task"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "type": "text_to_model",
            "prompt": prompt[:1000],
        }

        # Optionale Parameter
        model_version = os.getenv("TRIPO_MODEL_VERSION")
        if model_version:
            payload["model_version"] = model_version

        if _env_bool("TRIPO_ENABLE_TEXTURE", True):
            payload["texture"] = True

        timeout = float(os.getenv("TRIPO_HTTP_TIMEOUT", str(self.default_timeout)))

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            # Task erstellen
            created = await self._request_json(client, "POST", task_url, headers=headers, json_payload=payload)
            if not created:
                logger.warning("Tripo: Task konnte nicht erstellt werden")
                return None

            task_id = _extract_task_id(created)
            if not task_id:
                logger.warning("Tripo: Keine task_id in Antwort: %s", created)
                return None

            # Task pollen
            poll_url = f"{task_url}/{task_id}"
            task = await self._poll_task(client, poll_url, headers)
            if not task:
                return None

            model_url = _extract_model_url(task)
            if not model_url:
                logger.warning("Tripo: Keine model_url im fertigen Task")
                return None

            glb = await self._download_model(client, model_url)
            if glb:
                return glb, model_url, "Tripo AI (v2)"
            return None

    async def _try_meshy(self, prompt: str):
        api_key = os.getenv("MESHY_API_KEY")
        if not api_key:
            return None

        base_url = os.getenv("MESHY_BASE_URL", "https://api.meshy.ai").rstrip("/")
        endpoint = os.getenv("MESHY_TEXT3D_PATH", "/openapi/v2/text-to-3d")
        url = f"{base_url}{endpoint}"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        preview_payload: dict[str, Any] = {
            "mode": "preview",
            "prompt": prompt,
            "art_style": os.getenv("MESHY_ART_STYLE", "realistic"),
            "should_remesh": _env_bool("MESHY_SHOULD_REMESH", True),
            "moderation": _env_bool("MESHY_MODERATION", False),
        }
        model_name = os.getenv("MESHY_AI_MODEL")
        if model_name:
            preview_payload["ai_model"] = model_name

        timeout = float(os.getenv("MESHY_HTTP_TIMEOUT", str(self.default_timeout)))
        async with httpx.AsyncClient(timeout=timeout) as client:
            preview_create = await self._request_json(
                client,
                "POST",
                url,
                headers=headers,
                json_payload=preview_payload,
            )
            if not preview_create:
                return None

            preview_id = _extract_task_id(preview_create)
            if not preview_id:
                logger.warning("Meshy preview has no task id: %s", preview_create)
                return None

            preview_task = await self._poll_task(client, f"{url}/{preview_id}", headers)
            if not preview_task:
                return None

            refine_payload: dict[str, Any] = {
                "mode": "refine",
                "preview_task_id": preview_id,
                "enable_pbr": _env_bool("MESHY_ENABLE_PBR", False),
            }
            if model_name:
                refine_payload["ai_model"] = model_name

            texture_prompt = os.getenv("MESHY_TEXTURE_PROMPT")
            if texture_prompt:
                refine_payload["texture_prompt"] = texture_prompt

            refine_create = await self._request_json(
                client,
                "POST",
                url,
                headers=headers,
                json_payload=refine_payload,
            )
            if not refine_create:
                return None

            refine_id = _extract_task_id(refine_create)
            if not refine_id:
                logger.warning("Meshy refine has no task id: %s", refine_create)
                return None

            refine_task = await self._poll_task(client, f"{url}/{refine_id}", headers)
            if not refine_task:
                return None

            model_url = _extract_model_url(refine_task)
            if not model_url:
                logger.warning("Meshy task has no downloadable model url: %s", refine_task)
                return None

            glb = await self._download_model(client, model_url)
            return glb, model_url, "Meshy AI"

    async def _try_luma(self, prompt: str):
        api_key = os.getenv("LUMA_API_KEY")
        endpoint = os.getenv("LUMA_TEXT3D_ENDPOINT")
        if not api_key or not endpoint:
            return None

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {"prompt": prompt}
        async with httpx.AsyncClient(timeout=self.default_timeout) as client:
            data = await self._request_json(client, "POST", endpoint, headers=headers, json_payload=payload)
            if not data:
                return None

            model_url = _extract_model_url(data)
            if not model_url:
                task_id = _extract_task_id(data)
                task_endpoint_template = os.getenv("LUMA_TEXT3D_TASK_ENDPOINT", "")
                if task_id and task_endpoint_template:
                    task_url = task_endpoint_template.format(task_id=task_id)
                    task = await self._poll_task(client, task_url, headers)
                    if task:
                        model_url = _extract_model_url(task)

            if not model_url:
                return None

            glb = await self._download_model(client, model_url)
            return glb, model_url, "Luma AI"

    async def _try_trellis(self, prompt: str):
        endpoint = os.getenv("TRELLIS_API_ENDPOINT")
        if not endpoint:
            return None

        headers = {"Content-Type": "application/json"}
        hf_token = os.getenv("HF_TOKEN")
        if hf_token:
            headers["Authorization"] = f"Bearer {hf_token}"

        payload = {"prompt": prompt}
        async with httpx.AsyncClient(timeout=self.default_timeout) as client:
            data = await self._request_json(client, "POST", endpoint, headers=headers, json_payload=payload)
            if not data:
                return None

            model_url = _extract_model_url(data)
            if not model_url:
                return None

            glb = await self._download_model(client, model_url)
            return glb, model_url, "TRELLIS"

    async def _try_local_fallback(self, prompt: str):
        _ = prompt
        if _env_bool("ENABLE_LOCAL_3D", False):
            logger.info("ENABLE_LOCAL_3D=1 gesetzt, aber kein lokales leichtes Modell aktiviert.")
        return None, None, "local_fallback"


text_to_3d = TextTo3D()
