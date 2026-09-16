#!/usr/bin/env python3
from pathlib import Path
import subprocess
import sys

PIN = "31eabe1e534a70a2b7d5c39eb31e56a75c17be3b"
root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
if head != PIN:
    raise SystemExit(f"Refusing to patch unexpected LibreOffice commit: {head} != {PIN}")

path = root / "vcl/headless/svpinst.cxx"
text = path.read_text(encoding="utf-8")
anchor = """bool SvpSalInstance::ImplYield(bool bWait, bool bHandleAllCurrentEvents)
{
    DBG_TESTSVPYIELDMUTEX();
    DBG_TESTSOLARMUTEX();
    assert(IsMainThread());
"""
replacement = anchor + """
#if defined __EMSCRIPTEN__ && defined ROW_EMSCRIPTEN_SINGLE_THREAD
    // The Emscripten system loop already calls us again from the browser task
    // loop.  In a true one-thread build there is no second thread that can wake
    // m_WakeUpMainCond, so bWait=true can permanently block the DedicatedWorker
    // and starve postMessage/setInterval.  Never sleep inside the sole runtime
    // thread; process currently-ready VCL work and return to the browser.
    bWait = false;
#endif
"""
count = text.count(anchor)
if count != 1:
    raise SystemExit(f"single-thread yield anchor count={count}, expected 1")
text = text.replace(anchor, replacement, 1)
path.write_text(text, encoding="utf-8")

# Contract checks make accidental drift fail before the expensive build.
patched = path.read_text(encoding="utf-8")
required = [
    "ROW_EMSCRIPTEN_SINGLE_THREAD",
    "bWait = false;",
    "m_WakeUpMainCond.wait(g,",
]
for needle in required:
    if needle not in patched:
        raise SystemExit(f"missing yield patch contract: {needle}")
print("[ROW] patched single-thread Emscripten ImplYield to remain non-blocking")
