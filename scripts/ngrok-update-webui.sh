#!/bin/bash
# Ngrok URL updater for Open WebUI
# Po štarte ngrok získa novú URL a aktualizuje ju v Open WebUI DB
# Ak Open WebUI ešte nebeží, čaká a skúša znova

WEBUI_DB="/var/lib/docker/volumes/open-webui/_data/webui.db"
LOG="/var/log/ngrok-updater.log"
MAX_WAIT=60

echo "[$(date)] Ngrok update script started" >> "$LOG"

# 1. Čakáme na ngrok tunel
NGROK_URL=""
for i in $(seq 1 $MAX_WAIT); do
    NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | python3 -c "
import sys,json
try:
    data = json.loads(sys.stdin.read())
    for t in data.get('tunnels',[]):
        if t.get('public_url','').startswith('https://'):
            print(t['public_url']); break
except: pass
" 2>/dev/null)
    [ -n "$NGROK_URL" ] && break
    sleep 2
done

if [ -z "$NGROK_URL" ]; then
    echo "[$(date)] TIMEOUT: Ngrok tunnel not available" >> "$LOG"
    exit 1
fi

echo "[$(date)] Ngrok URL: $NGROK_URL" >> "$LOG"

# 2. Čakáme na Open WebUI DB
for i in $(seq 1 30); do
    if [ -f "$WEBUI_DB" ]; then
        break
    fi
    echo "[$(date)] Waiting for WebUI DB ($i/30)..." >> "$LOG"
    sleep 5
done

# 3. Aktualizujeme DB
python3 << PYEOF
import sqlite3, json, sys

NGROK_URL = "$NGROK_URL"
DB_PATH = "$WEBUI_DB"

try:
    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()
    cur.execute("SELECT data FROM config WHERE id=1")
    row = cur.fetchone()
    if row:
        config = json.loads(row[0])
        urls = config.get("openai", {}).get("api_base_urls", [])
        if len(urls) >= 2:
            config["openai"]["api_base_urls"][1] = f"{NGROK_URL}/v1"
        elif len(urls) == 1:
            config["openai"]["api_base_urls"].append(f"{NGROK_URL}/v1")
            config["openai"]["api_keys"].append("none")
            config["openai"]["api_configs"]["1"] = {
                "enable": True, "tags": [], "prefix_id": "ngrok",
                "model_ids": [], "connection_type": "external", "auth_type": "none"
            }
        cur.execute("UPDATE config SET data=? WHERE id=1", (json.dumps(config),))
        db.commit()
        print(f"OK: Updated ngrok URL to {NGROK_URL}/v1")
    else:
        print("WARNING: No config row found in DB")
    db.close()
except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF

echo "[$(date)] DB updated successfully" >> "$LOG"

# 4. Reštart Open WebUI aby načítal novú config
docker restart open-webui >> "$LOG" 2>&1
echo "[$(date)] Open WebUI restarted" >> "$LOG"
exit 0
