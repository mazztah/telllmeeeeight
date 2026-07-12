import asyncio
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

app = FastAPI(title="Scanner Mini App")

GTIN_LENGTHS = {8, 12, 13, 14}
LOOKUP_TIMEOUT_SECONDS = float(os.getenv("SCANNER_LOOKUP_TIMEOUT_SECONDS", "6.0"))
LOOKUP_USER_AGENT = os.getenv(
    "SCANNER_USER_AGENT",
    "telllmeeesevn-scanner/1.0 (+https://telllmeeesevn.onrender.com/)"
)


@dataclass(frozen=True)
class OpenFactsSource:
    label: str
    domain: str


OPEN_FACTS_SOURCES = [
    OpenFactsSource("Open Food Facts", "world.openfoodfacts.org"),
    OpenFactsSource("Open Beauty Facts", "world.openbeautyfacts.org"),
    OpenFactsSource("Open Pet Food Facts", "world.openpetfoodfacts.org"),
    OpenFactsSource("Open Products Facts", "world.openproductsfacts.org"),
]

OPEN_FACTS_FIELDS = ",".join(
    [
        "code",
        "product_name",
        "product_name_de",
        "generic_name",
        "generic_name_de",
        "brands",
        "brands_tags",
        "quantity",
        "categories",
        "categories_tags",
        "stores",
        "stores_tags",
        "countries",
        "countries_tags",
        "labels",
        "labels_tags",
        "nutriscore_grade",
        "image_url",
        "image_front_url",
        "ingredients_text",
        "ingredients_text_de",
    ]
)


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
        elif isinstance(value, list):
            joined = ", ".join(str(item).strip() for item in value if str(item).strip())
            if joined:
                return joined
    return ""


def _clean_tag_list(value: Any, max_items: int = 6) -> list[str]:
    if not value:
        return []

    if isinstance(value, str):
        parts = re.split(r"[;,]", value)
    elif isinstance(value, list):
        parts = [str(item) for item in value]
    else:
        parts = [str(value)]

    cleaned: list[str] = []
    for part in parts:
        item = part.strip()
        if not item:
            continue
        item = re.sub(r"^[a-z]{2}:", "", item, flags=re.IGNORECASE)
        item = item.replace("_", " ").strip()
        if item and item not in cleaned:
            cleaned.append(item)
        if len(cleaned) >= max_items:
            break
    return cleaned


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value)


def _gtin_check_digit(number_without_check: str) -> int:
    total = 0
    for index, char in enumerate(reversed(number_without_check), start=1):
        digit = int(char)
        weight = 3 if index % 2 == 1 else 1
        total += digit * weight
    return (10 - (total % 10)) % 10


def _is_valid_gtin(code: str) -> bool:
    if not code.isdigit() or len(code) not in GTIN_LENGTHS:
        return False
    return int(code[-1]) == _gtin_check_digit(code[:-1])


def _classify_scan(value: str, format_hint: str) -> dict[str, Any]:
    raw_value = (value or "").strip()
    format_normalized = (format_hint or "unknown").strip().lower() or "unknown"
    digits = _digits_only(raw_value)

    if raw_value.lower().startswith(("http://", "https://")):
        return {"kind": "qr_url", "code": None, "normalized": raw_value, "format": format_normalized}

    if raw_value.upper().startswith("WIFI:"):
        return {"kind": "qr_wifi", "code": None, "normalized": raw_value, "format": format_normalized}

    if raw_value.upper().startswith("BEGIN:VCARD"):
        return {"kind": "qr_vcard", "code": None, "normalized": raw_value, "format": format_normalized}

    if len(digits) in GTIN_LENGTHS:
        if _is_valid_gtin(digits):
            return {"kind": "gtin", "code": digits, "normalized": digits, "format": format_normalized}
        return {"kind": "gtin_candidate", "code": digits, "normalized": digits, "format": format_normalized}

    if format_normalized == "qr_code":
        return {"kind": "qr_text", "code": None, "normalized": raw_value, "format": format_normalized}

    if digits and len(digits) >= 5:
        return {"kind": "numeric_text", "code": digits, "normalized": digits, "format": format_normalized}

    return {"kind": "text", "code": None, "normalized": raw_value, "format": format_normalized}


