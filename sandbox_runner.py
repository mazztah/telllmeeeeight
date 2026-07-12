# sandbox_runner.py – Sicherer Code-Execution-Service mit RestrictedPython
import ast
import builtins
import contextlib
import io
import logging
import math
import os
import re
import sys
import textwrap
import time
import traceback
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image

logger = logging.getLogger(__name__)

# ── Konfiguration ────────────────────────────────────────────────────────────
MAX_EXECUTION_TIME = 30  # Sekunden
MAX_OUTPUT_LENGTH = 50000  # Zeichen
MAX_MEMORY_MB = 256  # MB (soft limit via ulimit nicht möglich, aber wir können große Objekte blockieren)
FORBIDDEN_MODULES = {
    "os", "sys", "subprocess", "socket", "urllib", "http", "ftplib", "smtplib",
    "pickle", "marshal", "ctypes", "multiprocessing", "threading", "asyncio",
    "importlib", "imp", "builtins", "__builtin__",
}
FORBIDDEN_BUILTINS = {
    "__import__", "open", "exec", "eval", "compile", "input",
    "exit", "quit", "help", "dir", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "hasattr",
}

# ── AST-Validator ───────────────────────────────────────────────────────────────
class SandboxValidator(ast.NodeVisitor):
    """Prüft AST auf verbotene Konstrukte."""
    
    def __init__(self):
        self.errors: List[str] = []
        self.imported_names: set = set()
    
    def visit_Import(self, node):
        for alias in node.names:
            mod = alias.name.split(".")[0]
            if mod in FORBIDDEN_MODULES:
                self.errors.append(f"❌ Import von '{mod}' ist nicht erlaubt")
        self.generic_visit(node)
    
    def visit_ImportFrom(self, node):
        if node.module:
            mod = node.module.split(".")[0]
            if mod in FORBIDDEN_MODULES:
                self.errors.append(f"❌ Import aus '{mod}' ist nicht erlaubt")
        self.generic_visit(node)
    
    def visit_Call(self, node):
        # Blockiere eval(), exec(), compile()
        if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_BUILTINS:
            # __import__ wird sicher über SafeBuiltins._safe_import gehandhabt
            if node.func.id != "__import__":
                self.errors.append(f"❌ Aufruf von '{node.func.id}()' ist nicht erlaubt")
        self.generic_visit(node)
    
    def visit_Attribute(self, node):
        # Blockiere Zugriff auf __class__, __bases__, etc.
        if isinstance(node.attr, str) and node.attr.startswith("__") and node.attr.endswith("__"):
            if node.attr not in {"__name__", "__doc__", "__file__", "__package__"}:
                self.errors.append(f"❌ Zugriff auf '{node.attr}' ist nicht erlaubt")
        self.generic_visit(node)
    
    def visit_While(self, node):
        # Warnung bei potenziell endlosen Schleifen (einfache Heuristik)
        self.generic_visit(node)
    
    def visit_For(self, node):
        self.generic_visit(node)
    
    def validate(self, code: str) -> Tuple[bool, List[str]]:
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, [f"❌ Syntax-Fehler: {e}"]
        
        self.visit(tree)
        return len(self.errors) == 0, self.errors


