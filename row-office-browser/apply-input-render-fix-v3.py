#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def replace_once(rel, old, new):
    p = ROOT / rel
    s = p.read_text(encoding='utf-8')
    if old not in s:
        raise SystemExit(f'v3 patch anchor missing in {rel}: {old[:100]!r}')
    p.write_text(s.replace(old, new, 1), encoding='utf-8')

replace_once('row-office-view.js',
"      this.refocusTimer = 0;\n",
"      this.refocusTimer = 0;\n      this.refocusTimer2 = 0;\n      this.inputFrame = null;\n      this.inputWindow = null;\n")

replace_once('row-office-view.js', '''      // A real editable control is needed for composition/IME. Reborn XP may
      // move focus to its own window chrome after pointer bubbling, so a second
      // document-level keyboard path recovers ordinary typing when that happens.
      this.ime = document.createElement('textarea');
      this.ime.setAttribute('aria-label', 'Writer text input');
      this.ime.autocomplete = 'off';
      this.ime.autocapitalize = 'off';
      this.ime.spellcheck = false;
      this.ime.tabIndex = -1;
      Object.assign(this.ime.style, {
        position: 'absolute',
        inset: '0',
        width: '100%',
        height: '100%',
        opacity: '0',
        border: '0',
        outline: '0',
        padding: '0',
        margin: '0',
        resize: 'none',
        overflow: 'hidden',
        color: 'transparent',
        background: 'transparent',
        caretColor: 'transparent',
        fontSize: '16px',
        zIndex: '50',
        pointerEvents: 'auto',
        cursor: 'text'
      });

      this.overlayLayer.appendChild(this.selectionLayer);
      this.overlayLayer.appendChild(this.cursor);
      this.documentLayer.appendChild(this.pageLayer);
      this.documentLayer.appendChild(this.tileLayer);
      this.documentLayer.appendChild(this.overlayLayer);
      this.documentLayer.appendChild(this.ime);
      this.stage.appendChild(this.documentLayer);
      this.surface.appendChild(this.stage);
''', '''      // Put the browser text control in its own browsing context. Key/IME
      // events in this frame never propagate through Reborn XP's parent window.
      this.inputFrame = document.createElement('iframe');
      this.inputFrame.className = 'row-office-input-frame';
      this.inputFrame.title = 'Writer keyboard input';
      this.inputFrame.tabIndex = -1;
      this.inputFrame.src = 'about:blank';
      Object.assign(this.inputFrame.style, {
        position: 'absolute', left: '0', top: '0', width: '6px', height: '24px',
        opacity: '0', border: '0', outline: '0', padding: '0', margin: '0',
        zIndex: '50', pointerEvents: 'none'
      });

      this.overlayLayer.appendChild(this.selectionLayer);
      this.overlayLayer.appendChild(this.cursor);
      this.documentLayer.appendChild(this.pageLayer);
      this.documentLayer.appendChild(this.tileLayer);
      this.documentLayer.appendChild(this.overlayLayer);
      this.documentLayer.appendChild(this.inputFrame);
      this.stage.appendChild(this.documentLayer);
      this.surface.appendChild(this.stage);
      this._initializeInputFrame();
''')

replace_once('row-office-view.js', '''    _bindEvents() {
''', '''    _initializeInputFrame() {
      const doc = this.inputFrame && this.inputFrame.contentDocument;
      if (!doc) throw new Error('ROW_INPUT_FRAME_UNAVAILABLE');
      doc.open();
      doc.write('<!doctype html><meta charset="utf-8"><style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent}textarea{position:absolute;inset:0;width:100%;height:100%;box-sizing:border-box;border:0;outline:0;padding:0;margin:0;resize:none;overflow:hidden;background:transparent;color:transparent;caret-color:transparent;font:16px sans-serif}</style><textarea id="row-office-ime" aria-label="Writer text input" autocomplete="off" autocapitalize="off" spellcheck="false"></textarea>');
      doc.close();
      this.inputWindow = this.inputFrame.contentWindow;
      this.ime = doc.getElementById('row-office-ime');
      if (!this.inputWindow || !this.ime) throw new Error('ROW_INPUT_FRAME_INIT_FAILED');
    }

    _pageRectsTwips() {
      if (!this.info) return [];
      const pages = parseRectList(this.info.pageRectangles);
      return pages.length ? pages : [{x:0,y:0,width:this.info.widthTwips,height:this.info.heightTwips}];
    }

    _pageAtTwips(x, y) {
      return this._pageRectsTwips().find((page) =>
        x >= page.x && y >= page.y && x <= page.x + page.width && y <= page.y + page.height) || null;
    }

    _bindEvents() {
''')

