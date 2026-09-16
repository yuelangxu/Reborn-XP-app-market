#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def replace_once(rel, old, new):
    p = ROOT / rel
    s = p.read_text(encoding='utf-8')
    if old not in s:
        raise SystemExit(f'v6 patch anchor missing in {rel}: {old[:140]!r}')
    p.write_text(s.replace(old, new, 1), encoding='utf-8')

# Runtime diagnostic state. Keep it deliberately tiny and observable both from
# screenshots and DevTools. This build is a black-box probe for the real Reborn
# XP host, whose keyboard/focus behavior differs from standalone Chromium.
replace_once('row-office-view.js',
"      this.inputQueue = Promise.resolve();\n",
"""      this.inputQueue = Promise.resolve();
      this.debugState = {
        version: 'v6-host-diag', active: false,
        keydown: 0, beforeinput: 0, input: 0,
        compositionStart: 0, compositionEnd: 0,
        imeFocus: 0, imeBlur: 0, frameFocus: 0, frameBlur: 0,
        parentTrustedKeydown: 0,
        commitsQueued: 0, commitsOk: 0, commitsError: 0,
        writerLength: -1, textareaLength: 0,
        lastEvent: 'init', lastKey: '', lastInputType: '', lastError: ''
      };
      this.debugHud = null;
      this.debugTimer = 0;
      globalThis.ROW_DEBUG_STATE = this.debugState;
""")

replace_once('row-office-view.js',
"""      this.surface.innerHTML = '';
      Object.assign(this.surface.style, {
""",
"""      this.surface.innerHTML = '';
      Object.assign(this.surface.style, {
""")

# Add the HUD after the surface/stage is assembled.
replace_once('row-office-view.js',
"""      this.stage.appendChild(this.documentLayer);
      this.surface.appendChild(this.stage);
      this._initializeInputFrame();
""",
"""      this.stage.appendChild(this.documentLayer);
      this.surface.appendChild(this.stage);
      this._initializeInputFrame();
      this._buildDebugHud();
""")

replace_once('row-office-view.js',
"""    _initializeInputFrame() {
""",
"""    _buildDebugHud() {
      const hud = document.createElement('pre');
      hud.className = 'row-office-debug-hud';
      Object.assign(hud.style, {
        position: 'fixed', right: '6px', bottom: '6px', margin: '0',
        zIndex: '2147483646', minWidth: '250px', maxWidth: '360px',
        padding: '6px 8px', border: '1px solid #222', borderRadius: '2px',
        background: 'rgba(255,255,225,.96)', color: '#111',
        font: '11px/1.25 Consolas,monospace', whiteSpace: 'pre-wrap',
        pointerEvents: 'none', boxShadow: '0 1px 4px rgba(0,0,0,.35)'
      });
      document.body.appendChild(hud);
      this.debugHud = hud;
      this._refreshDebugHud();
    }

    _debug(eventName, extra = {}) {
      if (!this.debugState) return;
      this.debugState.lastEvent = String(eventName || '');
      Object.assign(this.debugState, extra || {});
      this.debugState.active = !!this.active;
      this.debugState.textareaLength = this.ime ? String(this.ime.value || '').length : -1;
      this._refreshDebugHud();
    }

    _refreshDebugHud() {
      const d = this.debugState;
      if (!d || !this.debugHud) return;
      const outer = document.activeElement === this.inputFrame ? 'FRAME' :
        (document.activeElement && document.activeElement.tagName) || 'NONE';
      const inner = this.inputFrame && this.inputFrame.contentDocument &&
        this.inputFrame.contentDocument.activeElement === this.ime ? 'TEXTAREA' :
        (this.inputFrame && this.inputFrame.contentDocument &&
         this.inputFrame.contentDocument.activeElement &&
         this.inputFrame.contentDocument.activeElement.tagName) || 'NONE';
      const docFocus = document.hasFocus ? document.hasFocus() : null;
      const lines = [
        `ROW ${d.version}`,
        `active=${this.active ? 1 : 0} docFocus=${docFocus ? 1 : 0}`,
        `focus outer=${outer} inner=${inner}`,
        `KD=${d.keydown} BI=${d.beforeinput} IN=${d.input} parentKD=${d.parentTrustedKeydown}`,
        `CS=${d.compositionStart} CE=${d.compositionEnd} F=${d.imeFocus}/${d.imeBlur}`,
        `Q=${d.commitsQueued} OK=${d.commitsOk} ERR=${d.commitsError}`,
        `writerLen=${d.writerLength} textareaLen=${d.textareaLength}`,
        `last=${d.lastEvent} key=${JSON.stringify(d.lastKey || '')}`,
        `type=${d.lastInputType || '-'}`,
        d.lastError ? `ERROR=${d.lastError.slice(0, 120)}` : 'ERROR=-'
      ];
      this.debugHud.textContent = lines.join('\n');
    }

    _initializeInputFrame() {
""")

# Record real focus transitions inside the isolated browsing context.
replace_once('row-office-view.js',
"""      if (!this.inputWindow || !this.ime) throw new Error('ROW_INPUT_FRAME_INIT_FAILED');
    }
""",
"""      if (!this.inputWindow || !this.ime) throw new Error('ROW_INPUT_FRAME_INIT_FAILED');
      this.inputWindow.addEventListener('focus', () => {
        this.debugState.frameFocus += 1;
        this._debug('frame-focus');
      });
      this.inputWindow.addEventListener('blur', () => {
        this.debugState.frameBlur += 1;
        this._debug('frame-blur');
      });
      this.ime.addEventListener('focus', () => {
        this.debugState.imeFocus += 1;
        this._debug('ime-focus');
      });
    }
""")

