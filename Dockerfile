FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    git ffmpeg libsm6 libxext6 gcc g++ \
    portaudio19-dev libsndfile1 libassimp-dev \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 user

# WICHTIG: Verzeichnis VOR dem USER-Wechsel erstellen und chownen!
# app/data dient als beschreibbarer Fallback, falls kein Persistent Disk
# unter /data gemountet ist (z.B. auf Render ohne bezahlten Disk-Addon).
RUN mkdir -p /home/user/app/data && chown -R user:user /home/user/app

USER user
WORKDIR /home/user/app

ENV PATH="/home/user/.local/bin:$PATH"
ENV DATA_DIR="/home/user/app/data"

# Fallback-Port, falls die Plattform (Render, Railway, Cloud Run, HF Spaces, ...)
# keinen eigenen PORT setzt. Render setzt PORT zur Laufzeit automatisch und
# ueberschreibt diesen Default.
ENV PORT=8080

COPY --chown=user:user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY --chown=user:user . .

EXPOSE 8080

# --workers 1 ist Pflicht: der Telegram-Polling-Loop und globaler
# In-Memory-State laufen nur sicher mit genau einem Worker-Prozess.
# Mehrere Worker wuerden den Bot jede Nachricht mehrfach beantworten lassen.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT} --workers 1 --log-level info"]
