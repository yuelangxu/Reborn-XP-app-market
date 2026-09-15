#!/usr/bin/env bash
set -euo pipefail
SRC=${SRC:-$PWD/libreoffice}
BUILD=${BUILD:-$PWD/lo-build}
TARBALLS=${TARBALLS:-$PWD/lo-tarballs}
PORT=${PORT:-$PWD/row-office-port}
HARNESS=${HARNESS:-$(cd "$PORT/.." && pwd)}
IMAGE=${IMAGE:-public.ecr.aws/allotropia/libo-builders/wasm}
HOST_PYTHON=${HOST_PYTHON:-}
CCACHE_HOST_DIR=${CCACHE_HOST_DIR:-$PWD/lo-ccache}
mkdir -p "$BUILD" "$TARBALLS" "$CCACHE_HOST_DIR"

# Pinned source transforms.  The expensive branch is prepared so the next
# compiler-feedback iteration can carry the real blocker fix plus all runtime
# integration work in one build.
python3 "$PORT/patch_lo.py" "$SRC"
python3 "$HARNESS/row-office-lok/integrate_bridge.py" "$SRC"
python3 "$HARNESS/row-office-lok/integrate_cjk_font.py" "$SRC"

cat > "$BUILD/autogen.input" <<EOF
--disable-debug
--disable-optimized
--enable-sal-log
--disable-crashdump
--disable-online-update
--disable-scripting
--disable-gui
--build=x86_64-pc-linux-gnu
--host=wasm32-local-emscripten
--with-wasm-module=writer
--with-package-format=emscripten
--without-java
--without-help
--enable-ccache
--disable-dynamic-loading
--enable-customtarget-components
--with-fonts
--with-external-tar=/ext_sources
--with-build-platform-configure-options=--enable-ccache
EOF

cat > "$BUILD/row-container-build.sh" <<'ROW_CONTAINER_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
set -o pipefail
cd /build
: > row-build.log
log() { printf '%s\n' "$*" | tee -a row-build.log; }

EMSCRIPTEN_ROOT=/home/builder/emsdk/emscripten/main
if [ -e "$EMSCRIPTEN_ROOT/.git" ]; then
  if git -C "$EMSCRIPTEN_ROOT" rev-parse --verify HEAD >/dev/null 2>&1; then
    em_git_head=$(git -C "$EMSCRIPTEN_ROOT" rev-parse --verify HEAD 2>/dev/null || true)
    log "[ROW] Emscripten git metadata valid: ${em_git_head:-unknown}"
  else
    quarantine="$EMSCRIPTEN_ROOT/.git.row-invalid"
    rm -rf "$quarantine"
    mv "$EMSCRIPTEN_ROOT/.git" "$quarantine"
    log "[ROW] quarantined broken Emscripten .git metadata"
  fi
else
  log "[ROW] Emscripten is already in packaged no-.git form"
fi

source /home/builder/emsdk/emsdk_env.sh

log "[ROW] native compiler probe"
for tool in clang emcc; do
  tool_path=$(command -v "$tool" || true)
  if [ -z "$tool_path" ]; then
    log "[ROW] WARNING: $tool is not on PATH"
    continue
  fi
  log "[ROW] $tool path: $tool_path"
  if "$tool" --version >> row-build.log 2>&1; then
    log "[ROW] $tool version probe rc=0"
  else
    probe_rc=$?
    log "[ROW] WARNING: $tool --version rc=$probe_rc"
  fi
done

if ! command -v ccache >/dev/null 2>&1; then
  log "[ROW] ERROR: ccache is not available in the WASM builder"
  exit 87
fi
export CCACHE_DIR=/ccache
export CCACHE_BASEDIR=/src
export CCACHE_COMPILERCHECK=content
export CCACHE_MAXSIZE=4G
export CCACHE_COMPRESS=1
log "[ROW] ccache probe"
ccache --version 2>&1 | tee -a row-build.log
ccache -M 4G 2>&1 | tee -a row-build.log
ccache -s 2>&1 | tee -a row-build.log || true

