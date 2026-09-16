#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def replace_once(rel, old, new):
    p = ROOT / rel
    s = p.read_text(encoding='utf-8')
    if old not in s:
        raise SystemExit(f'v8 patch anchor missing in {rel}: {old[:180]!r}')
    p.write_text(s.replace(old, new, 1), encoding='utf-8')

# There must be exactly one serialization layer for interactive RPCs: the
# worker-side requestQueue. A second UI Promise queue can stall while unrelated
# worker RPCs are still alive, which is exactly what the Reborn HUD exposed.
replace_once('row-office-view.js',
"      this.inputQueue = Promise.resolve();\n",
"")

old = '''    _postText(text) {
      const value = String(text || '');
      if (!value) return Promise.resolve();
      this.debugState.commitsQueued += 1;
      this._debug('commit-queued');
      const send = () => this.client.postTextInput(value)
        .then(() => {
          this.debugState.commitsOk += 1;
          this.deferInitialTiles = false;
          this.renderHoldUntil = Math.max(this.renderHoldUntil, performance.now() + 160);
          this._debug('commit-ok');
          this._scheduleVisible(true);
          this._ensureInputFocus();
        }, (error) => {
          this.debugState.commitsError += 1;
          this.debugState.lastError = String(error && error.message ? error.message : error);
          this._debug('commit-error');
          throw error;
        });
      const pending = this.inputQueue.then(send, send);
      // Keep the queue alive after an individual failure while still returning
      // the real rejection to the caller that submitted this commit.
      this.inputQueue = pending.catch(() => undefined);
      return pending;
    }
'''
new = '''    _postText(text) {
      const value = String(text || '');
      if (!value) return Promise.resolve();
      this.debugState.commitsQueued += 1;
      this._debug('commit-posted');
      // postMessage ordering + the worker's requestQueue are the only ordering
      // mechanism. Do not add a second UI-side Promise queue.
      return this.client.postTextInput(value)
        .then(() => {
          this.debugState.commitsOk += 1;
          this.deferInitialTiles = false;
          this.renderHoldUntil = Math.max(this.renderHoldUntil, performance.now() + 160);
          this._debug('commit-ok');
          this._scheduleVisible(true);
        }, (error) => {
          this.debugState.commitsError += 1;
          this.debugState.lastError = String(error && error.message ? error.message : error);
          this._debug('commit-error');
          throw error;
        });
    }
'''
replace_once('row-office-view.js', old, new)

# Never steal focus continuously from the Reborn XP desktop. Writer gets focus
# only from an explicit Writer-page interaction or an explicit app command.
replace_once('row-office-view.js', '''    async mount() {
      await this.reloadDocument();
      this.focus();
      if (!this.focusWatchdog) {
        this.focusWatchdog = setInterval(() => {
          if (this.active && !this.destroyed) this._ensureInputFocus();
        }, 120);
      }
      if (!this.debugTimer) {
''', '''    async mount() {
      await this.reloadDocument();
      this.focus();
      if (!this.debugTimer) {
''')

# A blur means the host/user moved focus. Respect it. The next explicit click on
# Writer will activate the input frame again.
replace_once('row-office-view.js', '''      this.onImeBlur = () => {
        this.debugState.imeBlur += 1;
        this._debug('ime-blur');
        if (!this.active || this.destroyed) return;
        clearTimeout(this.refocusTimer);
        this.refocusTimer = setTimeout(() => this._ensureInputFocus(), 0);
      };
''', '''      this.onImeBlur = () => {
        this.debugState.imeBlur += 1;
        this.active = false;
        clearTimeout(this.refocusTimer);
        clearTimeout(this.refocusTimer2);
        this._debug('ime-blur');
      };
''')

# Clicking anywhere outside the Writer page immediately cancels delayed focus
# grabs. This is crucial for Reborn's own close/minimize/buttons and other apps.
replace_once('row-office-view.js', '''      this.onDocumentPointerDownCapture = (event) => {
        if (!this.surface.contains(event.target)) this.active = false;
      };
''', '''      this.onDocumentPointerDownCapture = (event) => {
        if (!this.surface.contains(event.target)) {
          this.active = false;
          clearTimeout(this.refocusTimer);
          clearTimeout(this.refocusTimer2);
        }
      };
''')

# Browser/tab focus returning must not automatically reactivate Writer.
replace_once('row-office-view.js', '''      this.onWindowFocus = () => {
        if (this.active) this._ensureInputFocus();
        this._scheduleVisible(true);
      };
''', '''      this.onWindowFocus = () => {
        this._scheduleVisible(true);
      };
''')
replace_once('row-office-view.js', '''      this.onVisibilityChange = () => {
        if (!document.hidden) {
          if (this.active) this._ensureInputFocus();
          this._scheduleVisible(true);
        }
      };
''', '''      this.onVisibilityChange = () => {
        if (!document.hidden) this._scheduleVisible(true);
      };
''')

# Focusing the textarea is sufficient to focus its iframe. Avoid a separate
# contentWindow.focus(), which is an unnecessary host-level focus operation.
replace_once('row-office-view.js', '''      if (!frameActive || !innerActive) {
        this.ime.value = '';
        try { this.inputWindow.focus(); } catch (_) {}
        safeFocus(this.ime);
      }
''', '''      if (!frameActive || !innerActive) {
        this.ime.value = '';
        safeFocus(this.ime);
      }
''')

# Pointer capture is hostile to a DOM desktop/window manager if pointerup is
# transformed or consumed by host chrome. Basic Writer editing doesn't need it.
replace_once('row-office-view.js',
"        try { this.documentLayer.setPointerCapture(event.pointerId); } catch (_) {}\n",
"")
replace_once('row-office-view.js',
"        try { this.documentLayer.releasePointerCapture(event.pointerId); } catch (_) {}\n",
"")

# Remove now-unused watchdog cleanup if present.
replace_once('row-office-view.js', '''      if (this.focusWatchdog) {
        clearInterval(this.focusWatchdog);
        this.focusWatchdog = 0;
      }
''', '')

print('applied ROW input/render fix v8 host-safe input dispatch')