replace_once('row-office-view.js', '''      this.onWindowBeforeInputCapture = (event) => {
        if (this.active && !this.destroyed && event.target === this.ime) this._beforeInput(event);
      };
      this.onWindowInputCapture = (event) => {
        if (this.active && !this.destroyed && event.target === this.ime) this._inputFallback();
      };
      this.onWindowCompositionStartCapture = (event) => {
        if (this.active && !this.destroyed && event.target === this.ime) this.onCompositionStart(event);
      };
      this.onWindowCompositionEndCapture = (event) => {
        if (this.active && !this.destroyed && event.target === this.ime) this.onCompositionEnd(event);
      };
''', '''      this.onInputFrameKeyDown = (event) => this._keyDown(event, true);
      this.onInputFrameBeforeInput = (event) => this._beforeInput(event);
      this.onInputFrameInput = () => this._inputFallback();
      this.onInputFrameCompositionStart = (event) => this.onCompositionStart(event);
      this.onInputFrameCompositionEnd = (event) => this.onCompositionEnd(event);
''')

replace_once('row-office-view.js', '''      // Input is captured at window level so host document handlers cannot
      // swallow keyboard/IME events before they reach the hidden editor.
      this.ime.addEventListener('blur', this.onImeBlur);
      window.addEventListener('beforeinput', this.onWindowBeforeInputCapture, true);
      window.addEventListener('input', this.onWindowInputCapture, true);
      window.addEventListener('compositionstart', this.onWindowCompositionStartCapture, true);
      window.addEventListener('compositionend', this.onWindowCompositionEndCapture, true);
''', '''      // Keyboard/IME events stay in the nested frame and never enter the
      // Reborn XP parent event path.
      this.ime.addEventListener('blur', this.onImeBlur);
      this.inputWindow.addEventListener('keydown', this.onInputFrameKeyDown, true);
      this.ime.addEventListener('beforeinput', this.onInputFrameBeforeInput);
      this.ime.addEventListener('input', this.onInputFrameInput);
      this.ime.addEventListener('compositionstart', this.onInputFrameCompositionStart);
      this.ime.addEventListener('compositionend', this.onInputFrameCompositionEnd);
''')

replace_once('row-office-view.js', '''      this.stage = document.createElement('div');
''', '''      if (!document.getElementById('row-office-caret-style')) {
        const style = document.createElement('style');
        style.id = 'row-office-caret-style';
        style.textContent = '@keyframes row-office-caret-blink{0%,49%{opacity:1}50%,100%{opacity:0}}';
        document.head.appendChild(style);
      }

      this.stage = document.createElement('div');
''')

replace_once('row-office-view.js', '''    _renderCursor() {
      const r = this.cursorRect;
      if (!r || !this.cursorVisible || !this.info) {
        this.cursor.style.display = 'none';
        return;
      }
      const x = r.x / this.twipsPerCssPx;
      const y = r.y / this.twipsPerCssPx;
      const width = Math.max(1, r.width / this.twipsPerCssPx);
      const height = Math.max(12, r.height / this.twipsPerCssPx);
      Object.assign(this.cursor.style, {
        display: 'block',
        left: `${x}px`,
        top: `${y}px`,
        width: `${Math.min(width, 2)}px`,
        height: `${height}px`
      });
    }
''', '''    _renderCursor() {
      const r = this.cursorRect;
      if (!r || !this.cursorVisible || !this.info || !this._pageAtTwips(r.x, r.y)) {
        this.cursor.style.display = 'none';
        return;
      }
      const x = r.x / this.twipsPerCssPx;
      const y = r.y / this.twipsPerCssPx;
      const width = Math.max(1, r.width / this.twipsPerCssPx);
      const height = Math.max(12, r.height / this.twipsPerCssPx);
      Object.assign(this.cursor.style, {
        display: 'block', left: `${x}px`, top: `${y}px`,
        width: `${Math.min(width, 2)}px`, height: `${height}px`,
        animation: 'row-office-caret-blink 1s steps(1,end) infinite'
      });
      if (this.inputFrame) Object.assign(this.inputFrame.style, {
        left: `${Math.max(0, x - 2)}px`, top: `${Math.max(0, y)}px`,
        height: `${Math.max(20, height)}px`
      });
    }
''')

