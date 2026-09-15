#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <LibreOffice build dir>" >&2
  exit 64
fi

BUILD=$(cd "$1" && pwd)
FONT_DIR="$BUILD/instdir/share/fonts/truetype"
FONT="$FONT_DIR/NotoSansCJK-Regular.ttc"
LICENSE_DIR="$BUILD/row-third-party-licenses"
LICENSE="$LICENSE_DIR/NotoSansCJK-OFL-1.1.txt"

NOTO_COMMIT=f8d157532fbfaeda587e826d4cd5b21a49186f7c
FONT_PATH=Sans/OTC/NotoSansCJK-Regular.ttc
FONT_BLOB=a2033f163659aeab49c4d54aac59fe770ad05552
LICENSE_PATH=Sans/LICENSE

mkdir -p "$FONT_DIR" "$LICENSE_DIR"

if [ ! -f "$FONT" ] || [ "$(git hash-object "$FONT")" != "$FONT_BLOB" ]; then
  tmp="$FONT.tmp"
  rm -f "$tmp"
  curl --fail --location --retry 3 \
    "https://raw.githubusercontent.com/notofonts/noto-cjk/${NOTO_COMMIT}/${FONT_PATH}" \
    -o "$tmp"
  actual=$(git hash-object "$tmp")
  if [ "$actual" != "$FONT_BLOB" ]; then
    echo "Noto CJK blob mismatch: expected $FONT_BLOB, got $actual" >&2
    rm -f "$tmp"
    exit 65
  fi
  mv "$tmp" "$FONT"
fi

curl --fail --location --retry 3 \
  "https://raw.githubusercontent.com/notofonts/noto-cjk/${NOTO_COMMIT}/${LICENSE_PATH}" \
  -o "$LICENSE"

printf 'Noto CJK font: %s\n' "$FONT"
printf 'git blob: %s\n' "$(git hash-object "$FONT")"
printf 'bytes: %s\n' "$(wc -c < "$FONT")"
printf 'license: %s\n' "$LICENSE"
