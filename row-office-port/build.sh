#!/usr/bin/env bash
set -euo pipefail
SRC=${SRC:-$PWD/libreoffice}
BUILD=${BUILD:-$PWD/lo-build}
TARBALLS=${TARBALLS:-$PWD/lo-tarballs}
PORT=${PORT:-$PWD/row-office-port}
IMAGE=${IMAGE:-public.ecr.aws/allotropia/libo-builders/wasm}
HOST_PYTHON=${HOST_PYTHON:-}
ROW_CCACHE_DIR=${ROW_CCACHE_DIR:-}
mkdir -p "$BUILD" "$TARBALLS"
if [ -n "$ROW_CCACHE_DIR" ]; then
  mkdir -p "$ROW_CCACHE_DIR"
fi
python3 "$PORT/patch_lo.py" "$SRC"
cat > "$BUILD/autogen.input" <<EOF
--disable-debug
--disable-optimized
--enable-sal-log
--disable-crashdump
--disable-online-update
--disable-scripting
--disable-gui
--disable-emscripten-proxy-to-pthread
--build=x86_64-pc-linux-gnu
--host=wasm32-local-emscripten
--with-wasm-module=writer
--with-package-format=emscripten
--without-java
--without-help
--enable-ccache
--disable-dynamic-loading
--enable-customtarget-components
--with-external-tar=/ext_sources
--with-build-platform-configure-options=--enable-ccache
EOF

# Keep the container payload in a real script file. The previous inline
# single-quoted bash -lc payload was fragile: one apostrophe in a comment was
# enough to terminate the host shell string before Docker ever reached Meson.
cat > "$BUILD/row-container-build.sh" <<'ROW_CONTAINER_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
set -o pipefail
cd /build
: > row-build.log
log() { printf '%s\n' "$*" | tee -a row-build.log; }

# The Allotropia builder currently contains Emscripten source with a .git entry
# whose referenced repository metadata is unavailable in the published image.
# Emscripten 3.x sees that .git entry and unconditionally runs
# `git rev-parse HEAD` while identifying the compiler. That makes even
# `emcc --version` fail, and Meson consequently reports "Unknown compiler".
# Packaged Emscripten explicitly supports running without .git and falls back
# to its packaged revision/version file, so quarantine only demonstrably broken
# metadata. Do not touch a valid checkout.
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

# Use a persistent ccache directory when the workflow mounted one. If an older
# builder image unexpectedly lacks ccache, fall back to a non-ccache configure
# rather than turning a performance optimization into a build blocker.
if command -v ccache >/dev/null 2>&1 && [ "${ROW_CCACHE_ACTIVE:-0}" = "1" ]; then
  export CCACHE_DIR=${CCACHE_DIR:-/row-ccache}
  export CCACHE_BASEDIR=${CCACHE_BASEDIR:-/src}
  export CCACHE_COMPILERCHECK=${CCACHE_COMPILERCHECK:-content}
  export CCACHE_NOHASHDIR=true
  mkdir -p "$CCACHE_DIR"
  ccache --version 2>&1 | head -n 2 | tee -a row-build.log || true
  ccache -M 4G 2>&1 | tee -a row-build.log || true
  ccache -z 2>&1 | tee -a row-build.log || true
  log "[ROW] persistent ccache enabled at $CCACHE_DIR"
else
  log "[ROW] ccache unavailable; falling back to uncached build"
  sed -i 's/--enable-ccache/--disable-ccache/g' /build/autogen.input
fi

# Diagnostics must never abort a build. In particular, piping a version
# command through head while pipefail is active can turn an innocent SIGPIPE
# into a fatal probe failure.
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

if [ -n "${ROW_PYTHON:-}" ]; then
  export PATH=/opt/row-python/bin:$PATH
  export LD_LIBRARY_PATH=/opt/row-python/lib:${LD_LIBRARY_PATH:-}
  export PYTHON_FOR_BUILD="$ROW_PYTHON"
  export PYTHON="$ROW_PYTHON"

  log "[ROW] mounted Python probe"
  "$ROW_PYTHON" --version 2>&1 | tee -a row-build.log
  "$ROW_PYTHON" - <<'PY' 2>&1 | tee -a row-build.log
