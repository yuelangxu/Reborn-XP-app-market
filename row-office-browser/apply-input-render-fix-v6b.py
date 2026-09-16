#!/usr/bin/env python3
from pathlib import Path

p = Path(__file__).resolve().parent / 'row-office-view.js'
s = p.read_text(encoding='utf-8')
bad = "this.debugHud.textContent = lines.join('\n');"
good = "this.debugHud.textContent = lines.join(String.fromCharCode(10));"
if bad not in s:
    raise SystemExit('v6b repair anchor missing')
p.write_text(s.replace(bad, good, 1), encoding='utf-8')
print('repaired ROW v6 diagnostic HUD newline emission')
