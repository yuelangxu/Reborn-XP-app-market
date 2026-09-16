#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def replace_once(rel, old, new):
    p = ROOT / rel
    s = p.read_text(encoding='utf-8')
    if old not in s:
        raise SystemExit(f'patch anchor missing in {rel}: {old[:80]!r}')
    p.write_text(s.replace(old, new, 1), encoding='utf-8')

# LOK pixels are premultiplied; Canvas ImageData expects straight RGBA.
replace_once('row-office-thread.js', '''  function normalizeTileToRgba(bytes, mode) {
    if (mode === TILEMODE_RGBA) return bytes;
    if (mode !== TILEMODE_BGRA) throw new Error(`ROW_UNKNOWN_TILE_MODE:${mode}`);
    for (let i = 0; i + 3 < bytes.length; i += 4) {
      const red = bytes[i];
      bytes[i] = bytes[i + 2];
      bytes[i + 2] = red;
    }
    return bytes;
  }
''', '''  // LibreOfficeKit tile buffers are premultiplied-alpha pixels. Canvas ImageData
  // expects unpremultiplied RGBA. This follows LibreOffice Online/tilebench.
  function normalizeTileToRgba(bytes, mode) {
    if (mode !== TILEMODE_RGBA && mode !== TILEMODE_BGRA) {
      throw new Error(`ROW_UNKNOWN_TILE_MODE:${mode}`);
    }
    const straight = (value, alpha) => Math.min(255, Math.floor((value * 255 + alpha / 2) / alpha));
    for (let i = 0; i + 3 < bytes.length; i += 4) {
      const c0 = bytes[i], c1 = bytes[i + 1], c2 = bytes[i + 2], alpha = bytes[i + 3];
      if (alpha === 0) {
        bytes[i] = bytes[i + 1] = bytes[i + 2] = bytes[i + 3] = 0;
        continue;
      }
      if (mode === TILEMODE_BGRA) {
        bytes[i] = straight(c2, alpha);
        bytes[i + 1] = straight(c1, alpha);
        bytes[i + 2] = straight(c0, alpha);
      } else {
        bytes[i] = straight(c0, alpha);
        bytes[i + 1] = straight(c1, alpha);
        bytes[i + 2] = straight(c2, alpha);
      }
      bytes[i + 3] = alpha;
    }
    return bytes;
  }
''')

replace_once('row-office-thread.js', '''  function lokUno(payload) {
''', '''  function lokTextSelection(payload) {
    assertLok();
    lokDoc.setTextSelection(
      Number(payload.type || 0) | 0,
      Number(payload.xTwips || 0) | 0,
      Number(payload.yTwips || 0) | 0);
    return {ok: true};
  }

  function lokUno(payload) {
''')
replace_once('row-office-thread.js', "      case 'lok-mouse': return lokMouse(payload);\n", "      case 'lok-mouse': return lokMouse(payload);\n      case 'lok-text-selection': return lokTextSelection(payload);\n")

replace_once('row-office-client.js', '''    postUnoCommand(command, args = '', notifyWhenFinished = false) {
''', '''    setLokTextSelection(type, xTwips, yTwips) {
      return this.request('lok-text-selection', {type, xTwips, yTwips});
    }

    postUnoCommand(command, args = '', notifyWhenFinished = false) {
''')

replace_once('row-office-view.js', "  const LOK_MOUSEEVENT_MOUSEMOVE = 2;\n", "  const LOK_MOUSEEVENT_MOUSEMOVE = 2;\n  const LOK_SETTEXTSELECTION_RESET = 2;\n")

replace_once('row-office-view.js', '''      Object.assign(this.ime.style, {
        position: 'absolute',
        width: '4px',
        height: '20px',
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
        pointerEvents: 'none'
      });

      this.overlayLayer.appendChild(this.selectionLayer);
      this.overlayLayer.appendChild(this.cursor);
      this.overlayLayer.appendChild(this.ime);
      this.documentLayer.appendChild(this.pageLayer);
      this.documentLayer.appendChild(this.tileLayer);
      this.documentLayer.appendChild(this.overlayLayer);
''', '''      Object.assign(this.ime.style, {
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
''')

