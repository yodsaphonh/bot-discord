#!/usr/bin/env bash
set -euo pipefail

echo "=== Build-time dependencies (once) ==="
# Render อนุญาต apt ใน build/start ได้
apt-get update -y
apt-get install -y openjdk-17-jre-headless python3-venv

echo "=== Python venv & deps ==="
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "=== Launch Lavalink ==="
pushd lavalink >/dev/null
# ปิดพอร์ตภายนอก ไม่ต้อง — เราคุย 127.0.0.1 กันเอง
nohup java -Xms128m -Xmx512m -jar Lavalink.jar > ../lavalink.out 2>&1 &
popd >/dev/null

# รอให้ Lavalink พร้อม (พอร์ต 2333)
echo "=== Wait Lavalink :2333 ==="
for i in {1..30}; do
  nc -z 127.0.0.1 2333 && break || sleep 1
done

echo "=== Launch Discord bot ==="
nohup .venv/bin/python bot/main.py > bot.out 2>&1 &

# เปิดเว็บพอร์ต (Render ต้องมีโปรเซส foreground ฟังที่ $PORT)
echo "=== Serve health on \$PORT=${PORT:-10000} ==="
python3 - <<'PY'
import http.server, os
PORT = int(os.environ.get("PORT","10000"))
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *a): pass
http.server.ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
PY