replace_once('row-office-view.js', '''    _eventDocPoint(event) {
      const rect = this.documentLayer.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      if (x < 0 || y < 0 || x > this.documentWidthPx || y > this.documentHeightPx) return null;
      return {
        xTwips: Math.round(x * this.twipsPerCssPx),
        yTwips: Math.round(y * this.twipsPerCssPx)
      };
    }
''', '''    _eventDocPoint(event) {
      const rect = this.documentLayer.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      if (x < 0 || y < 0 || x > this.documentWidthPx || y > this.documentHeightPx) return null;
      const xTwips = Math.round(x * this.twipsPerCssPx);
      const yTwips = Math.round(y * this.twipsPerCssPx);
      const page = this._pageAtTwips(xTwips, yTwips);
      if (!page) return null;
      return {
        xTwips: Math.min(Math.max(xTwips, page.x + 1), page.x + page.width - 1),
        yTwips: Math.min(Math.max(yTwips, page.y + 1), page.y + page.height - 1),
        page
      };
    }
''')

replace_once('row-office-view.js', '''    _activateInput() {
      this.active = true;
      this._ensureInputFocus();
      requestAnimationFrame(() => this._ensureInputFocus());
      clearTimeout(this.refocusTimer);
      this.refocusTimer = setTimeout(() => this._ensureInputFocus(), 0);
    }
''', '''    _activateInput() {
      this.active = true;
      this._ensureInputFocus();
      requestAnimationFrame(() => this._ensureInputFocus());
      clearTimeout(this.refocusTimer);
      clearTimeout(this.refocusTimer2);
      this.refocusTimer = setTimeout(() => this._ensureInputFocus(), 0);
      this.refocusTimer2 = setTimeout(() => this._ensureInputFocus(), 80);
    }
''')

replace_once('row-office-view.js', '''    _ensureInputFocus() {
      if (!this.active || this.destroyed) return;
      if (document.activeElement !== this.ime) {
        this.ime.value = '';
        safeFocus(this.ime);
      }
    }
''', '''    _ensureInputFocus() {
      if (!this.active || this.destroyed || !this.inputWindow || !this.ime) return;
      const frameActive = document.activeElement === this.inputFrame;
      const innerActive = this.inputFrame.contentDocument && this.inputFrame.contentDocument.activeElement === this.ime;
      if (!frameActive || !innerActive) {
        this.ime.value = '';
        try { this.inputWindow.focus(); } catch (_) {}
        safeFocus(this.ime);
      }
    }
''')

replace_once('row-office-view.js',
"      if (!fromIme && key.length === 1 && (!event.altKey || altGraph)\n",
"      if (key.length === 1 && (!event.altKey || altGraph)\n")

replace_once('row-office-view.js', '''      clearTimeout(this.refocusTimer);
      this.renderEpoch += 1;
''', '''      clearTimeout(this.refocusTimer);
      clearTimeout(this.refocusTimer2);
      this.renderEpoch += 1;
''')

replace_once('row-office-view.js', '''      this.ime.removeEventListener('blur', this.onImeBlur);
      window.removeEventListener('beforeinput', this.onWindowBeforeInputCapture, true);
      window.removeEventListener('input', this.onWindowInputCapture, true);
      window.removeEventListener('compositionstart', this.onWindowCompositionStartCapture, true);
      window.removeEventListener('compositionend', this.onWindowCompositionEndCapture, true);
''', '''      this.ime.removeEventListener('blur', this.onImeBlur);
      if (this.inputWindow) this.inputWindow.removeEventListener('keydown', this.onInputFrameKeyDown, true);
      this.ime.removeEventListener('beforeinput', this.onInputFrameBeforeInput);
      this.ime.removeEventListener('input', this.onInputFrameInput);
      this.ime.removeEventListener('compositionstart', this.onInputFrameCompositionStart);
      this.ime.removeEventListener('compositionend', this.onInputFrameCompositionEnd);
''')

(ROOT / 'acceptance.html').write_text((ROOT / 'acceptance-v3.html').read_text(encoding='utf-8'), encoding='utf-8')
print('applied ROW input/render fix v3')