if [ -n "${ROW_PYTHON:-}" ]; then
  export PATH=/opt/row-python/bin:$PATH
  export LD_LIBRARY_PATH=/opt/row-python/lib:${LD_LIBRARY_PATH:-}
  export PYTHON_FOR_BUILD="$ROW_PYTHON"
  export PYTHON="$ROW_PYTHON"

  log "[ROW] mounted Python probe"
  "$ROW_PYTHON" --version 2>&1 | tee -a row-build.log
  "$ROW_PYTHON" - <<'PY' 2>&1 | tee -a row-build.log
import json, sys
print(json.dumps({
    "executable": sys.executable,
    "version": sys.version,
    "prefix": sys.prefix,
    "path": sys.path,
}, indent=2))
PY

  log "[ROW] system Meson executable probe"
  if command -v meson >/dev/null 2>&1; then
    command -v meson | tee -a row-build.log
    meson --version 2>&1 | tee -a row-build.log || true
    head -n 1 "$(command -v meson)" 2>/dev/null | tee -a row-build.log || true
  else
    log "[ROW] system meson command not found"
  fi

  log "[ROW] discover mesonbuild package without importing it"
  MESON_INIT=""
  for root in \
      /usr/lib/python3/dist-packages \
      /usr/local/lib/python3/dist-packages \
      /usr/local/lib/python3/site-packages \
      /usr/lib/python3/site-packages; do
    if [ -f "$root/mesonbuild/__init__.py" ]; then
      MESON_INIT="$root/mesonbuild/__init__.py"
      break
    fi
  done
  if [ -z "$MESON_INIT" ]; then
    MESON_INIT=$(find /usr/lib /usr/local/lib \
      -maxdepth 6 -type f -path '*/mesonbuild/__init__.py' \
      -print -quit 2>/dev/null || true)
  fi
  if [ -z "$MESON_INIT" ]; then
    log "[ROW] ERROR: mesonbuild package was not found in the builder image"
    exit 86
  fi
  MESON_SITE=${MESON_INIT%/mesonbuild/__init__.py}
  export PYTHONPATH="$MESON_SITE${PYTHONPATH:+:$PYTHONPATH}"
  log "[ROW] Meson package: $MESON_INIT"
  log "[ROW] Meson site root: $MESON_SITE"

  log "[ROW] mounted Python imports mesonbuild"
  "$ROW_PYTHON" - <<'PY' 2>&1 | tee -a row-build.log
import json, mesonbuild, pathlib, sys
print(json.dumps({
    "python": sys.executable,
    "mesonbuild": str(pathlib.Path(mesonbuild.__file__).resolve()),
}, indent=2))
PY
  rc=${PIPESTATUS[0]}
  if [ "$rc" -ne 0 ]; then
    log "[ROW] ERROR: mounted Python cannot import discovered mesonbuild package"
    exit "$rc"
  fi

  MESON_BIN=$(command -v meson || true)
  if [ -z "$MESON_BIN" ]; then
    MESON_BIN=/usr/bin/meson
  fi
  log "[ROW] mounted Python executes Meson: $MESON_BIN"
  "$ROW_PYTHON" "$MESON_BIN" --version 2>&1 | tee -a row-build.log
  rc=${PIPESTATUS[0]}
  if [ "$rc" -ne 0 ]; then
    log "[ROW] ERROR: mounted Python failed to execute Meson"
    exit "$rc"
  fi
fi

log "[ROW] configure"
log "[ROW] explicit build triplet: x86_64-pc-linux-gnu"
log "[ROW] explicit host triplet: wasm32-local-emscripten"
CC_FOR_BUILD=clang CXX_FOR_BUILD=clang++ ENABLE_EMSCRIPTEN_SINGLE_THREAD=TRUE /src/autogen.sh 2>&1 | tee -a row-build.log
rc=${PIPESTATUS[0]}
if [ "$rc" -ne 0 ]; then exit "$rc"; fi

log "[ROW] fetch external tarballs"
CC_FOR_BUILD=clang CXX_FOR_BUILD=clang++ ENABLE_EMSCRIPTEN_SINGLE_THREAD=TRUE make fetch -j2 2>&1 | tee -a row-build.log
rc=${PIPESTATUS[0]}
if [ "$rc" -ne 0 ]; then exit "$rc"; fi

