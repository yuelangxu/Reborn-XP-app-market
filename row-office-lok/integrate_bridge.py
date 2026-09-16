#!/usr/bin/env python3
"""Stage the ROW LOK bridge into a pinned LibreOffice checkout.

The real Reborn runtime runs the whole single-thread LibreOffice instance in one
ordinary DedicatedWorker.  Alongside the LOK bridge, make LibreOffice's non-
pthread UNO script loader synchronous for ROW builds so zeta.js and the ROW
thread bridge are present before Module.uno_init is resolved.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
HARNESS = Path(__file__).resolve().parent
BRIDGE = HARNESS / "row_lok_bridge.cxx"
TARGET = ROOT / "static/source/unoembindhelpers/RowLokBridge.cxx"
MK = ROOT / "static/StaticLibrary_unoembind.mk"
UNO_INIT = ROOT / "desktop/source/app/initjsunoscripting.cxx"
YIELD_PATCH = HARNESS.parent / "row-office-port" / "patch_single_thread_yield.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


if not BRIDGE.is_file():
    raise SystemExit(f"Missing staged bridge: {BRIDGE}")
if not MK.is_file():
    raise SystemExit(f"Not a LibreOffice checkout: {ROOT}")
if not YIELD_PATCH.is_file():
    raise SystemExit(f"Missing single-thread yield patcher: {YIELD_PATCH}")

TARGET.write_text(BRIDGE.read_text(encoding="utf-8"), encoding="utf-8")

text = MK.read_text(encoding="utf-8")
text = replace_once(
    text,
    "$(eval $(call gb_StaticLibrary_StaticLibrary,unoembind))\n\n",
    "$(eval $(call gb_StaticLibrary_StaticLibrary,unoembind))\n\n"
    "$(eval $(call gb_StaticLibrary_use_external,unoembind,boost_headers))\n\n"
    "$(eval $(call gb_StaticLibrary_set_include,unoembind,\\\n"
    "    $$(INCLUDE) \\\n"
    "    -I$(SRCDIR)/desktop/inc \\\n"
    "))\n\n",
    "unoembind bridge build dependencies",
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

# In upstream's non-PROXY_TO_PTHREAD path runUnoScriptUrls uses fetch().then(),
# i.e. it returns before the UNO scripts have actually executed.  The ROW patch
# resolves Module.uno_init immediately after runUnoScriptUrls(), which would race
# zeta.js/row-office-thread.js.  Our runtime is deliberately hosted in a classic
# DedicatedWorker, where importScripts() is synchronous, so give ROW builds that
# deterministic branch while leaving upstream's other modes unchanged.
if UNO_INIT.is_file():
    text = UNO_INIT.read_text(encoding="utf-8")
    old = """});
#else
EM_JS(void, runUnoScriptUrls, (emscripten::EM_VAL handle), {
    const urls = Emval.toValue(handle);
"""
    new = """});
#elif defined ROW_EMSCRIPTEN_SINGLE_THREAD
EM_JS(void, runUnoScriptUrls, (emscripten::EM_VAL handle), {
    globalThis.Module = globalThis.Module || Module;
    importScripts.apply(self, Emval.toValue(handle));
});
#else
EM_JS(void, runUnoScriptUrls, (emscripten::EM_VAL handle), {
    const urls = Emval.toValue(handle);
"""
    UNO_INIT.write_text(
        replace_once(text, old, new, "ROW synchronous UNO script loader"),
        encoding="utf-8",
    )

# A DedicatedWorker with exactly one runtime thread must never enter headless
# VCL's condition-variable sleep path: there is no second thread that can wake
# it, and blocking the worker also blocks browser message/timer delivery.
subprocess.run([sys.executable, str(YIELD_PATCH), str(ROOT)], check=True)

print(f"ROW LOK bridge copied to {TARGET.relative_to(ROOT)}")
print("ROW LOK bridge added to whole-archived unoembind static library")
print("ROW LOK bridge declared its Boost header dependency")
if UNO_INIT.is_file():
    print("ROW UNO scripts use synchronous importScripts() in the DedicatedWorker")
print("ROW single-thread headless VCL yield is non-blocking")
