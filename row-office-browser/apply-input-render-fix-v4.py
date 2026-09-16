#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def replace_once(rel, old, new):
    p = ROOT / rel
    s = p.read_text(encoding='utf-8')
    if old not in s:
        raise SystemExit(f'v4 patch anchor missing in {rel}: {old[:120]!r}')
    p.write_text(s.replace(old, new, 1), encoding='utf-8')

# Stop using the VCL ExtTextInput state machine for committed body text.
# Insert synchronously at the visible Writer view cursor instead, then collapse
# that cursor to the end of the inserted text so repeated commits are stable.
replace_once('row-office-thread.js', '''  function lokText(payload) {
    assertLok();
    const text = String(payload.text || '');
    if (text) lokDoc.postTextInput(text);
    return {ok: true};
  }
''', '''  function lokText(payload) {
    assertLok();
    assertReady();
    const text = String(payload.text || '');
    if (!text) return {ok: true};
    if (!xModel) throw new Error('ROW_NO_DOCUMENT');

    const controller = xModel.getCurrentController();
    if (!controller) throw new Error('ROW_NO_CURRENT_CONTROLLER');
    const supplier = controller.queryInterface(
      zetajs.type.interface(css.text.XTextViewCursorSupplier));
    if (!supplier) throw new Error('ROW_NO_TEXT_VIEW_CURSOR_SUPPLIER');
    const viewCursor = supplier.getViewCursor();
    if (!viewCursor) throw new Error('ROW_NO_TEXT_VIEW_CURSOR');
    const xText = viewCursor.getText();
    if (!xText) throw new Error('ROW_VIEW_CURSOR_HAS_NO_TEXT');

    // Absorb a selection exactly as ordinary typing would, then leave the
    // visible cursor collapsed after the inserted string for the next commit.
    xText.insertString(viewCursor, text, true);
    viewCursor.collapseToEnd();
    return {ok: true, text: readText()};
  }
''')

# Keep the nested browsing-context input focused even when the host steals focus
# without delivering a standards-compliant blur event.
replace_once('row-office-view.js',
"      this.inputWindow = null;\n",
"      this.inputWindow = null;\n      this.focusWatchdog = 0;\n")

replace_once('row-office-view.js', '''    async mount() {
      await this.reloadDocument();
      this.focus();
    }
''', '''    async mount() {
      await this.reloadDocument();
      this.focus();
      if (!this.focusWatchdog) {
        this.focusWatchdog = setInterval(() => {
          if (this.active && !this.destroyed) this._ensureInputFocus();
        }, 120);
      }
    }
''')

replace_once('row-office-view.js', '''      clearTimeout(this.refocusTimer2);
      this.renderEpoch += 1;
''', '''      clearTimeout(this.refocusTimer2);
      if (this.focusWatchdog) {
        clearInterval(this.focusWatchdog);
        this.focusWatchdog = 0;
      }
      this.renderEpoch += 1;
''')

# Replace the v3 acceptance with the v4 stress gate at workflow assembly time.
(ROOT / 'acceptance.html').write_text((ROOT / 'acceptance-v4.html').read_text(encoding='utf-8'), encoding='utf-8')
print('applied ROW input/render fix v4')
