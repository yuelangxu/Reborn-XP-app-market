#!/usr/bin/env bash
set -euo pipefail
SRC=${SRC:-$PWD/libreoffice}
BUILD=${BUILD:-$PWD/lo-build}
TARBALLS=${TARBALLS:-$PWD/lo-tarballs}
PORT=${PORT:-$PWD/row-office-port}
IMAGE=${IMAGE:-public.ecr.aws/allotropia/libo-builders/wasm}
HOST_PYTHON=${HOST_PYTHON:-}
mkdir -p "$BUILD" "$TARBALLS"
python3 "$PORT/patch_lo.py" "$SRC"
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
--disable-ccache
--disable-dynamic-loading
--enable-customtarget-components
--with-external-tar=/ext_sources
--with-build-platform-configure-options=--disable-ccache
EOF

# Keep the container payload in a real script file.  The previous inline
# single-quoted bash -lc payload was fragile: one apostrophe in a comment was
# enough to terminate the host shell string before Docker ever reached Meson.
cat > "$BUILD/row-container-build.sh" <<'ROW_CONTAINER_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
set -o pipefail
source /home/builder/emsdk/emsdk_env.sh
cd /build
: > row-build.log
log() { printf '%s\n' "$*" | tee -a row-build.log; }

# Diagnostics must never abort a build.  In particular, piping a version
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

log "[ROW] full headless Writer build"
CC_FOR_BUILD=clang CXX_FOR_BUILD=clang++ ENABLE_EMSCRIPTEN_SINGLE_THREAD=TRUE make -rj2 2>&1 | tee -a row-build.log
exit ${PIPESTATUS[0]}
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

set +e
docker run --rm \
  -v "$SRC:/src:rw" \
  -v "$BUILD:/build:rw" \
  -v "$TARBALLS:/ext_sources:rw" \
  "${PYMOUNT[@]}" \
  -e ENABLE_EMSCRIPTEN_SINGLE_THREAD=TRUE \
  "${PYENV[@]}" \
  "$IMAGE" /bin/bash /build/row-container-build.sh
rc=$?
set -e

python3 "$PORT/classify.py" "$BUILD/row-build.log" > "$BUILD/row-build-summary.json" || true
find "$BUILD" \( -name 'soffice.wasm' -o -name 'soffice.js' -o -name 'soffice.data' -o -name 'soffice.data.js.metadata' \) -print | sort > "$BUILD/runtime-files.txt" || true
WASM=$(find "$BUILD" -name soffice.wasm -print -quit || true)
if [ -n "$WASM" ]; then
  python3 "$PORT/inspect_wasm.py" "$WASM" > "$BUILD/soffice-inspection.json" || true
  cp "$WASM" "$BUILD/ROW-soffice.wasm"
fi
exit "$rc"
