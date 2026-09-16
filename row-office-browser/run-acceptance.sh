#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <prepared-runtime-tree>" >&2
  exit 64
fi

ROOT=$(cd "$1" && pwd)
RESULT="$ROOT/row-acceptance-result.json"
HTTP_LOG="$ROOT/row-acceptance-http.log"
CHROME_LOG="$ROOT/row-acceptance-chrome.log"
TRUSTED_LOG="$ROOT/row-trusted-input.log"
PORT=${ROW_ACCEPTANCE_PORT:-18765}
TIMEOUT_SECONDS=${ROW_ACCEPTANCE_TIMEOUT_SECONDS:-180}
rm -f "$RESULT" "$HTTP_LOG" "$CHROME_LOG" "$TRUSTED_LOG"

chrome=""
for candidate in google-chrome google-chrome-stable chromium chromium-browser; do
  if command -v "$candidate" >/dev/null 2>&1; then
    chrome=$(command -v "$candidate")
    break
  fi
done
if [ -z "$chrome" ]; then
  echo "No Chromium/Chrome executable found" >&2
  exit 69
fi

SERVER_SCRIPT=$(mktemp)
export ROOT RESULT PORT
cat > "$SERVER_SCRIPT" <<'PY'
import http.server
import os
from pathlib import Path

root = os.environ['ROOT']
result = Path(os.environ['RESULT'])
port = int(os.environ['PORT'])

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=root, **kwargs)

    def do_POST(self):
        if self.path != '/__row_result__':
            self.send_error(404)
            return
        size = int(self.headers.get('content-length', '0'))
        body = self.rfile.read(size)
        temp = result.with_suffix(result.suffix + '.tmp')
        temp.write_bytes(body)
        temp.replace(result)
        self.send_response(204)
        self.end_headers()

http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
PY

python3 "$SERVER_SCRIPT" >"$HTTP_LOG" 2>&1 &
server_pid=$!
chrome_pid=''
cleanup() {
  if [ -n "$chrome_pid" ]; then
    kill "$chrome_pid" >/dev/null 2>&1 || true
    wait "$chrome_pid" 2>/dev/null || true
  fi
  kill "$server_pid" >/dev/null 2>&1 || true
  wait "$server_pid" 2>/dev/null || true
  rm -f "$SERVER_SCRIPT"
}
trap cleanup EXIT

ready=0
for _ in $(seq 1 50); do
  if curl --fail --silent "http://127.0.0.1:${PORT}/acceptance.html" >/dev/null; then
    ready=1
    break
  fi
  sleep 0.1
done
if [ "$ready" -ne 1 ]; then
  echo "Acceptance HTTP server did not become ready" >&2
  exit 70
fi

"$chrome" \
  --headless=new \
  --no-sandbox \
  --disable-gpu \
  --disable-dev-shm-usage \
  --enable-features=WebAssembly \
  "http://127.0.0.1:${PORT}/acceptance.html" \
  >/dev/null 2>"$CHROME_LOG" &
chrome_pid=$!

for _ in $(seq 1 "$TIMEOUT_SECONDS"); do
  if [ -s "$RESULT" ]; then
    break
  fi
  if ! kill -0 "$chrome_pid" 2>/dev/null; then
    echo "Chrome exited before reporting an acceptance result" >&2
    break
  fi
  sleep 1
done

if [ ! -s "$RESULT" ]; then
  echo "Reborn Office browser acceptance timed out after ${TIMEOUT_SECONDS}s" >&2
  cat "$CHROME_LOG" >&2 || true
  cat "$HTTP_LOG" >&2 || true
  exit 71
fi

python3 - "$RESULT" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding='utf-8'))
print(json.dumps(data, ensure_ascii=False, indent=2))
if data.get('status') != 'pass':
    raise SystemExit(72)
PY

# Synthetic DOM dispatches are not evidence that a physical keyboard works.
# Require ChromeDriver and a second browser session that produces trusted events.
if ! command -v chromedriver >/dev/null 2>&1; then
  echo "ChromeDriver is required for trusted keyboard acceptance" >&2
  exit 73
fi
if [ ! -s "$ROOT/trusted-input.html" ]; then
  echo "trusted-input.html is missing from prepared runtime" >&2
  exit 74
fi
CHROMEDRIVER=$(command -v chromedriver) \
  python3 "$SCRIPT_DIR/trusted-input-driver.py" \
  "http://127.0.0.1:${PORT}/trusted-input.html" \
  | tee "$TRUSTED_LOG"

grep -q '"status": "pass"\|"status":"pass"' "$TRUSTED_LOG"
echo "Reborn Office browser acceptance passed (including trusted physical-keyboard path)"
