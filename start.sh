#!/usr/bin/env bash
set -euo pipefail

echo "[start] begin"

# ---------- 0) Java 17 แบบพกพา (ไม่มี apt) ----------
JDK_DIR=".jdk17"
if [ ! -d "$JDK_DIR" ]; then
  echo "[start] downloading Temurin JRE 17..."
  JRE_URL="https://github.com/adoptium/temurin17-binaries/releases/download/jre-17.0.13%2B11/OpenJDK17U-jre_x64_linux_hotspot_17.0.13_11.tar.gz"
  mkdir -p "$JDK_DIR"
  if command -v curl >/dev/null 2>&1; then
    curl -L "$JRE_URL" -o jre17.tar.gz
  else
    wget -O jre17.tar.gz "$JRE_URL"
  fi
  tar -xzf jre17.tar.gz --strip-components=1 -C "$JDK_DIR"
  rm -f jre17.tar.gz
fi
export JAVA_HOME="$PWD/$JDK_DIR"
export PATH="$JAVA_HOME/bin:$PATH"

# ---------- 1) Python venv & deps ----------
if [ ! -d ".venv" ]; then
  echo "[start] creating venv"
  python3 -m venv .venv || python -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

# ---------- 2) Run Lavalink (background) ----------
echo "[start] launching Lavalink"
pushd lavalink >/dev/null
nohup "$JAVA_HOME/bin/java" -Xms128m -Xmx512m -jar Lavalink.jar > ../lavalink.out 2>&1 &
popd >/dev/null

# ---------- 3) Wait for :2333 ----------
python3 - <<'PY'
import socket,time
addr=('127.0.0.1',2333)
for i in range(60):
    try:
        with socket.create_connection(addr, timeout=1): pass
        print("[wait] lavalink ready"); break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit("[wait] lavalink not ready in time")
PY

# ---------- 4) Run bot (background) ----------
echo "[start] launching bot"
nohup .venv/bin/python bot/main.py > bot.out 2>&1 &

# ---------- 5) Health server (foreground) ----------
PORT="${PORT:-10000}"
echo "[start] serving health on :$PORT"
python3 - <<PY
import http.server, os
PORT=int(os.environ.get("PORT","10000"))
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self,*a): pass
http.server.ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
PY
