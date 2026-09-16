#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()


def replace_once(rel: str, old: str, new: str, label: str) -> None:
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Report browser acceptance through a real wall-clock HTTP harness.
replace_once(
    "row-office-browser/acceptance.html",
    """  function assert(condition, message) {
    if (!condition) throw new Error(message);
  }

  try {
""",
    """  function assert(condition, message) {
    if (!condition) throw new Error(message);
  }

  async function report(result) {
    try {
      await fetch('/__row_result__', {
        method: 'POST',
        headers: {'content-type': 'application/json'},
        body: JSON.stringify(result)
      });
    } catch (_) {}
  }

  try {
""",
    "acceptance result reporter",
)
replace_once(
    "row-office-browser/acceptance.html",
    "    console.log('ROW_ACCEPTANCE_PASS', finalResult);\n",
    "    console.log('ROW_ACCEPTANCE_PASS', finalResult);\n    await report(finalResult);\n",
    "acceptance pass report",
)
replace_once(
    "row-office-browser/acceptance.html",
    "    console.error('ROW_ACCEPTANCE_FAIL', failure);\n",
    "    console.error('ROW_ACCEPTANCE_FAIL', failure);\n    await report(failure);\n",
    "acceptance failure report",
)

# Fix the two canvas/input correctness bugs found during the LOK view audit.
replace_once(
    "row-office-browser/row-office-view.js",
    """      for (const tile of this.tiles.values()) {
        if (intersects(pxRect, tile)) tile.dirty = true;
      }
""",
    """      for (const tile of this.tiles.values()) {
        const tileRect = {
          x: tile.x, y: tile.y,
          width: tile.cssWidth, height: tile.cssHeight
        };
        if (intersects(pxRect, tileRect)) tile.dirty = true;
      }
""",
    "tile invalidation geometry",
)
replace_once(
    "row-office-browser/row-office-view.js",
    """        if (event.button === 0) return 1;
        if (event.button === 1) return 2;
        if (event.button === 2) return 4;
      }
      let value = 0;
      if (event.buttons & 1) value |= 1;
      if (event.buttons & 4) value |= 2;
      if (event.buttons & 2) value |= 4;
""",
    """        if (event.button === 0) return 1;
        if (event.button === 1) return 4;
        if (event.button === 2) return 2;
      }
      let value = 0;
      if (event.buttons & 1) value |= 1;
      if (event.buttons & 2) value |= 2;
      if (event.buttons & 4) value |= 4;
""",
    "LOK mouse button mapping",
)

# Persistent cheap-smoke regression guards.
replace_once(
    ".github/workflows/row-office-browser-smoke.yml",
    """          bash -n row-office-browser/prepare-runtime-tree.sh
          bash -n row-office-lok/prepare_cjk_font.sh
""",
    """          bash -n row-office-browser/prepare-runtime-tree.sh
          bash -n row-office-browser/run-acceptance.sh
          bash -n row-office-lok/prepare_cjk_font.sh
          ! grep -q -- '--virtual-time-budget' row-office-browser/run-acceptance.sh
          grep -q '__row_result__' row-office-browser/acceptance.html
          grep -q 'row-acceptance-result.json' row-office-browser/run-acceptance.sh
          grep -q 'width: tile.cssWidth' row-office-browser/row-office-view.js
          grep -q 'event.button === 1) return 4' row-office-browser/row-office-view.js
          grep -q 'event.button === 2) return 2' row-office-browser/row-office-view.js
""",
    "browser smoke runtime guards",
)

# Future failures get a tiny dedicated diagnostics artifact.
replace_once(
    ".github/workflows/row-office-core-port.yml",
    """          echo '--- browser acceptance ---'
          cat lo-build/ROW-browser-runtime/row-acceptance-dom.txt 2>/dev/null || true
""",
    """          echo '--- browser acceptance ---'
          cat lo-build/ROW-browser-runtime/row-acceptance-result.json 2>/dev/null \\
            || cat lo-build/ROW-browser-runtime/row-acceptance-dom.txt 2>/dev/null \\
            || true
""",
    "core browser acceptance display",
)
replace_once(
    ".github/workflows/row-office-core-port.yml",
    """            lo-build/ROW-browser-runtime/**

      - name: Upload accepted Reborn Office release
""",
    """            lo-build/ROW-browser-runtime/**

      - name: Upload runtime diagnostics
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: row-office-runtime-diagnostics
          retention-days: 14
          if-no-files-found: warn
          path: |
            lo-build/row-build-summary.json
            lo-build/runtime-files.txt
            lo-build/soffice-inspection.json
            lo-build/ROW-browser-runtime/row-acceptance-result.json
            lo-build/ROW-browser-runtime/row-acceptance-chrome.log
            lo-build/ROW-browser-runtime/row-acceptance-http.log

      - name: Upload accepted Reborn Office release
""",
    "tiny runtime diagnostics artifact",
)

run_acceptance = r'''#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <prepared-runtime-tree>" >&2
  exit 64
fi

ROOT=$(cd "$1" && pwd)
RESULT="$ROOT/row-acceptance-result.json"
HTTP_LOG="$ROOT/row-acceptance-http.log"
CHROME_LOG="$ROOT/row-acceptance-chrome.log"
PORT=${ROW_ACCEPTANCE_PORT:-18765}
TIMEOUT_SECONDS=${ROW_ACCEPTANCE_TIMEOUT_SECONDS:-180}
rm -f "$RESULT" "$HTTP_LOG" "$CHROME_LOG"

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

echo "Reborn Office browser acceptance passed"
'''
path = ROOT / "row-office-browser/run-acceptance.sh"
path.write_text(run_acceptance, encoding="utf-8")
path.chmod(0o755)

print("staged wall-clock acceptance, tiny diagnostics, and canvas/input fixes")