# ── Sichere Builtins ──────────────────────────────────────────────────────────
class SafeBuiltins:
    """Eingeschränkte Builtins für die Sandbox."""
    
    SAFE = {
        "abs": abs,
        "all": all,
        "any": any,
        "ascii": ascii,
        "bin": bin,
        "bool": bool,
        "bytearray": bytearray,
        "bytes": bytes,
        "callable": callable,
        "chr": chr,
        "complex": complex,
        "divmod": divmod,
        "enumerate": enumerate,
        "filter": filter,
        "float": float,
        "format": format,
        "frozenset": frozenset,
        "hash": hash,
        "hex": hex,
        "int": int,
        "isinstance": isinstance,
        "issubclass": issubclass,
        "iter": iter,
        "len": len,
        "list": list,
        "map": map,
        "max": max,
        "min": min,
        "next": next,
        "oct": oct,
        "ord": ord,
        "pow": pow,
        "range": range,
        "repr": repr,
        "reversed": reversed,
        "round": round,
        "set": set,
        "slice": slice,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "type": type,
        "zip": zip,
        # Mathe
        "math": math,
        # Exceptions
        "Exception": Exception,
        "ValueError": ValueError,
        "TypeError": TypeError,
        "KeyError": KeyError,
        "IndexError": IndexError,
        "AttributeError": AttributeError,
        "ZeroDivisionError": ZeroDivisionError,
        "RuntimeError": RuntimeError,
        "StopIteration": StopIteration,
        "OverflowError": OverflowError,
        "ArithmeticError": ArithmeticError,
        "LookupError": LookupError,
        "AssertionError": AssertionError,
        "NotImplementedError": NotImplementedError,
        "MemoryError": MemoryError,
        "RecursionError": RecursionError,
    }

    @staticmethod
    def _safe_import(name, *args, **kwargs):
        """Sicheres Importieren – verhindert gefährliche Module."""
        if name in FORBIDDEN_MODULES or name.split(".")[0] in FORBIDDEN_MODULES:
            raise ImportError(f"Import von '{name}' ist in der Sandbox nicht erlaubt.")
        # Erlaubte sichere Imports weiterleiten
        return __import__(name, *args, **kwargs)


def get_safe_globals() -> Dict[str, Any]:
    """Erstellt ein sicheres Globals-Dict für exec()."""
    safe_globals = {
        "__builtins__": SafeBuiltins.SAFE,
        # Erlaubte Module
        "np": np,
        "pd": pd,
        "plt": plt,
        "Image": Image,
        "BytesIO": BytesIO,
        # Hilfsfunktionen
        "print": lambda *args, **kwargs: builtins.print(*args, **kwargs),
        "__name__": "__main__",
        "__file__": "sandbox.py",
        "__package__": None,
        # Sicheres Import
        "__import__": SafeBuiltins._safe_import,
    }
    return safe_globals


# ── Code-Ausführung ──────────────────────────────────────────────────────────
class TimeoutException(Exception):
    pass


def _run_with_timeout(code: str, globals_dict: Dict, locals_dict: Dict, timeout: int):
    """Führt Code mit Timeout aus (Threading-basiert)."""
    import threading
    
    result_container = {"output": None, "error": None, "completed": False}
    
    def target():
        try:
            output_buffer = io.StringIO()
            with contextlib.redirect_stdout(output_buffer):
                exec(code, globals_dict, locals_dict)
            result_container["output"] = output_buffer.getvalue()
            result_container["completed"] = True
        except Exception as e:
            result_container["error"] = e
    
    thread = threading.Thread(target=target)
    thread.daemon = True
    thread.start()
    thread.join(timeout)
    
    if thread.is_alive():
        raise TimeoutException(f"⏱️ Code hat das Zeitlimit von {timeout}s überschritten")
    
    if result_container["error"]:
        raise result_container["error"]
    
    return result_container["output"]


def _truncate_output(text: str, max_length: int = MAX_OUTPUT_LENGTH) -> str:
    if len(text) <= max_length:
        return text
    return text[:max_length] + f"\n\n...[gekürzt – {len(text) - max_length} Zeichen entfernt]"


def _extract_result_file(locals_dict: Dict) -> Optional[Tuple[BytesIO, str]]:
    """Extrahiert result_file aus den lokalen Variablen."""
    result_file = locals_dict.get("result_file")
    if not result_file:
        return None
    
    if isinstance(result_file, tuple) and len(result_file) >= 2:
        buf, fname = result_file[0], result_file[1]
    elif isinstance(result_file, dict):
        buf = result_file.get("buffer") or result_file.get("bytes") or result_file.get("content")
        fname = result_file.get("filename") or result_file.get("name") or "output.bin"
    else:
        return None
    
    if isinstance(buf, bytes):
        buf = BytesIO(buf)
    elif isinstance(buf, str):
        buf = BytesIO(buf.encode("utf-8"))
    
    if not hasattr(buf, "read"):
        return None
    
    buf.seek(0)
    return buf, str(fname)