replace_once('row-office-view.js', '''      this.surface.addEventListener('scroll', this.onScroll, {passive: true});
      this.documentLayer.addEventListener('pointerdown', this.onPointerDown);
      this.documentLayer.addEventListener('pointermove', this.onPointerMove);
      this.documentLayer.addEventListener('pointerup', this.onPointerUp);
      this.documentLayer.addEventListener('pointercancel', this.onPointerUp);
''', '''      this.surface.addEventListener('scroll', this.onScroll, {passive: true});
      // Capture before the Reborn XP window manager can stop propagation.
      window.addEventListener('pointerdown', this.onPointerDown, true);
      window.addEventListener('pointermove', this.onPointerMove, true);
      window.addEventListener('pointerup', this.onPointerUp, true);
      window.addEventListener('pointercancel', this.onPointerUp, true);
''')
replace_once('row-office-view.js', '''      this.onDocumentKeyDownCapture = (event) => {
        if (!this.active || this.destroyed || event.target === this.ime) return;
        if (isEditableTarget(event.target)) return;
        this._keyDown(event, false);
      };
''', '''      this.onDocumentKeyDownCapture = (event) => {
        if (!this.active || this.destroyed) return;
        if (event.target !== this.ime && isEditableTarget(event.target)) return;
        this._keyDown(event, event.target === this.ime);
      };
      this.onWindowBeforeInputCapture = (event) => {
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
''')

replace_once('row-office-view.js', '''      this.ime.addEventListener('keydown', this.onImeKeyDown);
      this.ime.addEventListener('beforeinput', this.onImeBeforeInput);
      this.ime.addEventListener('input', this.onImeInput);
      this.ime.addEventListener('compositionstart', this.onCompositionStart);
      this.ime.addEventListener('compositionend', this.onCompositionEnd);
      this.ime.addEventListener('blur', this.onImeBlur);
''', '''      // Input is captured at window level so host document handlers cannot
      // swallow keyboard/IME events before they reach the hidden editor.
      this.ime.addEventListener('blur', this.onImeBlur);
      window.addEventListener('beforeinput', this.onWindowBeforeInputCapture, true);
      window.addEventListener('input', this.onWindowInputCapture, true);
      window.addEventListener('compositionstart', this.onWindowCompositionStartCapture, true);
      window.addEventListener('compositionend', this.onWindowCompositionEndCapture, true);
''')

replace_once('row-office-view.js', "      document.addEventListener('keydown', this.onDocumentKeyDownCapture, true);\n", "      window.addEventListener('keydown', this.onDocumentKeyDownCapture, true);\n")

replace_once('row-office-view.js', '''        ctx.clearRect(0, 0, result.canvasWidth, result.canvasHeight);
        ctx.putImageData(image, 0, 0);
''', '''        ctx.clearRect(0, 0, result.canvasWidth, result.canvasHeight);
        ctx.putImageData(image, 0, 0);

        // The LOK document bounds include gutters outside the physical Writer
        // pages. Clip every tile to pageRectangles so stale/premultiplied edge
        // pixels cannot leak through the browser compositor.
        const pages = parseRectList(this.info && this.info.pageRectangles);
        if (pages.length) {
          const tx = result.xTwips, ty = result.yTwips;
          const tw = result.widthTwips, th = result.heightTwips;
          const sx = result.canvasWidth / tw, sy = result.canvasHeight / th;
          ctx.globalCompositeOperation = 'destination-in';
          ctx.fillStyle = '#fff';
          for (const page of pages) {
            const left = Math.max(tx, page.x);
            const top = Math.max(ty, page.y);
            const right = Math.min(tx + tw, page.x + page.width);
            const bottom = Math.min(ty + th, page.y + page.height);
            if (right <= left || bottom <= top) continue;
            const px = Math.floor((left - tx) * sx);
            const py = Math.floor((top - ty) * sy);
            const pr = Math.ceil((right - tx) * sx);
            const pb = Math.ceil((bottom - ty) * sy);
            ctx.fillRect(px, py, Math.max(1, pr - px), Math.max(1, pb - py));
          }
          ctx.globalCompositeOperation = 'source-over';
        }
''')

replace_once('row-office-view.js', '''      Object.assign(this.ime.style, {
        left: `${x}px`,
        top: `${y}px`,
        height: `${height}px`
      });
''', '')

