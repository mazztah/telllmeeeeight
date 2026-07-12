# 🔥 Polling Keepalive Guide – Render/Railway Free Tier

## Das Problem

Auf **Render Free Tier** und **Railway** schlafen Container nach ~15 Minuten Inaktivität ein. Wenn dein Bot im **Webhook-Mode** läuft, kann er nicht mehr aufwachen, weil:

1. Der Container ist eingefroren → Webhook-Endpoint nicht erreichbar
2. Telegram versucht, Updates an die Webhook-URL zu senden → schlägt fehl
3. Der Bot "verschläft" alle Nachrichten, bis jemand manuell neu deployt

## Die Lösung: Polling + Keepalive

Wir nutzen **Polling** statt Webhook. Der Bot fragt aktiv alle 30 Sekunden bei Telegram nach neuen Updates. Damit der Container nicht einschläft, brauchen wir einen externen Ping-Service.

---

## Setup Schritt-für-Schritt

### 1. Externen Ping-Service einrichten

Registriere dich bei einem dieser kostenlosen Dienste:

| Service | URL | Intervall |
|---------|-----|-----------|
| **UptimeRobot** | https://uptimerobot.com | Alle 5 Minuten (Free) |
| **Cron-Job.org** | https://cron-job.org | Alle 1-60 Minuten (Free) |
| **Ping-My-Dyno** | https://pingmydyno.com | Alle 5 Minuten (Free) |

**Wichtig:** Pinge die `/ping` Route deiner App an:
```
https://deine-app.onrender.com/ping
```

### 2. Environment Variables prüfen

Stelle sicher, dass in Render/Railway:

```bash
USE_WEBHOOK=false
```

gesetzt ist. Das ist jetzt auch in `render.yaml` so konfiguriert.

### 3. Offset-Persistenz

Der Bot speichert den letzten verarbeiteten Update-Offset in `last_update_offset.txt`. Das bedeutet:

- Nach einem Restart werden keine alten Updates doppelt verarbeitet
- Nachrichten, die während eines kurzen Ausfalls eintreffen, werden nachgeholt
- Die Datei wird automatisch erstellt und aktualisiert

### 4. Webhook-Watchdog

Selbst wenn ein externer Prozess versehentlich einen Webhook setzt, erkennt der Watchdog dies alle 2 Minuten und löscht ihn sofort. So bleibt der Polling-Loop aktiv.

---

## Troubleshooting

### Bot antwortet nicht nach längerer Inaktivität

1. Prüfe im Render-Dashboard, ob der Container läuft
2. Prüfe die Logs auf Fehler
3. Stelle sicher, dass der Ping-Service aktiv ist und auf `/ping` zeigt
4. Prüfe, ob `USE_WEBHOOK=false` gesetzt ist

### "Webhook entdeckt" Warnung in Logs

Das ist normal – der Watchdog arbeitet. Wenn diese Meldung häufig kommt, prüfe:
- Gibt es einen zweiten Bot-Prozess?
- Wird von extern ein Webhook gesetzt?

### Doppelte Nachrichten nach Restart

Das sollte mit der Offset-Persistenz nicht mehr passieren. Falls doch:
- Lösche `last_update_offset.txt` und starte neu
- Der Bot fängt dann bei Offset 0 an (alte Updates werden ignoriert)

---

## Technische Details

### Polling-Loop

```
get_updates(offset=gespeicherter_offset, timeout=30)
→ Verarbeite Updates
→ Speichere neuen Offset
→ Warte 0.5s wenn keine Updates
→ Wiederhole
```

### Fehlerbehandlung

- **Timeout**: Exponentielles Backoff bis max. 30s
- **Netzwerkfehler**: Exponentielles Backoff bis max. 30s
- **10 Fehler hintereinander**: 60s Pause, dann Reset

### Lifespan-Management

FastAPI nutzt jetzt den modernen `@asynccontextmanager` Lifespan statt `@app.on_event`. Das garantiert:
- Sauberes Startup auch bei komplexen Dependencies
- Graceful Shutdown mit Offset-Speicherung
- Keine Race Conditions beim Start

---

## Zusammenfassung

| Feature | Vorher | Nachher |
|---------|--------|---------|
| Mode | Webhook | **Polling** |
| Offset | Im RAM (verloren bei Restart) | **Persistiert in Datei** |
| Watchdog | 5 Minuten | **2 Minuten** |
| Startup | `@app.on_event` (deprecated) | **`@asynccontextmanager`** |
| Fehler-Handling | Generisch | **Spezifisch (Timeout/Netzwerk)** |
| Render Config | `USE_WEBHOOK=true` | **`USE_WEBHOOK=false`** |

---

## Support

Wenn der Bot weiterhin nicht aufwacht:

1. Prüfe die Logs in Render/Railway
2. Teste manuell: `curl https://deine-app.onrender.com/ping`
3. Stelle sicher, dass der Ping-Service wirklich alle 5 Minuten anfragt
4. Erhöhe ggf. das Log-Level auf `DEBUG` in `main.py`

