#!/usr/bin/env bash
set -euo pipefail
SRC=${SRC:-$PWD/libreoffice}
BUILD=${BUILD:-$PWD/lo-build}
TARBALLS=${TARBALLS:-$PWD/lo-tarballs}
PORT=${PORT:-$PWD/row-office-port}
IMAGE=${IMAGE:-public.ecr.aws/allotropia/libo-builders/wasm}
mkdir -p "$BUILD" "$TARBALLS"
python3 "$PORT/patch_lo.py" "$SRC"
cat > "$SRC/autogen.input" <<EOF
--disable-debug
--disable-optimized
--enable-sal-log
--disable-crashdump
--disable-online-update
--disable-scripting
--disable-gui
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

docker pull "$IMAGE"
set +e
docker run --rm \
  -v "$SRC:/src:rw" \
  -v "$BUILD:/build:rw" \
  -v "$TARBALLS:/ext_sources:rw" \
  -e ENABLE_EMSCRIPTEN_SINGLE_THREAD=TRUE \
  "$IMAGE" /bin/bash -lc '
    set -o pipefail
    source /home/builder/emsdk/emsdk_env.sh
    cd /build
    echo "[ROW] configure" | tee row-build.log
    ENABLE_EMSCRIPTEN_SINGLE_THREAD=TRUE /src/autogen.sh 2>&1 | tee -a row-build.log
    rc=${PIPESTATUS[0]}
    if [ "$rc" -ne 0 ]; then exit "$rc"; fi
    echo "[ROW] fetch external tarballs" | tee -a row-build.log
    ENABLE_EMSCRIPTEN_SINGLE_THREAD=TRUE make fetch -j2 2>&1 | tee -a row-build.log
    rc=${PIPESTATUS[0]}
    if [ "$rc" -ne 0 ]; then exit "$rc"; fi
    echo "[ROW] full headless Writer build" | tee -a row-build.log
    ENABLE_EMSCRIPTEN_SINGLE_THREAD=TRUE make -rj2 2>&1 | tee -a row-build.log
    exit ${PIPESTATUS[0]}
  '
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