replace_once('row-office-view.js', '''        if (event.button === 0) return 1;
        if (event.button === 1) return 4;
        if (event.button === 2) return 2;
''', '''        if (event.button === 0) return 1;
        if (event.button === 1) return 2;
        if (event.button === 2) return 4;
''')
replace_once('row-office-view.js', '''      if (event.buttons & 1) value |= 1;
      if (event.buttons & 2) value |= 2;
      if (event.buttons & 4) value |= 4;
''', '''      if (event.buttons & 1) value |= 1;
      if (event.buttons & 2) value |= 4;
      if (event.buttons & 4) value |= 2;
''')

replace_once('row-office-view.js', '''      if (type === LOK_MOUSEEVENT_MOUSEBUTTONDOWN) {
        this.mouseDown = true;
        this._activateInput();
        try { this.documentLayer.setPointerCapture(event.pointerId); } catch (_) {}
''', '''      if (type === LOK_MOUSEEVENT_MOUSEBUTTONDOWN) {
        this.mouseDown = true;
        this._activateInput();
        if (event.button === 0) {
          // Writer postMouseEvent is async; in single-thread WASM it does not
          // reliably place a caret. RESET is the synchronous Writer
          // SetCursorTwipPosition path.
          this.cursorRect = {x: point.xTwips, y: point.yTwips, width: 15, height: 300};
          this.cursorVisible = true;
          this._renderCursor();
          this.client.setLokTextSelection(
            LOK_SETTEXTSELECTION_RESET, point.xTwips, point.yTwips
          ).then(() => this._scheduleVisible(true))
            .catch((error) => console.error('[ROW caret]', error));
        }
        try { this.documentLayer.setPointerCapture(event.pointerId); } catch (_) {}
''')

replace_once('row-office-view.js', '''      this.surface.removeEventListener('scroll', this.onScroll);
      this.documentLayer.removeEventListener('pointerdown', this.onPointerDown);
      this.documentLayer.removeEventListener('pointermove', this.onPointerMove);
      this.documentLayer.removeEventListener('pointerup', this.onPointerUp);
      this.documentLayer.removeEventListener('pointercancel', this.onPointerUp);
''', '''      this.surface.removeEventListener('scroll', this.onScroll);
      window.removeEventListener('pointerdown', this.onPointerDown, true);
      window.removeEventListener('pointermove', this.onPointerMove, true);
      window.removeEventListener('pointerup', this.onPointerUp, true);
      window.removeEventListener('pointercancel', this.onPointerUp, true);
''')
replace_once('row-office-view.js', '''      this.ime.removeEventListener('keydown', this.onImeKeyDown);
      this.ime.removeEventListener('beforeinput', this.onImeBeforeInput);
      this.ime.removeEventListener('input', this.onImeInput);
      this.ime.removeEventListener('compositionstart', this.onCompositionStart);
      this.ime.removeEventListener('compositionend', this.onCompositionEnd);
      this.ime.removeEventListener('blur', this.onImeBlur);
''', '''      this.ime.removeEventListener('blur', this.onImeBlur);
      window.removeEventListener('beforeinput', this.onWindowBeforeInputCapture, true);
      window.removeEventListener('input', this.onWindowInputCapture, true);
      window.removeEventListener('compositionstart', this.onWindowCompositionStartCapture, true);
      window.removeEventListener('compositionend', this.onWindowCompositionEndCapture, true);
''')
replace_once('row-office-view.js', "      document.removeEventListener('keydown', this.onDocumentKeyDownCapture, true);\n", "      window.removeEventListener('keydown', this.onDocumentKeyDownCapture, true);\n")