def _search_links(code: str) -> list[dict[str, str]]:
    return [
        {
            "label": "Google Produktsuche",
            "url": f"https://www.google.com/search?q={code}+EAN+Produkt",
        },
        {
            "label": "Idealo Suche",
            "url": f"https://www.idealo.de/preisvergleich/MainSearchProductCategory.html?q={code}",
        },
        {
            "label": "EAN bei Codecheck",
            "url": f"https://www.codecheck.info/product.search?q={code}",
        },
    ]


def _qr_payload(raw_value: str) -> dict[str, Any]:
    value = (raw_value or "").strip()
    upper_value = value.upper()

    if value.lower().startswith(("http://", "https://")):
        return {"type": "url", "url": value}
    if upper_value.startswith("WIFI:"):
        return {"type": "wifi", "raw": value}
    if upper_value.startswith("BEGIN:VCARD"):
        preview = "\n".join(value.splitlines()[:8])[:280]
        return {"type": "vcard", "preview": preview}
    if upper_value.startswith("MATMSG:"):
        return {"type": "email", "raw": value}
    return {"type": "text", "text": value[:400]}


def _build_product_payload(source: OpenFactsSource, code: str, product: dict[str, Any]) -> dict[str, Any]:
    name = _first_non_empty(
        product.get("product_name_de"),
        product.get("product_name"),
        product.get("generic_name_de"),
        product.get("generic_name"),
    )
    brand = _first_non_empty(product.get("brands"), product.get("brands_tags"))
    quantity = _first_non_empty(product.get("quantity"))
    categories = _clean_tag_list(product.get("categories"), max_items=8) or _clean_tag_list(
        product.get("categories_tags"), max_items=8
    )
    stores = _clean_tag_list(product.get("stores"), max_items=6) or _clean_tag_list(
        product.get("stores_tags"), max_items=6
    )
    countries = _clean_tag_list(product.get("countries"), max_items=6) or _clean_tag_list(
        product.get("countries_tags"), max_items=6
    )
    labels = _clean_tag_list(product.get("labels"), max_items=6) or _clean_tag_list(
        product.get("labels_tags"), max_items=6
    )
    image_url = _first_non_empty(product.get("image_front_url"), product.get("image_url"))
    ingredients = _first_non_empty(product.get("ingredients_text_de"), product.get("ingredients_text"))
    nutriscore = _first_non_empty(product.get("nutriscore_grade")).upper()

    return {
        "code": code,
        "name": name or "Unbekanntes Produkt",
        "brand": brand,
        "quantity": quantity,
        "categories": categories,
        "stores": stores,
        "countries": countries,
        "labels": labels,
        "nutriscore": nutriscore,
        "ingredients": ingredients,
        "image_url": image_url,
        "source": source.label,
        "product_page_url": f"https://{source.domain}/product/{code}",
    }


async def _lookup_open_facts_source(
    client: httpx.AsyncClient, source: OpenFactsSource, code: str
) -> dict[str, Any]:
    errors: list[str] = []
    headers = {"User-Agent": LOOKUP_USER_AGENT, "Accept": "application/json"}

    endpoints = [
        f"https://{source.domain}/api/v2/product/{code}.json?lc=de&fields={OPEN_FACTS_FIELDS}",
        f"https://{source.domain}/api/v0/product/{code}.json",
    ]

    for endpoint in endpoints:
        try:
            response = await client.get(endpoint, headers=headers)
        except httpx.HTTPError as exc:
            errors.append(f"{source.label}: Netzwerkfehler ({exc.__class__.__name__})")
            continue

        if response.status_code == 404:
            continue
        if response.status_code >= 400:
            errors.append(f"{source.label}: HTTP {response.status_code}")
            continue

        try:
            payload = response.json()
        except ValueError:
            errors.append(f"{source.label}: Antwort war kein gueltiges JSON")
            continue

        product = payload.get("product") or {}
        if payload.get("status") == 1 and product:
            return {
                "found": True,
                "source": source.label,
                "product": _build_product_payload(source, code, product),
                "errors": errors,
            }

    return {"found": False, "source": source.label, "errors": errors}