def _extract_plot() -> Optional[BytesIO]:
    """Extrahiert Matplotlib-Plot als BytesIO."""
    if not plt.get_fignums():
        return None
    
    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=200, bbox_inches="tight")
    buf.seek(0)
    plt.close("all")
    return buf


async def run_sandboxed_code(
    code: str,
    chat_id: str = None,
    timeout: int = MAX_EXECUTION_TIME,
) -> Dict[str, Any]:
    """
    Führt Python-Code in einer Sandbox aus.
    
    Returns:
        {
            "success": bool,
            "output": str,
            "error": str | None,
            "plot": BytesIO | None,
            "file": Tuple[BytesIO, str] | None,
            "result": Any,
            "execution_time": float,
        }
    """
    start_time = time.time()
    
    # 1. Validierung
    validator = SandboxValidator()
    is_valid, errors = validator.validate(code)
    if not is_valid:
        return {
            "success": False,
            "output": "",
            "error": "\n".join(errors),
            "plot": None,
            "file": None,
            "result": None,
            "execution_time": 0.0,
        }
    
    # 2. Code vorbereiten
    safe_globals = get_safe_globals()
    locals_dict: Dict[str, Any] = {}
    
    output_buffer = io.StringIO()
    error = None
    plot_bytes = None
    result_file = None
    result_value = None
    
    try:
        with contextlib.redirect_stdout(output_buffer):
            # Führe Code aus
            _run_with_timeout(code, safe_globals, locals_dict, timeout)
            
            # Plot extrahieren
            plot_bytes = _extract_plot()
            
            # Result-File extrahieren
            result_file = _extract_result_file(locals_dict)
            
            # Result-Variable
            result_value = locals_dict.get("result")
            if result_value is None:
                result_value = "✅ Code erfolgreich ausgeführt."
    
    except TimeoutException as e:
        error = str(e)
        logger.warning("Sandbox Timeout für Chat %s: %s", chat_id, e)
    except Exception as exc:
        error = traceback.format_exc(limit=8)
        logger.error("Sandbox Fehler für Chat %s: %s", chat_id, exc)
    finally:
        plt.close("all")
    
    execution_time = time.time() - start_time
    output = _truncate_output(output_buffer.getvalue().strip())
    
    return {
        "success": error is None,
        "output": output,
        "error": error,
        "plot": plot_bytes,
        "file": result_file,
        "result": result_value,
        "execution_time": round(execution_time, 3),
    }


# ── HTML-Generator ───────────────────────────────────────────────────────────
def generate_html_app(html_code: str, title: str = "Mini App", css: str = "", js: str = "") -> Tuple[BytesIO, str]:
    """Generiert eine vollständige HTML-Datei für Mini-Apps."""
    full_html = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>{title}</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg: #0f0f1a;
            --surface: #1a1a2e;
            --surface2: #252540;
            --border: #2a2f3f;
            --text: #e8ecf4;
            --muted: #7a8099;
            --accent: #a78bfa;
            --accent2: #00d4aa;
            --gold: #f5c242;
            --red: #ff3366;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            margin: 0;
            padding: 0;
            background: var(--bg);
            color: var(--text);
            font-family: 'Inter', system-ui, sans-serif;
            min-height: 100vh;
            overflow-x: hidden;
        }}
        {css}
    </style>
</head>
<body>
    {html_code}
    <script>
        const tg = window.Telegram.WebApp;
        tg.expand();
        tg.ready();
        tg.setHeaderColor('#0f0f1a');
        tg.setBackgroundColor('#0f0f1a');
        {js}
    </script>
