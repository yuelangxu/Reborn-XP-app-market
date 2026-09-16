#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def replace_once(rel, old, new):
    p = ROOT / rel
    s = p.read_text(encoding='utf-8')
    if old not in s:
        raise SystemExit(f'v5 patch anchor missing in {rel}: {old[:120]!r}')
    p.write_text(s.replace(old, new, 1), encoding='utf-8')

# Serialize committed text. Real typing can generate browser input events faster
# than the worker/UNO bridge completes, and the visible Writer cursor must advance
# in exactly the same order as the native textarea commits.
replace_once('row-office-view.js',
"      this.focusWatchdog = 0;\n",
"      this.focusWatchdog = 0;\n      this.inputQueue = Promise.resolve();\n")

replace_once('row-office-view.js', '''    _postText(text) {
      const value = String(text || '');
      if (!value) return Promise.resolve();
      return this.client.postTextInput(value)
        .then(() => this._scheduleVisible(true));
    }
''', '''    _postText(text) {
      const value = String(text || '');
      if (!value) return Promise.resolve();
      const send = () => this.client.postTextInput(value)
        .then(() => {
          this._scheduleVisible(true);
          this._ensureInputFocus();
        });
      const pending = this.inputQueue.then(send, send);
      // Keep the queue alive after an individual failure while still returning
      // the real rejection to the caller that submitted this commit.
      this.inputQueue = pending.catch(() => undefined);
      return pending;
    }
''')

# Printable keys received by the *real textarea* must be left to the browser's
# native text input pipeline. The parent-window fallback can still synthesize
# committed text from keydown when Reborn owns focus outside the iframe.
replace_once('row-office-view.js',
"      if (key.length === 1 && (!event.altKey || altGraph)\n",
"      if (!fromIme && key.length === 1 && (!event.altKey || altGraph)\n")

# Do not cancel native insertText beforeinput. Let Chromium update the textarea,
# then consume the committed value from the ensuing input event. This is the
# standard path used by physical keyboards and Windows/macOS/Linux IMEs.
replace_once('row-office-view.js', '''      if ((event.inputType === 'insertText' || event.inputType === 'insertReplacementText')
          && event.data) {
        if (this.compositionCommit && event.data === this.compositionCommit) {
          this.compositionCommit = '';
          event.preventDefault();
          this.ime.value = '';
          return;
        }
        event.preventDefault();
        this.ime.value = '';
        this._postText(event.data)
          .catch((error) => console.error('[ROW beforeinput]', error));
        return;
      }
''', '''      if ((event.inputType === 'insertText' || event.inputType === 'insertReplacementText')
          && event.data) {
        // Intentionally do not preventDefault(): the browser owns the native
        // textarea edit. _inputFallback() consumes the resulting value once.
        return;
      }
''')

replace_once('row-office-view.js', '''    _inputFallback() {
      if (this.composing || this.destroyed) return;
      const text = String(this.ime.value || '');
      this.ime.value = '';
      if (!text) return;
      if (this.compositionCommit && text === this.compositionCommit) {
        this.compositionCommit = '';
        return;
      }
      this._postText(text)
        .catch((error) => console.error('[ROW input fallback]', error));
    }
''', '''    _inputFallback() {
      if (this.composing || this.destroyed) return;
      const text = String(this.ime.value || '');
      if (!text) return;
      this.ime.value = '';
      this._postText(text)
        .catch((error) => console.error('[ROW input fallback]', error));
    }
''')

# compositionend can be followed by the final native input event. Clearing the
# textarea inside compositionend can break the platform IME after its first
# commit. Defer consumption one task; if input already consumed it, this is a no-op.
replace_once('row-office-view.js', '''    _compositionEnd(event) {
      this.composing = false;
      const text = String(event.data || '');
      this.ime.value = '';
      if (!text) return;
      this.compositionCommit = text;
      setTimeout(() => {
        if (this.compositionCommit === text) this.compositionCommit = '';
      }, 120);
      this._postText(text)
        .catch((error) => console.error('[ROW IME]', error));
    }
''', '''    _compositionEnd() {
      this.composing = false;
      setTimeout(() => this._inputFallback(), 0);
    }
''')

# v5 acceptance exercises the native textarea input lifecycle rather than
# dispatching printable text from keydown.
(ROOT / 'acceptance.html').write_text((ROOT / 'acceptance-v5.html').read_text(encoding='utf-8'), encoding='utf-8')
print('applied ROW input/render fix v5')
