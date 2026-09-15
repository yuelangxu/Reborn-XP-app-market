#!/usr/bin/env python3
"""Add the pinned ROW CJK fallback font to LibreOffice's Emscripten FS image."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
MK = ROOT / "static/CustomTarget_emscripten_fs_image.mk"

if not MK.is_file():
    raise SystemExit(f"Not a LibreOffice checkout: {ROOT}")

text = MK.read_text(encoding="utf-8")
old = "    $(INSTROOT)/$(LIBO_SHARE_FOLDER)/fonts/truetype/fc_local.conf \\\n"
new = (
    "    $(INSTROOT)/$(LIBO_SHARE_FOLDER)/fonts/truetype/fc_local.conf \\\n"
    "    $(INSTROOT)/$(LIBO_SHARE_FOLDER)/fonts/truetype/NotoSansCJK-Regular.ttc \\\n"
)
count = text.count(old)
if count != 1:
    raise RuntimeError(f"font FS anchor: expected exactly one match, found {count}")
MK.write_text(text.replace(old, new, 1), encoding="utf-8")
print("ROW CJK font added to Emscripten filesystem image")