log "[ROW] install pinned pan-CJK fallback font"
bash /harness/row-office-lok/prepare_cjk_font.sh /build 2>&1 | tee -a row-build.log
rc=${PIPESTATUS[0]}
if [ "$rc" -ne 0 ]; then exit "$rc"; fi

log "[ROW] full headless Writer build"
set +e
CC_FOR_BUILD=clang CXX_FOR_BUILD=clang++ ENABLE_EMSCRIPTEN_SINGLE_THREAD=TRUE make -rj2 2>&1 | tee -a row-build.log
rc=${PIPESTATUS[0]}
set -e
log "[ROW] ccache final stats"
ccache -s 2>&1 | tee -a row-build.log || true
exit "$rc"
ROW_CONTAINER_SCRIPT
chmod +x "$BUILD/row-container-build.sh"

bash "$PORT/pull_builder_image.sh" "$IMAGE"
PYMOUNT=()
PYENV=()
if [ -n "$HOST_PYTHON" ] && [ -x "$HOST_PYTHON/bin/python3" ]; then
  PYMOUNT=(-v "$HOST_PYTHON:/opt/row-python:ro")
  PYENV=(-e ROW_PYTHON=/opt/row-python/bin/python3)
fi

set +e
docker run --rm \
  -v "$SRC:/src:rw" \
  -v "$BUILD:/build:rw" \
  -v "$TARBALLS:/ext_sources:rw" \
  -v "$HARNESS:/harness:ro" \
  -v "$CCACHE_HOST_DIR:/ccache:rw" \
  "${PYMOUNT[@]}" \
  -e ENABLE_EMSCRIPTEN_SINGLE_THREAD=TRUE \
  "${PYENV[@]}" \
  "$IMAGE" /bin/bash /build/row-container-build.sh
rc=$?
set -e

python3 "$PORT/classify.py" "$BUILD/row-build.log" > "$BUILD/row-build-summary.json" || true
find "$BUILD" \( -name 'soffice.wasm' -o -name 'soffice.js' -o -name 'soffice.data' -o -name 'soffice.data.js.metadata' \) -print | sort > "$BUILD/runtime-files.txt" || true

RUNTIME_DIR=""
while IFS= read -r wasm; do
  dir=$(dirname "$wasm")
  if [ -f "$dir/soffice.js" ] && [ -f "$dir/soffice.data" ] && [ -f "$dir/soffice.data.js.metadata" ]; then
    RUNTIME_DIR="$dir"
    break
  fi
done < <(find "$BUILD" -name soffice.wasm -type f -print 2>/dev/null | sort)

if [ -n "$RUNTIME_DIR" ]; then
  WASM="$RUNTIME_DIR/soffice.wasm"
  python3 "$PORT/inspect_wasm.py" "$WASM" > "$BUILD/soffice-inspection.json"
  cp "$WASM" "$BUILD/ROW-soffice.wasm"
  python3 - "$BUILD/soffice-inspection.json" <<'PY'
import json, sys
report = json.load(open(sys.argv[1], encoding='utf-8'))
if report.get('sharedMemory'):
    raise SystemExit('ROW invariant failed: soffice.wasm declares shared memory')
print('ROW WASM invariant: non-shared memory')
PY
  inspect_rc=$?
  if [ "$inspect_rc" -ne 0 ] && [ "$rc" -eq 0 ]; then rc=$inspect_rc; fi
fi

if [ "$rc" -eq 0 ]; then
  if [ -z "$RUNTIME_DIR" ]; then
    echo "ROW build reported success but no complete soffice runtime directory was found" >&2
    rc=88
  else
    set +e
    NOTO_CJK_LICENSE_SOURCE="$BUILD/row-third-party-licenses/NotoSansCJK-OFL-1.1.txt" \
      bash "$HARNESS/row-office-browser/prepare-runtime-tree.sh" \
      "$RUNTIME_DIR" "$BUILD/row-runtime-tree"
    package_rc=$?
    if [ "$package_rc" -eq 0 ]; then
      bash "$HARNESS/row-office-browser/run-acceptance.sh" "$BUILD/row-runtime-tree"
      acceptance_rc=$?
    else
      acceptance_rc=$package_rc
    fi
    set -e
    if [ "$acceptance_rc" -ne 0 ]; then rc=$acceptance_rc; fi
  fi
fi

exit "$rc"