# Replace the intentionally failing async-mouse probe with the synchronous Writer
# cursor placement gate. The DOM click gate later in the file still verifies the
# actual view produces a visible caret.
replace_once('acceptance.html', '''    // Direct LOK mouse probe. This bypasses Reborn's DOM/window manager and tells
    // us whether the LibreOffice mouse path itself can place a Writer caret.
    await client.newWriter();
    let mouseCursorPayload = '';
    const offMouseProbe = client.on('lok-callback', (message) => {
      if (Number(message.callbackType) === 1 && String(message.payload || '').trim()
          && String(message.payload || '').trim() !== 'EMPTY') {
        mouseCursorPayload = String(message.payload);
      }
    });
    await client.postLokMouse(0, 1800, 1800, 1, 1, 0);
    await client.postLokMouse(1, 1800, 1800, 1, 1, 0);
    await waitFor(() => mouseCursorPayload, 'Direct LOK mouse click did not produce a visible cursor callback', 4000);
    offMouseProbe();
    record('lok-mouse-caret', {payload: mouseCursorPayload});
''', '''    // Writer postMouseEvent is asynchronous and is known not to place a caret
    // in this single-thread Emscripten runtime. Verify that synchronous Writer
    // setTextSelection(RESET) actually moves the insertion point, not just that
    // the API call returns.
    await client.newWriter();
    await client.postTextInput('ABCD');
    assert((await client.readText()).text === 'ABCD', 'Caret-position fixture text mismatch');
    await client.setLokTextSelection(2, 1450, 1450);
    await client.postTextInput('X');
    const syncCaretText = (await client.readText()).text;
    assert(syncCaretText.includes('X'), 'Text input after synchronous LOK caret placement did not reach Writer');
    assert(syncCaretText !== 'ABCDX', 'Synchronous LOK cursor placement did not move the insertion point');
    record('lok-sync-caret', {text: syncCaretText});
''')

replace_once('acceptance.html', '''    // DOM mouse probe: actual pointerdown/up must make the view display a caret.
    view.cursorRect = null;
    view._renderCursor();
    const docRect = view.documentLayer.getBoundingClientRect();
    const page = view.pageLayer.firstElementChild.getBoundingClientRect();
    const clickX = Math.max(page.left + 80, docRect.left + 40);
    const clickY = Math.max(page.top + 80, docRect.top + 40);
    view.documentLayer.dispatchEvent(new PointerEvent('pointerdown', {
      pointerId: 1, pointerType: 'mouse', button: 0, buttons: 1,
      clientX: clickX, clientY: clickY, bubbles: true, cancelable: true
    }));
    view.documentLayer.dispatchEvent(new PointerEvent('pointerup', {
      pointerId: 1, pointerType: 'mouse', button: 0, buttons: 0,
      clientX: clickX, clientY: clickY, bubbles: true, cancelable: true
    }));
    await waitFor(() => view.cursorRect, 'DOM pointer click did not produce a Writer caret callback', 4000);
    record('dom-mouse-caret', {cursorRect: view.cursorRect});
''', '''    // DOM mouse probe under a hostile host: document-capture listeners swallow
    // the events, so only our earlier window-capture path can see them.
    view.cursorRect = null;
    view._renderCursor();
    const docRect = view.documentLayer.getBoundingClientRect();
    const page = view.pageLayer.firstElementChild.getBoundingClientRect();
    const clickX = Math.max(page.left + 80, docRect.left + 40);
    const clickY = Math.max(page.top + 80, docRect.top + 40);
    const swallow = (event) => event.stopImmediatePropagation();
    for (const type of ['pointerdown', 'pointerup', 'keydown', 'beforeinput']) {
      document.addEventListener(type, swallow, true);
    }
    view.ime.dispatchEvent(new PointerEvent('pointerdown', {
      pointerId: 1, pointerType: 'mouse', button: 0, buttons: 1,
      clientX: clickX, clientY: clickY, bubbles: true, cancelable: true
    }));
    view.ime.dispatchEvent(new PointerEvent('pointerup', {
      pointerId: 1, pointerType: 'mouse', button: 0, buttons: 0,
      clientX: clickX, clientY: clickY, bubbles: true, cancelable: true
    }));
    await waitFor(() => view.cursorRect && getComputedStyle(view.cursor).display !== 'none',
      'DOM pointer click did not display a Writer caret', 4000);
    view.ime.dispatchEvent(new InputEvent('beforeinput', {
      inputType: 'insertText', data: 'K', bubbles: true, cancelable: true
    }));
    const clickedText = await waitFor(async () => {
      const value = await client.readText();
      return value.text.includes('K') ? value.text : '';
    }, 'Text typed after DOM pointer click did not reach Writer');
    for (const type of ['pointerdown', 'pointerup', 'keydown', 'beforeinput']) {
      document.removeEventListener(type, swallow, true);
    }
    record('dom-mouse-caret', {cursorRect: view.cursorRect, text: clickedText});
''')

print('applied ROW input/render fix v2')
