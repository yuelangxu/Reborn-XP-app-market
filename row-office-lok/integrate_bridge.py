#!/usr/bin/env python3
"""Stage the ROW LOK bridge into a pinned LibreOffice checkout.

This helper intentionally lives outside row-office-port so editing it does not
start another multi-hour core build.  Once the current compiler frontier is
known, patch_lo.py can call the same deterministic transform.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
HARNESS = Path(__file__).resolve().parent
BRIDGE = HARNESS / "row_lok_bridge.cxx"
TARGET = ROOT / "static/source/unoembindhelpers/RowLokBridge.cxx"
MK = ROOT / "static/StaticLibrary_unoembind.mk"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


if not BRIDGE.is_file():
    raise SystemExit(f"Missing staged bridge: {BRIDGE}")
if not MK.is_file():
    raise SystemExit(f"Not a LibreOffice checkout: {ROOT}")

TARGET.write_text(BRIDGE.read_text(encoding="utf-8"), encoding="utf-8")

text = MK.read_text(encoding="utf-8")
text = replace_once(
    text,
    "$(eval $(call gb_StaticLibrary_StaticLibrary,unoembind))\n\n",
    "$(eval $(call gb_StaticLibrary_StaticLibrary,unoembind))\n\n"
    "$(eval $(call gb_StaticLibrary_set_include,unoembind,\\\n"
    "    $$(INCLUDE) \\\n"
    "    -I$(SRCDIR)/desktop/inc \\\n"
    "))\n\n",
    "unoembind include path",
)
text = replace_once(
    text,
    "$(eval $(call gb_StaticLibrary_add_exception_objects,unoembind, \\\n"
    "    static/source/unoembindhelpers/PrimaryBindings \\\n"
    "))\n",
    "$(eval $(call gb_StaticLibrary_add_exception_objects,unoembind, \\\n"
    "    static/source/unoembindhelpers/PrimaryBindings \\\n"
    "    static/source/unoembindhelpers/RowLokBridge \\\n"
    "))\n",
    "unoembind bridge object",
)
MK.write_text(text, encoding="utf-8")

print(f"ROW LOK bridge copied to {TARGET.relative_to(ROOT)}")
print("ROW LOK bridge added to whole-archived unoembind static library")
