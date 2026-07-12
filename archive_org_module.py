# archive_org_module.py – Internet Archive API + LLM Agent Integration (Render-Optimized)
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Optional
from urllib.parse import quote, urlencode

import httpx

logger = logging.getLogger(__name__)

# ── S3 Credentials ───────────────────────────────────────────────────────────
IA_S3_ACCESS_KEY = os.getenv("IA_S3_ACCESS_KEY", "Uddir392rXlWctFp")
IA_S3_SECRET_KEY = os.getenv("IA_S3_SECRET_KEY", "gmjUkINhpffBvRGY")

# ── API Endpoints ────────────────────────────────────────────────────────────
IA_METADATA_URL = "https://archive.org/metadata/{}"
IA_SEARCH_URL = "https://archive.org/advancedsearch.php"
IA_S3_UPLOAD_URL = "https://s3.us.archive.org"
IA_DOWNLOAD_URL = "https://archive.org/download/{}"
IA_CATALOG_URL = "https://archive.org/catalog/{}"

# ── User-Agent für Archive.org Bot-Richtlinien ───────────────────────────────
BOT_VERSION = "1.0.0"
USER_AGENT = f"telllmeeedrei-archive/{BOT_VERSION} (telegram-bot; llama-4-scout; render-deployment)"


class ArchiveOrgClient:
    """S3-kompatibler Client für archive.org mit LLM-Agent-Integration."""

    def __init__(self, access_key: str = None, secret_key: str = None):
        self.access_key = access_key or IA_S3_ACCESS_KEY
        self.secret_key = secret_key or IA_S3_SECRET_KEY
        self.client = httpx.AsyncClient(
            timeout=60.0,
            headers={"User-Agent": USER_AGENT}
        )

    # ── S3 Auth Helpers ──────────────────────────────────────────────────────
    def _s3_signature(self, string_to_sign: str) -> str:
        """Erstellt HMAC-SHA1 S3 Signature."""
        return base64.b64encode(
            hmac.new(
                self.secret_key.encode('utf-8'),
                string_to_sign.encode('utf-8'),
                hashlib.sha1
            ).digest()
        ).decode('utf-8')

    def _s3_auth_headers(self, method: str, bucket: str, path: str = "",
                         content_type: str = "", content_md5: str = "") -> dict:
        """Generiert S3-kompatible Auth-Header."""
        date = datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')
        string_to_sign = f"{method}\n{content_md5}\n{content_type}\n{date}\n/{bucket}{path}"
        signature = self._s3_signature(string_to_sign)

        return {
            "Authorization": f"AWS {self.access_key}:{signature}",
            "Date": date,
            "Content-Type": content_type,
            "x-amz-auto-make-bucket": "1",
            "x-archive-meta-mediatype": "data",
        }

    # ── Search & Metadata ────────────────────────────────────────────────────
    async def search(self, query: str, page: int = 1, rows: int = 20,
                     fields: list = None, sort: str = None) -> dict:
        """
        Erweiterte Suche über archive.org.
        """
        params = {
            "q": query,
            "output": "json",
            "page": page,
            "rows": rows,
        }
        if fields:
            params["fl[]"] = fields
        if sort:
            params["sort[]"] = sort

        try:
            resp = await self.client.get(IA_SEARCH_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

            return {
                "success": True,
                "total": data.get("response", {}).get("numFound", 0),
                "page": page,
                "items": [
                    {
                        "identifier": doc.get("identifier"),
                        "title": doc.get("title", "Untitled"),
                        "creator": doc.get("creator", "Unknown"),
                        "date": doc.get("date", "Unknown"),
                        "mediatype": doc.get("mediatype", "data"),
                        "downloads": doc.get("downloads", 0),
                        "description": doc.get("description", "")[:300],
                    }
                    for doc in data.get("response", {}).get("docs", [])
                ]
            }
        except Exception as e:
            logger.error(f"Archive.org Search Fehler: {e}")
            return {"success": False, "error": str(e)}

    async def get_metadata(self, identifier: str) -> dict:
        """Holt detaillierte Metadaten für ein Item."""
        try:
            resp = await self.client.get(IA_METADATA_URL.format(identifier))
            resp.raise_for_status()
            data = resp.json()

            files = data.get("files", [])
            return {
                "success": True,
                "identifier": identifier,
                "title": data.get("metadata", {}).get("title", ["Untitled"])[0],
                "creator": data.get("metadata", {}).get("creator", ["Unknown"])[0],
                "description": data.get("metadata", {}).get("description", [""])[0],
                "date": data.get("metadata", {}).get("date", ["Unknown"])[0],
                "mediatype": data.get("metadata", {}).get("mediatype", ["data"])[0],
                "downloads": data.get("item", {}).get("downloads", 0),
                "files_count": len(files),
                "files": [
                    {
                        "name": f.get("name"),
                        "format": f.get("format"),
                        "size": f.get("size", 0),
                        "source": f.get("source", "original"),
                    }
                    for f in files[:20]
                ],
                "metadata_raw": data.get("metadata", {})
            }
        except Exception as e:
            logger.error(f"Metadata Fehler für {identifier}: {e}")
            return {"success": False, "error": str(e)}

    async def download_file(self, identifier: str, filename: str) -> Optional[bytes]:
        """Lädt eine spezifische Datei aus einem Item."""
        url = f"{IA_DOWNLOAD_URL.format(identifier)}/{quote(filename)}"
        try:
            resp = await self.client.get(url, follow_redirects=True, timeout=120.0)
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            logger.error(f"Download Fehler {identifier}/{filename}: {e}")
            return None

    # ── Upload ───────────────────────────────────────────────────────────────
    async def upload_file(self, identifier: str, file_bytes: bytes,
                          filename: str, metadata: dict = None) -> dict:
        """
        Upload via S3-kompatibler API.
        """
        bucket = identifier
        path = f"/{quote(filename)}"
        content_md5 = base64.b64encode(hashlib.md5(file_bytes).digest()).decode()
        content_type = metadata.get("format", "application/octet-stream") if metadata else "application/octet-stream"

        headers = self._s3_auth_headers(
            method="PUT",
            bucket=bucket,
            path=path,
            content_type=content_type,
            content_md5=content_md5
        )

        # Metadaten als x-archive-meta-* Header
        if metadata:
            for key, value in metadata.items():
                if isinstance(value, list):
                    for i, v in enumerate(value):
                        headers[f"x-archive-meta-{key}-{i}"] = str(v)
                else:
                    headers[f"x-archive-meta-{key}"] = str(value)

        headers["Content-MD5"] = content_md5

        try:
            url = f"{IA_S3_UPLOAD_URL}/{bucket}{path}"
            resp = await self.client.put(
                url,
                content=file_bytes,
                headers=headers,
                timeout=300.0
            )

            if resp.status_code in (200, 201):
                return {
                    "success": True,
                    "identifier": identifier,
                    "filename": filename,
                    "url": f"https://archive.org/details/{identifier}",
                    "size": len(file_bytes)
                }
            else:
                return {
                    "success": False,
                    "error": f"HTTP {resp.status_code}: {resp.text[:500]}"
                }
        except Exception as e:
            logger.error(f"Upload Fehler: {e}")
            return {"success": False, "error": str(e)}

    async def create_item(self, identifier: str, title: str,
                          mediatype: str = "data", metadata: dict = None) -> dict:
        """Erstellt ein neues Item (Bucket) auf archive.org."""
        meta = metadata or {}
        meta.update({
            "title": title,
            "mediatype": mediatype,
            "collection": "test_collection",
            "uploader": "telllmeeedrei-bot"
        })

        return await self.upload_file(
            identifier=identifier,
            file_bytes=b"",
            filename=".keep",
            metadata=meta
        )

    # ── LLM-Agent Tools ──────────────────────────────────────────────────────
    async def agent_search(self, query: str, context: str = "") -> str:
        """
        Für LLM-Agent: Sucht und formatiert Ergebnisse als Text.
        """
        result = await self.search(query, rows=10)
        if not result.get("success"):
            return f"Archive.org Suche fehlgeschlagen: {result.get('error')}"

        lines = [f"Archive.org Suchergebnisse für '{query}':", ""]
        for item in result["items"]:
            lines.append(f"📦 {item['title']}")
            lines.append(f"   ID: {item['identifier']}")
            lines.append(f"   Von: {item['creator']} | {item['date']}")
            lines.append(f"   Downloads: {item['downloads']}")
            lines.append(f"   Typ: {item['mediatype']}")
            if item['description']:
                lines.append(f"   Beschreibung: {item['description'][:200]}")
            lines.append("")

        lines.append(f"Gesamt: {result['total']} Ergebnisse")
        return "\n".join(lines)

    async def agent_get_details(self, identifier: str) -> str:
        """Für LLM-Agent: Holt Details als formatierten Text."""
        result = await self.get_metadata(identifier)
        if not result.get("success"):
            return f"Metadaten nicht gefunden: {result.get('error')}"

        lines = [
            f"📋 {result['title']}",
            f"ID: {result['identifier']}",
            f"Ersteller: {result['creator']}",
            f"Datum: {result['date']}",
            f"Typ: {result['mediatype']}",
            f"Downloads: {result['downloads']}",
            f"Dateien: {result['files_count']}",
            "",
            "Dateien:",
        ]
        for f in result["files"][:10]:
            size_mb = int(f['size']) / (1024*1024) if f['size'] else 0
            lines.append(f"  • {f['name']} ({f['format']}, {size_mb:.2f} MB)")

        return "\n".join(lines)

    async def close(self):
        await self.client.aclose()


# ── Singleton Client ─────────────────────────────────────────────────────────
_archive_client: Optional[ArchiveOrgClient] = None


def get_archive_client() -> ArchiveOrgClient:
    global _archive_client
    if _archive_client is None:
        _archive_client = ArchiveOrgClient()
    return _archive_client


# ── Agent Tool Wrapper ───────────────────────────────────────────────────────
async def archive_search_tool(arguments: dict) -> str:
    """Tool für den LLM-Agenten."""
    query = arguments.get("query", "")
    if not query:
        return "Leere Suchanfrage."
    client = get_archive_client()
    return await client.agent_search(query)


async def archive_get_details_tool(arguments: dict) -> str:
    """Tool für Item-Details."""
    identifier = arguments.get("identifier", "")
    if not identifier:
        return "Keine Item-ID angegeben."
    client = get_archive_client()
    return await client.agent_get_details(identifier)


def build_archive_agent_tools() -> list:
    """Erstellt Agent-Tools für Archive.org Integration."""
    try:
        from agent import AgentTool
    except ImportError:
        # Fallback wenn agent.py nicht verfügbar
        class AgentTool:
            def __init__(self, name, description, parameters, handler):
                self.name = name
                self.description = description
                self.parameters = parameters
                self.handler = handler

    return [
        AgentTool(
            name="archive_search",
            description="Sucht auf Archive.org nach Items, Büchern, Videos, Audio oder Software. Gibt Download-Links zurück.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Suchbegriff z.B. 'python programming 2024'"}
                },
                "required": ["query"]
            },
            handler=archive_search_tool,
        ),
        AgentTool(
            name="archive_get_details",
            description="Holt detaillierte Metadaten und alle verfügbaren Dateien für ein Archive.org Item. Ermöglicht Downloads.",
            parameters={
                "type": "object",
                "properties": {
                    "identifier": {"type": "string", "description": "Archive.org Item ID z.B. 'python_cookbook_2013'"}
                },
                "required": ["identifier"]
            },
            handler=archive_get_details_tool,
        ),
    ]