# Instrument the iframe's *real* input events. Synthetic tests still increment
# counters, but the HUD also exposes whether the host is stealing focus.
replace_once('row-office-view.js',
"""      this.onInputFrameKeyDown = (event) => this._keyDown(event, true);
      this.onInputFrameBeforeInput = (event) => this._beforeInput(event);
      this.onInputFrameInput = () => this._inputFallback();
      this.onInputFrameCompositionStart = (event) => this.onCompositionStart(event);
      this.onInputFrameCompositionEnd = (event) => this.onCompositionEnd(event);
""",
"""      this.onInputFrameKeyDown = (event) => {
        this.debugState.keydown += 1;
        this._debug('keydown', {lastKey: String(event.key || '')});
        this._keyDown(event, true);
      };
      this.onInputFrameBeforeInput = (event) => {
        this.debugState.beforeinput += 1;
        this._debug('beforeinput', {lastInputType: String(event.inputType || '')});
        this._beforeInput(event);
      };
      this.onInputFrameInput = (event) => {
        this.debugState.input += 1;
        this._debug('input', {lastInputType: String(event.inputType || '')});
        this._inputFallback();
      };
      this.onInputFrameCompositionStart = (event) => {
        this.debugState.compositionStart += 1;
        this._debug('compositionstart');
        this.onCompositionStart(event);
      };
      this.onInputFrameCompositionEnd = (event) => {
        this.debugState.compositionEnd += 1;
        this._debug('compositionend');
        this.onCompositionEnd(event);
      };
""")

# Parent-window observer: when the iframe loses focus, physical keys may start
# landing back in Reborn XP. Seeing parentKD rise while iframe KD freezes is a
# direct signature of host focus theft.
replace_once('row-office-view.js',
"""      this.onWindowFocus = () => {
""",
"""      this.onParentDebugKeyDown = (event) => {
        if (event.isTrusted) {
          this.debugState.parentTrustedKeydown += 1;
          this._debug('parent-keydown', {lastKey: String(event.key || '')});
        }
      };
      window.addEventListener('keydown', this.onParentDebugKeyDown, true);

      this.onWindowFocus = () => {
""")

# Count iframe blur even if the focus watchdog immediately restores it.
replace_once('row-office-view.js',
"""      this.onImeBlur = () => {
        if (!this.active || this.destroyed) return;
""",
"""      this.onImeBlur = () => {
        this.debugState.imeBlur += 1;
        this._debug('ime-blur');
        if (!this.active || this.destroyed) return;
""")

# Instrument the serialized Writer commit queue and retain the rejection.
replace_once('row-office-view.js',
"""      const send = () => this.client.postTextInput(value)
        .then(() => {
          this._scheduleVisible(true);
          this._ensureInputFocus();
        });
      const pending = this.inputQueue.then(send, send);
""",
"""      this.debugState.commitsQueued += 1;
      this._debug('commit-queued');
      const send = () => this.client.postTextInput(value)
        .then(() => {
          this.debugState.commitsOk += 1;
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
""")

# Poll the model text length at low frequency. If trusted input and commit counts
# rise but writerLen freezes, the fault is past the browser-input boundary.
replace_once('row-office-view.js',
"""      if (!this.focusWatchdog) {
        this.focusWatchdog = setInterval(() => {
          if (this.active && !this.destroyed) this._ensureInputFocus();
        }, 120);
      }
""",
"""      if (!this.focusWatchdog) {
        this.focusWatchdog = setInterval(() => {
          if (this.active && !this.destroyed) this._ensureInputFocus();
        }, 120);
      }
      if (!this.debugTimer) {
        this.debugTimer = setInterval(() => {
          if (this.destroyed) return;
          this._refreshDebugHud();
          this.client.readText().then(({text}) => {
            this.debugState.writerLength = String(text || '').length;
            this._refreshDebugHud();
          }).catch((error) => {
            this.debugState.lastError = `readText: ${String(error && error.message ? error.message : error)}`;
            this._refreshDebugHud();
          });
        }, 500);
      }
""")

# Clean diagnostics up with the view.
replace_once('row-office-view.js',
"""      if (this.focusWatchdog) {
        clearInterval(this.focusWatchdog);
        this.focusWatchdog = 0;
      }
      this.renderEpoch += 1;
""",
"""      if (this.focusWatchdog) {
        clearInterval(this.focusWatchdog);
        this.focusWatchdog = 0;
      }
      if (this.debugTimer) {
        clearInterval(this.debugTimer);
        this.debugTimer = 0;
      }
      if (this.onParentDebugKeyDown) {
        window.removeEventListener('keydown', this.onParentDebugKeyDown, true);
      }
      if (this.debugHud) {
        this.debugHud.remove();
        this.debugHud = null;
      }
      this.renderEpoch += 1;
""")

# Keep v5 acceptance. The HUD is intentionally additive and should not weaken
# any trusted/native gate that already passed.
print('applied ROW input/render fix v6 diagnostics')