</body>
</html>"""
    
    buffer = BytesIO(full_html.encode("utf-8"))
    buffer.seek(0)
    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', title.lower().replace(' ', '_'))[:40]
    return buffer, f"{safe_name or 'mini_app'}.html"


# ── Beispiel-Code-Templates ───────────────────────────────────────────────────
EXAMPLE_TEMPLATES = {
    "hello": '''# Hallo Welt
print("Hallo aus der Sandbox! 🚀")
print("Mathe:", 2 + 2)
print("NP Array:", np.array([1, 2, 3]) * 2)
''',
    "plot": '''# Matplotlib Plot
import numpy as np
x = np.linspace(0, 10, 100)
y = np.sin(x) * np.exp(-x/3)

plt.figure(figsize=(10, 5))
plt.plot(x, y, color='#a78bfa', linewidth=2)
plt.fill_between(x, y, alpha=0.3, color='#a78bfa')
plt.title('Dämpfte Schwingung', color='white', fontsize=14)
plt.xlabel('Zeit', color='#7a8099')
plt.ylabel('Amplitude', color='#7a8099')
plt.grid(True, alpha=0.2)
plt.tight_layout()
print("Plot erstellt! 📊")
''',
    "dataframe": '''# Pandas DataFrame
import pandas as pd
import numpy as np

df = pd.DataFrame({
    "Name": ["Alice", "Bob", "Charlie", "Diana"],
    "Alter": [25, 30, 35, 28],
    "Stadt": ["Berlin", "München", "Hamburg", "Köln"],
    "Score": np.random.randint(60, 100, 4)
})

print(df.to_string())
print(f"\nDurchschnittsalter: {df['Alter'].mean():.1f}")
print(f"Durchschnittsscore: {df['Score'].mean():.1f}")

# Als Datei exportieren
result_file = (df.to_csv(index=False).encode('utf-8'), "daten.csv")
''',
    "chart": '''# Interaktiver Chart mit Matplotlib
import numpy as np

categories = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun"]
values = np.random.randint(20, 100, 6)
colors = ['#a78bfa', '#00d4aa', '#f5c242', '#ff3366', '#3b82f6', '#22c55e']

fig, ax = plt.subplots(figsize=(10, 6))
bars = ax.bar(categories, values, color=colors, edgecolor='white', linewidth=1.5)

for bar, val in zip(bars, values):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 2, 
            str(val), ha='center', va='bottom', color='white', fontweight='bold')

ax.set_title('Monatliche Performance', color='white', fontsize=16, fontweight='bold')
ax.set_ylabel('Wert', color='#7a8099')
ax.set_facecolor('#1a1a2e')
fig.patch.set_facecolor('#0f0f1a')
ax.tick_params(colors='#7a8099')
ax.spines['bottom'].set_color('#2a2f3f')
ax.spines['left'].set_color('#2a2f3f')
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)

plt.tight_layout()
print("Chart erstellt! 📊")
''',
    "mini_app": '''# Mini-App HTML generieren
html = """
<div style="text-align:center; padding:40px 20px;">
    <h1 style="color:#a78bfa; font-size:2rem; margin-bottom:20px;">🚀 Meine Mini-App</h1>
    <p style="color:#7a8099; margin-bottom:30px;">Erstellt mit der Sandbox</p>
    <button onclick="tg.showAlert('Hallo aus der Mini-App!')" 
            style="background:linear-gradient(135deg,#a78bfa,#00d4aa); color:#0f0f1a; 
                   border:none; padding:14px 28px; border-radius:12px; font-size:1rem; 
                   font-weight:700; cursor:pointer;">
        Klick mich!
    </button>
    <div id="counter" style="margin-top:30px; font-size:3rem; color:#f5c242; font-weight:700;">0</div>
    <button onclick="increment()" 
            style="background:#1a1a2e; color:#00d4aa; border:2px solid #00d4aa; 
                   padding:10px 20px; border-radius:8px; margin-top:10px; cursor:pointer;">
        +1
    </button>
</div>
"""

css = """
button:hover { transform: translateY(-2px); transition: transform 0.2s; }
"""

js = """
let count = 0;
function increment() {
    count++;
    document.getElementById('counter').textContent = count;
    tg.HapticFeedback.impactOccurred('light');
}
"""

from sandbox_runner import generate_html_app
buffer, filename = generate_html_app(html, "Meine App", css, js)
result_file = (buffer, filename)
print(f"Mini-App erstellt: {filename}")
''',
}


def get_example_templates() -> Dict[str, str]:
    """Gibt alle verfügbaren Code-Templates zurück."""
    return EXAMPLE_TEMPLATES.copy()
