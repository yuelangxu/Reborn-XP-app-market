#!/usr/bin/env bash
set -euo pipefail
IMAGE=${IMAGE:-public.ecr.aws/allotropia/libo-builders/wasm}
PREFIX=${PREFIX:?PREFIX is required}
SOURCE_ARCHIVE=${SOURCE_ARCHIVE:?SOURCE_ARCHIVE is required}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

mkdir -p "$PREFIX"
if [ -x "$PREFIX/bin/python3" ]; then
  echo "[ROW] cached builder Python found"
  "$PREFIX/bin/python3" --version
  exit 0
fi

# Public ECR occasionally returns transient pull-rate errors. Reuse a runner-local
# image when possible and retry before giving up instead of failing the whole
# compiler experiment before LibreOffice is reached.
bash "$SCRIPT_DIR/pull_builder_image.sh" "$IMAGE"

docker run --rm \
  -v "$PREFIX:/row-python:rw" \
  -v "$SOURCE_ARCHIVE:/python-src.tgz:ro" \
  "$IMAGE" /bin/bash -lc '
    set -euxo pipefail
    rm -rf /tmp/row-python-src
    mkdir -p /tmp/row-python-src
    tar -xzf /python-src.tgz -C /tmp/row-python-src --strip-components=1
    cd /tmp/row-python-src
    ./configure \
      --prefix=/row-python \
      --without-ensurepip \
      --disable-test-modules
    make -j2
    make install
    /row-python/bin/python3 --version
    /row-python/bin/python3 - <<"PY"
import sys, json, pathlib, hashlib, xml.etree.ElementTree
print(json.dumps({
    "version": sys.version,
    "executable": sys.executable,
    "prefix": sys.prefix,
    "stdlib": str(pathlib.Path(json.__file__).parent),
}))
PY
  '

echo "[ROW] builder Python ready: $PREFIX"
"$PREFIX/bin/python3" --version || true