async def _lookup_gtin(code: str) -> dict[str, Any]:
    timeout = httpx.Timeout(LOOKUP_TIMEOUT_SECONDS)
    provider_errors: list[str] = []

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        tasks = [
            _lookup_open_facts_source(client=client, source=source, code=code)
            for source in OPEN_FACTS_SOURCES
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    for index, result in enumerate(results):
        source_label = OPEN_FACTS_SOURCES[index].label
        if isinstance(result, Exception):
            provider_errors.append(f"{source_label}: {result.__class__.__name__}")
            continue
        provider_errors.extend(result.get("errors", []))
        if result.get("found"):
            return {
                "found": True,
                "message": "Produktdaten gefunden.",
                "product": result["product"],
                "provider_errors": provider_errors,
                "search_links": _search_links(code),
            }

    return {
        "found": False,
        "message": (
            "Kein Produkt in den angebundenen offenen Datenbanken gefunden. "
            "Bei manchen Produkten fehlen oeffentliche EAN-Daten."
        ),
        "provider_errors": provider_errors,
        "search_links": _search_links(code),
    }


@app.get("/", response_class=HTMLResponse)
async def scanner_home() -> HTMLResponse:
    return HTMLResponse(HTML_CONTENT)


@app.get("/api/lookup")
async def lookup_scan_value(
    value: str = Query(..., min_length=1, max_length=1024),
    format: str = Query("unknown", max_length=80),
) -> dict[str, Any]:
    raw_value = (value or "").strip()
    if not raw_value:
        raise HTTPException(status_code=400, detail="Leerer Scan-Wert")

    classification = _classify_scan(raw_value, format)
    response: dict[str, Any] = {
        "ok": True,
        "input": {"raw_value": raw_value, "format_hint": format},
        "classification": classification,
    }

    kind = classification["kind"]
    if kind in {"gtin", "gtin_candidate"}:
        code = classification.get("code") or raw_value
        response["lookup"] = await _lookup_gtin(code)
        return response

    if kind.startswith("qr_"):
        response["lookup"] = {
            "found": False,
            "message": (
                "QR-Inhalt erkannt. Falls das ein Produkt ist, fuehrt der QR-Code oft auf "
                "eine Website statt auf die EAN. Unten siehst du den entschluesselten Inhalt."
            ),
            "qr_payload": _qr_payload(raw_value),
        }
        return response

    response["lookup"] = {
        "found": False,
        "message": (
            "Code erkannt, aber keine eindeutige EAN/GTIN (8/12/13/14-stellig). "
            "Du kannst den Wert trotzdem manuell pruefen."
        ),
        "qr_payload": _qr_payload(raw_value),
        "search_links": _search_links(classification.get("code") or raw_value)
        if (classification.get("code") or raw_value)
        else [],
    }
    return response


HTML_CONTENT = """<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Scanner Modul</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@400;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #0d0014;
      --surface: rgba(22, 0, 32, 0.84);
      --card: rgba(30, 0, 46, 0.88);
      --border: rgba(128, 43, 177, 0.42);
      --accent-1: #cc44ff;
      --accent-2: #ff44cc;
      --accent-3: #44ffcc;
      --text: #f0d6ff;
      --muted: #b992d6;
      --ok: #67e8a0;
      --warn: #ffb36b;
      --danger: #ff6f9f;
      --shadow: 0 22px 50px rgba(5, 0, 10, 0.55);
      --mono: "Space Mono", "Courier New", monospace;
      --sans: "Syne", "Segoe UI", sans-serif;
    }
    * {
      box-sizing: border-box;
    }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: var(--sans);
      color: var(--text);
      background: radial-gradient(circle at 20% 12%, #2f0249 0%, transparent 42%),
        radial-gradient(circle at 88% 8%, #3e0438 0%, transparent 44%),
        linear-gradient(160deg, #0d0014 0%, #110019 38%, #090011 100%);
      padding: 22px;
      position: relative;
      overflow-x: hidden;
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      background-image:
        repeating-linear-gradient(0deg, transparent, transparent 35px, rgba(204, 68, 255, 0.035) 35px, rgba(204, 68, 255, 0.035) 36px),
        repeating-linear-gradient(90deg, transparent, transparent 35px, rgba(204, 68, 255, 0.035) 35px, rgba(204, 68, 255, 0.035) 36px);
      pointer-events: none;
      z-index: 0;
    }
    .orb {
      position: fixed;
      border-radius: 999px;
      filter: blur(110px);
      pointer-events: none;
      opacity: 0.38;
      z-index: 0;
      animation: drift 18s ease-in-out infinite;
    }
    .orb-a {
      width: 450px;
      height: 450px;
      background: #6e00cc;
      top: -180px;
      right: -120px;
    }
    .orb-b {
      width: 390px;
      height: 390px;
      background: #cc0079;
      bottom: -120px;
      left: -100px;
      animation-duration: 22s;
      animation-direction: reverse;
    }
    .orb-c {
      width: 280px;
      height: 280px;
      background: #00cca0;
      top: 55%;
      right: 7%;
      animation-duration: 15s;
    }
    @keyframes drift {
      0%, 100% {
        transform: translate(0, 0) scale(1);
      }
      50% {
        transform: translate(32px, -22px) scale(1.07);
      }
    }
    .layout {
      max-width: 1080px;
      margin: 0 auto;
      display: grid;
      gap: 16px;
      grid-template-columns: 1.2fr 1fr;
      align-items: start;
      position: relative;
      z-index: 1;
    }
    .panel {
      border: 1px solid var(--border);
      border-radius: 24px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
      background: linear-gradient(160deg, var(--surface), var(--card));
      overflow: hidden;
    }
    .hero {
      grid-column: 1 / -1;
      padding: 18px 20px;
    }
    h1 {
      margin: 0 0 6px;
      font-size: clamp(1.35rem, 2.8vw, 2rem);
      letter-spacing: 0.02em;
      font-weight: 800;
      background: linear-gradient(120deg, #ffffff 0%, var(--accent-1) 46%, var(--accent-2) 75%, var(--accent-3) 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
    }
    .subtitle {
      margin: 0;
      color: var(--muted);
      font-size: 0.97rem;
    }
    .camera-panel, .result-panel {
      padding: 16px;
    }
    .video-wrap {
      position: relative;
      border-radius: 18px;
      overflow: hidden;
      border: 1px solid var(--border);
      aspect-ratio: 4 / 3;
      background: #06000d;
    }
    video {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .scan-target {
      position: absolute;
      left: 12%;
      right: 12%;
      top: 24%;
      bottom: 24%;
      border-radius: 14px;
      border: 3px solid rgba(204, 68, 255, 0.94);
      box-shadow: 0 0 18px rgba(204, 68, 255, 0.75), 0 0 0 120vmax rgba(0, 0, 0, 0.24);
      animation: pulse-target 2.1s ease-in-out infinite;
      pointer-events: none;
    }
    @keyframes pulse-target {
      0%, 100% {
        transform: scale(1);
      }
      50% {
        transform: scale(1.02);
      }
    }
    .video-wrap::after {
      content: "";
      position: absolute;
      top: 10px;
      left: 10px;
      width: 12px;
      height: 12px;
      border-radius: 999px;
      background: var(--accent-3);
      box-shadow: 0 0 10px rgba(68, 255, 204, 0.9);
      pointer-events: none;
    }
    .controls {
      margin-top: 12px;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }
    button {
      border: 1px solid transparent;
      border-radius: 12px;
      padding: 10px 14px;
      font-size: 0.95rem;
      font-weight: 700;
      font-family: var(--mono);
      cursor: pointer;
      transition: transform 120ms ease, opacity 120ms ease, box-shadow 120ms ease;
    }
    button:hover {
      transform: translateY(-1px);
    }
    button:active {
      transform: translateY(0);
    }
    button:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }
    .btn-start {
      background: linear-gradient(135deg, var(--accent-1), var(--accent-2));
      color: #fff;
      box-shadow: 0 8px 20px rgba(204, 68, 255, 0.35);
    }
    .btn-stop {
      background: rgba(13, 0, 22, 0.88);
      color: #ddc4ef;
      border-color: rgba(255, 255, 255, 0.16);
    }
    .manual-form {
      margin-top: 12px;
      display: flex;
      gap: 8px;
    }
    input {
      flex: 1;
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 10px 12px;
      font-size: 0.95rem;
      font-family: var(--mono);
      background: rgba(10, 0, 17, 0.88);
      color: #f3e3ff;
    }
    input::placeholder {
      color: #ae89c8;
    }
    input:focus {
      outline: none;
      border-color: rgba(204, 68, 255, 0.82);
      box-shadow: 0 0 0 3px rgba(204, 68, 255, 0.15);
    }
    .status {
      margin-top: 10px;
      border-radius: 12px;
      border: 1px solid var(--border);
      padding: 10px;
      font-size: 0.94rem;
      background: rgba(9, 0, 15, 0.82);
      color: var(--muted);
    }
    .status.ok {
      border-color: rgba(103, 232, 160, 0.4);
      color: var(--ok);
    }
    .status.warn {
      border-color: rgba(255, 179, 107, 0.35);
      color: var(--warn);
    }
    .result-headline {
      margin: 0 0 10px;
      font-size: 1.08rem;
      color: #ffe8ff;
      font-weight: 800;
    }
    .kv-list {
      display: grid;
      gap: 8px;
    }
    .kv {
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 9px 10px;
      background: rgba(13, 0, 22, 0.85);
    }
    .kv b {
      display: block;
      color: #cf8cff;
      font-size: 0.78rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      margin-bottom: 4px;
      font-family: var(--mono);
    }
    .kv span {
      color: #f2deff;
      line-height: 1.35;
      word-break: break-word;
    }
    .product-image {
      width: 100%;
      max-height: 250px;
      object-fit: contain;
      border-radius: 12px;
      border: 1px solid var(--border);
      background: rgba(6, 0, 10, 0.78);
      margin-bottom: 10px;
      display: none;
    }
    .search-links {
      margin-top: 10px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .search-links a {
      border: 1px solid var(--border);
      background: rgba(17, 0, 26, 0.88);
      text-decoration: none;
      color: #f0dcff;
      border-radius: 10px;
      padding: 8px 10px;
      font-weight: 700;
      font-size: 0.84rem;
      font-family: var(--mono);
      transition: transform 120ms ease, border-color 120ms ease;
    }
    .search-links a:hover {
      transform: translateY(-1px);
      border-color: rgba(204, 68, 255, 0.9);
    }
    .last-code {
      margin-top: 10px;
      font-family: var(--mono);
      font-size: 0.86rem;
      color: #d6b8eb;
      background: rgba(8, 0, 14, 0.84);
      border: 1px dashed var(--border);
      border-radius: 10px;
      padding: 8px 9px;
      word-break: break-all;
    }
    @media (max-width: 900px) {
      body {
        padding: 14px;
      }
      .layout {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <div class="orb orb-a"></div>
  <div class="orb orb-b"></div>
  <div class="orb orb-c"></div>
  <main class="layout">
    <section class="panel hero">
      <h1>Scanner fuer QR, EAN und Barcode</h1>
      <p class="subtitle">
        Live-Scan per Kamera + Produktabfrage ueber offene Waren-Datenbanken
        (Deutschland-freundlich). Wenn keine Daten vorhanden sind, bekommst du direkte Suchlinks.
      </p>
    </section>

    <section class="panel camera-panel">
      <div class="video-wrap">
        <video id="video" playsinline autoplay muted></video>
        <div class="scan-target"></div>
      </div>
      <div class="controls">
        <button id="startBtn" class="btn-start">Scanner starten</button>
        <button id="stopBtn" class="btn-stop" disabled>Stoppen</button>
      </div>
      <form id="manualForm" class="manual-form">
        <input id="manualInput" type="text" placeholder="EAN/Barcode manuell eingeben">
        <button type="submit" class="btn-start">Suchen</button>
      </form>
      <div id="statusBox" class="status">Bereit. Starte die Kamera oder gib einen Code ein.</div>
      <div id="lastCode" class="last-code">Letzter Scan: -</div>
    </section>

    <section class="panel result-panel">
      <h2 id="resultTitle" class="result-headline">Noch kein Treffer</h2>
      <img id="productImage" class="product-image" alt="Produktbild">
      <div id="resultRows" class="kv-list"></div>
      <div id="searchLinks" class="search-links"></div>
    </section>
  </main>

  <script>
    const SUPPORTED_FORMATS = [
      "qr_code",
      "ean_13",
      "ean_8",
      "upc_a",
      "upc_e",
      "code_128",
      "code_39",
      "codabar",
      "itf",
      "data_matrix",
      "aztec",
      "pdf417"
    ];

    const state = {
      stream: null,
      detector: null,
      running: false,
      lastValue: "",
      lastAt: 0,
      apiBase: ""
    };

    const videoEl = document.getElementById("video");
    const startBtn = document.getElementById("startBtn");
    const stopBtn = document.getElementById("stopBtn");
    const manualForm = document.getElementById("manualForm");
    const manualInput = document.getElementById("manualInput");
    const statusBox = document.getElementById("statusBox");
    const resultTitle = document.getElementById("resultTitle");
    const resultRows = document.getElementById("resultRows");
    const searchLinks = document.getElementById("searchLinks");
    const productImage = document.getElementById("productImage");
    const lastCode = document.getElementById("lastCode");

    function computeApiBase() {
      const firstSegment = (window.location.pathname.split("/").filter(Boolean)[0] || "scanner").trim();
      return `${window.location.origin}/${firstSegment}/api`;
    }

    function setStatus(message, tone = "neutral") {
      statusBox.textContent = message;
      statusBox.classList.remove("ok", "warn");
      if (tone === "ok") statusBox.classList.add("ok");
      if (tone === "warn") statusBox.classList.add("warn");
    }

    function setButtons(running) {
      startBtn.disabled = running;
      stopBtn.disabled = !running;
    }

    function clearResult() {
      resultRows.innerHTML = "";
      searchLinks.innerHTML = "";
      productImage.style.display = "none";
      productImage.removeAttribute("src");
    }

    function addRow(label, value) {
      if (!value) return;
      const row = document.createElement("div");
      row.className = "kv";

      const key = document.createElement("b");
      key.textContent = label;
      row.appendChild(key);

      const val = document.createElement("span");
      val.textContent = value;
      row.appendChild(val);

      resultRows.appendChild(row);
    }

    function addLinks(links) {
      searchLinks.innerHTML = "";
      if (!Array.isArray(links)) return;
      for (const linkItem of links) {
        if (!linkItem || !linkItem.url) continue;
        const a = document.createElement("a");
        a.href = linkItem.url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.textContent = linkItem.label || "Suche";
        searchLinks.appendChild(a);
      }
    }

    async function ensureDetector() {
      if (!("BarcodeDetector" in window)) return null;
      if (state.detector) return state.detector;

      let formats = SUPPORTED_FORMATS.slice();
      try {
        const supported = await BarcodeDetector.getSupportedFormats();
        formats = SUPPORTED_FORMATS.filter((f) => supported.includes(f));
      } catch (_) {
        // ignore and try with defaults
      }

      state.detector = formats.length ? new BarcodeDetector({ formats }) : new BarcodeDetector();
      return state.detector;
    }

    async function startScanner() {
      if (state.running) return;

      try {
        state.stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: "environment" },
            width: { ideal: 1920 },
            height: { ideal: 1080 }
          },
          audio: false
        });
      } catch (err) {
        setStatus("Kamera konnte nicht gestartet werden. Bitte Berechtigung pruefen.", "warn");
        return;
      }

      videoEl.srcObject = state.stream;
      await videoEl.play();

      const detector = await ensureDetector();
      if (!detector) {
        setStatus("BarcodeDetector nicht verfuegbar. Bitte manuelle Eingabe nutzen.", "warn");
        return;
      }

      state.running = true;
      setButtons(true);
      setStatus("Scanner aktiv. Richte den Code auf den Rahmen.", "ok");
      scanLoop();
    }

    function stopScanner() {
      state.running = false;
      setButtons(false);
      if (state.stream) {
        for (const track of state.stream.getTracks()) track.stop();
      }
      state.stream = null;
      videoEl.srcObject = null;
      setStatus("Scanner gestoppt. Du kannst jederzeit neu starten.");
    }

    async function scanLoop() {
      if (!state.running || !state.detector) return;

      try {
        if (videoEl.readyState >= 2) {
          const codes = await state.detector.detect(videoEl);
          if (codes && codes.length > 0) {
            const code = codes[0];
            const rawValue = (code.rawValue || "").trim();
            const format = code.format || "unknown";
            if (rawValue) {
              const now = Date.now();
              if (rawValue !== state.lastValue || now - state.lastAt > 2800) {
                state.lastValue = rawValue;
                state.lastAt = now;
                if (navigator.vibrate) navigator.vibrate(45);
                await lookupValue(rawValue, format);
              }
            }
          }
        }
      } catch (err) {
        setStatus("Scan-Lauf aktiv, aber ein Frame konnte nicht gelesen werden.", "warn");
      }

      setTimeout(() => requestAnimationFrame(scanLoop), 130);
    }

    async function lookupValue(value, formatHint) {
      const display = `${value} (${formatHint || "unknown"})`;
      lastCode.textContent = `Letzter Scan: ${display}`;
      setStatus("Code erkannt. Produktdaten werden abgerufen...");

      const url = `${state.apiBase}/lookup?value=${encodeURIComponent(value)}&format=${encodeURIComponent(formatHint || "unknown")}`;
      clearResult();

      try {
        const response = await fetch(url, { method: "GET" });
        const payload = await response.json();

        if (!response.ok) {
          resultTitle.textContent = "Fehler bei der Abfrage";
          addRow("Details", payload.detail || "Unbekannter Fehler");
          setStatus("API-Fehler beim Nachschlagen.", "warn");
          return;
        }

        renderLookup(payload);
      } catch (err) {
        resultTitle.textContent = "Netzwerkfehler";
        addRow("Details", "Lookup-API ist nicht erreichbar.");
        setStatus("Netzwerkfehler beim Lookup.", "warn");
      }
    }

    function renderLookup(payload) {
      const lookup = payload.lookup || {};
      const classification = payload.classification || {};

      addRow("Code-Typ", classification.kind || "unbekannt");
      addRow("Normalisiert", classification.normalized || "");

      if (lookup.found && lookup.product) {
        const product = lookup.product;
        resultTitle.textContent = product.name || "Produkt gefunden";
        addRow("Quelle", product.source || "");
        addRow("Marke", product.brand || "");
        addRow("Menge", product.quantity || "");
        addRow("Kategorien", Array.isArray(product.categories) ? product.categories.join(", ") : "");
        addRow("Laender", Array.isArray(product.countries) ? product.countries.join(", ") : "");
        addRow("Haendler-Hinweise", Array.isArray(product.stores) ? product.stores.join(", ") : "");
        addRow("Label", Array.isArray(product.labels) ? product.labels.join(", ") : "");
        addRow("Nutri-Score", product.nutriscore || "");
        addRow("EAN", product.code || "");
        addRow("Produktseite", product.product_page_url || "");

        if (product.image_url) {
          productImage.src = product.image_url;
          productImage.style.display = "block";
        }
        addLinks(lookup.search_links || []);
        setStatus("Produkt erfolgreich gefunden.", "ok");
        return;
      }

      resultTitle.textContent = "Kein direkter Treffer";
      addRow("Info", lookup.message || "Kein Datensatz gefunden.");

      if (lookup.qr_payload) {
        addRow("QR Typ", lookup.qr_payload.type || "");
        addRow("QR Inhalt", lookup.qr_payload.url || lookup.qr_payload.preview || lookup.qr_payload.text || lookup.qr_payload.raw || "");
      }

      addLinks(lookup.search_links || []);
      setStatus("Kein strukturierter Treffer. Nutze die Suchlinks als Fallback.", "warn");
    }

    startBtn.addEventListener("click", async () => {
      await startScanner();
    });

    stopBtn.addEventListener("click", () => {
      stopScanner();
    });

    manualForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const value = (manualInput.value || "").trim();
      if (!value) return;
      await lookupValue(value, "manual");
    });

    window.addEventListener("beforeunload", () => {
      stopScanner();
    });

    state.apiBase = computeApiBase();
  </script>
</body>
</html>
"""
