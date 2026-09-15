#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <prepared-runtime-tree>" >&2
  exit 64
fi

ROOT=$(cd "$1" && pwd)
RESULT="$ROOT/row-acceptance-dom.txt"
PORT=${ROW_ACCEPTANCE_PORT:-18765}

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

python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$ROOT" \
  >"$ROOT/row-acceptance-http.log" 2>&1 &
server_pid=$!
cleanup() {
  kill "$server_pid" >/dev/null 2>&1 || true
  wait "$server_pid" 2>/dev/null || true
}
trap cleanup EXIT

for _ in $(seq 1 50); do
  if curl --fail --silent "http://127.0.0.1:${PORT}/acceptance.html" >/dev/null; then
    break
  fi
  sleep 0.1
done

"$chrome" \
  --headless=new \
  --no-sandbox \
  --disable-gpu \
  --disable-dev-shm-usage \
  --enable-features=WebAssembly \
  --virtual-time-budget=120000 \
  --dump-dom \
  "http://127.0.0.1:${PORT}/acceptance.html" \
  >"$RESULT" 2>"$ROOT/row-acceptance-chrome.log" || {
    cat "$ROOT/row-acceptance-chrome.log" >&2 || true
    exit 70
  }

if ! grep -q 'data-status="pass"' "$RESULT"; then
  echo "Reborn Office browser acceptance failed" >&2
  cat "$RESULT" >&2 || true
  cat "$ROOT/row-acceptance-chrome.log" >&2 || true
  exit 71
fi

echo "Reborn Office browser acceptance passed"
grep -A 80 -B 2 'data-status="pass"' "$RESULT" || true
