#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "usage: $0 <libreoffice-emscripten-runtime-dir> <output-dir>" >&2
  exit 64
fi

RUNTIME_DIR=$(cd "$1" && pwd)
OUT=$2
HERE=$(cd "$(dirname "$0")" && pwd)
ZETA_COMMIT=b3dec98af5dc4c059a260afd6db0bf0fe38c6384
NOTO_CJK_COMMIT=f8d157532fbfaeda587e826d4cd5b21a49186f7c

rm -rf "$OUT"
mkdir -p "$OUT/runtime" "$OUT/vendor" "$OUT/THIRD_PARTY_LICENSES"

for name in soffice.js soffice.wasm soffice.data soffice.data.js.metadata; do
  if [ ! -f "$RUNTIME_DIR/$name" ]; then
    echo "missing LibreOffice runtime file: $RUNTIME_DIR/$name" >&2
    exit 66
  fi
  cp "$RUNTIME_DIR/$name" "$OUT/runtime/$name"
done

for name in reborn-office.js row-office-client.js row-office-view.js row-office-worker-loader.js row-office-thread.js; do
  cp "$HERE/$name" "$OUT/$name"
done

if [ -n "${ZETAJS_SOURCE:-}" ]; then
  cp "$ZETAJS_SOURCE" "$OUT/vendor/zeta.js"
else
  curl --fail --location --retry 3 \
    "https://raw.githubusercontent.com/allotropia/zetajs/${ZETA_COMMIT}/source/zeta.js" \
    -o "$OUT/vendor/zeta.js"
fi

if [ -n "${ZETAJS_LICENSE_SOURCE:-}" ]; then
  cp "$ZETAJS_LICENSE_SOURCE" "$OUT/THIRD_PARTY_LICENSES/ZetaJS-MIT.txt"
else
  curl --fail --location --retry 3 \
    "https://raw.githubusercontent.com/allotropia/zetajs/${ZETA_COMMIT}/LICENSE" \
    -o "$OUT/THIRD_PARTY_LICENSES/ZetaJS-MIT.txt"
fi

if [ -n "${NOTO_CJK_LICENSE_SOURCE:-}" ]; then
  cp "$NOTO_CJK_LICENSE_SOURCE" "$OUT/THIRD_PARTY_LICENSES/NotoSansCJK-OFL-1.1.txt"
else
  curl --fail --location --retry 3 \
    "https://raw.githubusercontent.com/notofonts/noto-cjk/${NOTO_CJK_COMMIT}/Sans/LICENSE" \
    -o "$OUT/THIRD_PARTY_LICENSES/NotoSansCJK-OFL-1.1.txt"
fi

python3 - "$OUT" "$ZETA_COMMIT" "$NOTO_CJK_COMMIT" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
zeta_commit = sys.argv[2]
noto_cjk_commit = sys.argv[3]
files = []
for path in sorted(p for p in root.rglob('*') if p.is_file()):
    data = path.read_bytes()
    files.append({
        'path': path.relative_to(root).as_posix(),
        'bytes': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
    })
manifest = {
    'format': 'reborn-office-runtime-v1',
    'execution': 'single-dedicated-worker',
    'sharedMemoryRequired': False,
    'nativeServerRequired': False,
    'zetajsCommit': zeta_commit,
    'notoCjkCommit': noto_cjk_commit,
    'files': files,
}
(root / 'runtime-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
PY

printf 'Reborn Office runtime tree prepared at %s\n' "$OUT"