import json, os, sys
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

# The CJK font is downloaded outside instdir so configure/build setup cannot
# accidentally delete it. Install the verified pinned asset immediately before
# the real build creates the Emscripten filesystem image.
ROW_CJK_FONT=/build/row-assets/NotoSansCJK-Regular.ttc
if [ -f "$ROW_CJK_FONT" ]; then
  ROW_CJK_DEST=/build/instdir/share/fonts/truetype/NotoSansCJK-Regular.ttc
  mkdir -p "$(dirname "$ROW_CJK_DEST")"
  cp "$ROW_CJK_FONT" "$ROW_CJK_DEST"
  expected_blob=a2033d0e4e53f568c3f418a7d5d8c951af3f76c1
  actual_blob=$(git hash-object "$ROW_CJK_DEST")
  if [ "$actual_blob" != "$expected_blob" ]; then
    log "[ROW] ERROR: staged CJK font changed before install: $actual_blob"
    exit 87
  fi
  log "[ROW] installed verified NotoSansCJK-Regular.ttc into instdir"
else
  log "[ROW] WARNING: no staged CJK font found at $ROW_CJK_FONT"
fi

log "[ROW] full headless Writer build"
CC_FOR_BUILD=clang CXX_FOR_BUILD=clang++ ENABLE_EMSCRIPTEN_SINGLE_THREAD=TRUE make -rj2 2>&1 | tee -a row-build.log
build_rc=${PIPESTATUS[0]}
if command -v ccache >/dev/null 2>&1 && [ "${ROW_CCACHE_ACTIVE:-0}" = "1" ]; then
  log "[ROW] ccache statistics after build"
  ccache -s 2>&1 | tee -a row-build.log || true
fi
exit "$build_rc"
ROW_CONTAINER_SCRIPT
chmod +x "$BUILD/row-container-build.sh"

# bootstrap_python.sh may already have pulled the image on this runner. Avoid a
# second registry request and use the same retry policy if the image is absent.
bash "$PORT/pull_builder_image.sh" "$IMAGE"
PYMOUNT=()
PYENV=()
if [ -n "$HOST_PYTHON" ] && [ -x "$HOST_PYTHON/bin/python3" ]; then
  PYMOUNT=(-v "$HOST_PYTHON:/opt/row-python:ro")
  PYENV=(-e ROW_PYTHON=/opt/row-python/bin/python3)
fi
CCACHEMOUNT=()
CCACHEENV=()
if [ -n "$ROW_CCACHE_DIR" ]; then
  CCACHEMOUNT=(-v "$ROW_CCACHE_DIR:/row-ccache:rw")
  CCACHEENV=(
    -e ROW_CCACHE_ACTIVE=1
    -e CCACHE_DIR=/row-ccache
    -e CCACHE_BASEDIR=/src
    -e CCACHE_COMPILERCHECK=content
  )
fi

set +e
docker run --rm \
  -v "$SRC:/src:rw" \
  -v "$BUILD:/build:rw" \
  -v "$TARBALLS:/ext_sources:rw" \
  "${PYMOUNT[@]}" \
  "${CCACHEMOUNT[@]}" \
  -e ENABLE_EMSCRIPTEN_SINGLE_THREAD=TRUE \
  "${PYENV[@]}" \
  "${CCACHEENV[@]}" \
  "$IMAGE" /bin/bash /build/row-container-build.sh
rc=$?
set -e

python3 "$PORT/classify.py" "$BUILD/row-build.log" > "$BUILD/row-build-summary.json" || true
find "$BUILD" \( -name 'soffice.wasm' -o -name 'soffice.js' -o -name 'soffice.data' -o -name 'soffice.data.js.metadata' -o -name 'soffice.worker.js' \) -print | sort > "$BUILD/runtime-files.txt" || true
WASM=$(find "$BUILD" -name soffice.wasm -print -quit || true)
if [ -n "$WASM" ]; then
  python3 "$PORT/inspect_wasm.py" "$WASM" > "$BUILD/soffice-inspection.json" || true
  cp "$WASM" "$BUILD/ROW-soffice.wasm"
fi
exit "$rc"
