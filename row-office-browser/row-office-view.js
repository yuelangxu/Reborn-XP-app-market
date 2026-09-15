/* Reborn Office: virtualized Writer page surface backed by upstream LibreOfficeKit tiles. */
'use strict';

(() => {
  const TWIPS_PER_CSS_PX_AT_100 = 15;
  const TILE_CSS = 512;
  const TILE_BUFFER = 1;
  const DOC_MARGIN = 24;

  const LOK_CALLBACK_INVALIDATE_TILES = 0;
  const LOK_CALLBACK_INVALIDATE_VISIBLE_CURSOR = 1;
  const LOK_CALLBACK_TEXT_SELECTION = 2;
  const LOK_CALLBACK_TEXT_SELECTION_START = 3;
  const LOK_CALLBACK_TEXT_SELECTION_END = 4;
  const LOK_CALLBACK_CURSOR_VISIBLE = 5;
  const LOK_CALLBACK_DOCUMENT_SIZE_CHANGED = 13;

  const LOK_KEYEVENT_KEYINPUT = 0;
  const LOK_KEYEVENT_KEYUP = 1;
  const LOK_MOUSEEVENT_MOUSEBUTTONDOWN = 0;
  const LOK_MOUSEEVENT_MOUSEBUTTONUP = 1;
  const LOK_MOUSEEVENT_MOUSEMOVE = 2;

  const KEY_SHIFT = 0x1000;
  const KEY_MOD1 = 0x2000;
  const KEY_MOD2 = 0x4000;

  const KEY = Object.freeze({
    ArrowDown: 1024,
    ArrowUp: 1025,
    ArrowLeft: 1026,
    ArrowRight: 1027,
    Home: 1028,
    End: 1029,
    PageUp: 1030,
    PageDown: 1031,
    Enter: 1280,
    Escape: 1281,
    Tab: 1282,
    Backspace: 1283,
    Space: 1284,
    Insert: 1285,
    Delete: 1286
  });

  function parseRect(value) {
    const parts = String(value || '').match(/-?\d+/g);
    if (!parts || parts.length < 4) return null;
    return {
      x: Number(parts[0]), y: Number(parts[1]),
      width: Number(parts[2]), height: Number(parts[3])
    };
  }

  function parseCursorPayload(payload) {
    const value = String(payload || '').trim();
    if (!value || value === 'EMPTY') return null;
    if (value.startsWith('{')) {
      try {
        const parsed = JSON.parse(value);
        return parseRect(parsed.rectangle);
      } catch (_) {}
    }
    return parseRect(value);
  }

  function parseRectList(payload) {
    return String(payload || '')
      .split(';')
      .map((part) => parseRect(part))
      .filter(Boolean);
  }

  function intersects(a, b) {
    return a.x < b.x + b.width && a.x + a.width > b.x
      && a.y < b.y + b.height && a.y + a.height > b.y;
  }

  class RowOfficeCanvasView {
    constructor(client, surface, options = {}) {
      if (!client) throw new Error('ROW_VIEW_CLIENT_REQUIRED');
      if (!surface) throw new Error('ROW_VIEW_SURFACE_REQUIRED');
      this.client = client;
      this.surface = surface;
      this.zoom = Number(options.zoom || 1);
      this.tileCss = Number(options.tileCss || TILE_CSS);
      this.renderScale = Math.min(Math.max(window.devicePixelRatio || 1, 1), 1.5);
      this.info = null;
      this.tiles = new Map();
      this.renderEpoch = 0;
      this.framePending = false;
      this.mouseDown = false;
      this.composing = false;
      this.compositionCommit = '';
      this.cursorRect = null;
      this.cursorVisible = true;
      this.selectionRects = [];
      this.destroyed = false;
      this.offCallback = null;
      this.resizeObserver = null;

      this._buildDom();
      this._bindEvents();
    }

    get twipsPerCssPx() {
      return TWIPS_PER_CSS_PX_AT_100 / this.zoom;
    }

    _buildDom() {
      this.surface.innerHTML = '';
      this.surface.style.padding = '0';
      this.surface.style.overflow = 'auto';
      this.surface.style.background = '#808080';
      this.surface.style.outline = 'none';

      this.stage = document.createElement('div');
      this.stage.className = 'row-office-stage';
      Object.assign(this.stage.style, {
        position: 'relative',
        minWidth: '100%',
        minHeight: '100%'
      });

      this.documentLayer = document.createElement('div');
      this.documentLayer.className = 'row-office-document-layer';
      Object.assign(this.documentLayer.style, {
        position: 'absolute',
        background: '#fff',
        boxShadow: '0 0 0 1px #666, 2px 2px 8px rgba(0,0,0,.35)'
      });

      this.tileLayer = document.createElement('div');
      Object.assign(this.tileLayer.style, {
        position: 'absolute', inset: '0', overflow: 'hidden'
      });
      this.overlayLayer = document.createElement('div');
      Object.assign(this.overlayLayer.style, {
        position: 'absolute', inset: '0', pointerEvents: 'none', zIndex: '20'
      });

      this.cursor = document.createElement('div');
      Object.assign(this.cursor.style, {
        position: 'absolute', background: '#111', width: '1px',
        minHeight: '14px', display: 'none', zIndex: '30'
      });

      this.selectionLayer = document.createElement('div');
      Object.assign(this.selectionLayer.style, {
        position: 'absolute', inset: '0', pointerEvents: 'none', zIndex: '25'
      });

      this.ime = document.createElement('textarea');
      this.ime.setAttribute('aria-label', 'Writer text input');
      this.ime.autocomplete = 'off';
      this.ime.autocapitalize = 'off';
      this.ime.spellcheck = false;
      Object.assign(this.ime.style, {
        position: 'absolute', width: '2px', height: '20px', opacity: '0.01',
        border: '0', outline: '0', padding: '0', margin: '0', resize: 'none',
        overflow: 'hidden', color: 'transparent', background: 'transparent',
        caretColor: 'transparent', zIndex: '50', pointerEvents: 'none'
      });

      this.overlayLayer.appendChild(this.selectionLayer);
      this.overlayLayer.appendChild(this.cursor);
      this.overlayLayer.appendChild(this.ime);
      this.documentLayer.appendChild(this.tileLayer);
      this.documentLayer.appendChild(this.overlayLayer);
      this.stage.appendChild(this.documentLayer);
      this.surface.appendChild(this.stage);
    }

    _bindEvents() {
      this.onScroll = () => this._scheduleVisible();
      this.onPointerDown = (event) => this._pointer(event, LOK_MOUSEEVENT_MOUSEBUTTONDOWN);
      this.onPointerMove = (event) => {
        if (this.mouseDown) this._pointer(event, LOK_MOUSEEVENT_MOUSEMOVE);
      };
      this.onPointerUp = (event) => this._pointer(event, LOK_MOUSEEVENT_MOUSEBUTTONUP);
      this.onKeyDown = (event) => this._keyDown(event);
      this.onBeforeInput = (event) => this._beforeInput(event);
      this.onCompositionStart = () => { this.composing = true; };
      this.onCompositionEnd = (event) => this._compositionEnd(event);

      this.surface.addEventListener('scroll', this.onScroll, {passive: true});
      this.documentLayer.addEventListener('pointerdown', this.onPointerDown);
      this.documentLayer.addEventListener('pointermove', this.onPointerMove);
      this.documentLayer.addEventListener('pointerup', this.onPointerUp);
      this.documentLayer.addEventListener('pointercancel', this.onPointerUp);
      this.ime.addEventListener('keydown', this.onKeyDown);
      this.ime.addEventListener('beforeinput', this.onBeforeInput);
      this.ime.addEventListener('compositionstart', this.onCompositionStart);
      this.ime.addEventListener('compositionend', this.onCompositionEnd);

      this.offCallback = this.client.on('lok-callback', (message) => {
        this._handleLokCallback(message.callbackType, message.payload);
      });

      if (typeof ResizeObserver === 'function') {
        this.resizeObserver = new ResizeObserver(() => this._layoutAndSchedule());
        this.resizeObserver.observe(this.surface);
      } else {
        this.onWindowResize = () => this._layoutAndSchedule();
        window.addEventListener('resize', this.onWindowResize);
      }
    }

    async mount() {
      await this.reloadDocument();
      this.ime.focus({preventScroll: true});
    }

    async reloadDocument() {
      if (this.destroyed) return;
      this.renderEpoch += 1;
      this._dropAllTiles();
      this.info = await this.client.lokInfo();
      this._layoutDocument();
      await this._updateVisibleArea();
      this._scheduleVisible(true);
    }

    async setZoom(zoom) {
      const next = Math.min(Math.max(Number(zoom) || 1, 0.25), 4);
      if (Math.abs(next - this.zoom) < 0.001) return;
      this.zoom = next;
      this.renderEpoch += 1;
      this._dropAllTiles();
      this._layoutDocument();
      await this._updateVisibleArea();
      this._scheduleVisible(true);
    }

    _layoutDocument() {
      if (!this.info) return;
      const widthPx = Math.max(1, Math.ceil(this.info.widthTwips / this.twipsPerCssPx));
      const heightPx = Math.max(1, Math.ceil(this.info.heightTwips / this.twipsPerCssPx));
      this.documentWidthPx = widthPx;
      this.documentHeightPx = heightPx;

      const stageWidth = Math.max(this.surface.clientWidth || 1, widthPx + DOC_MARGIN * 2);
      const docLeft = Math.floor((stageWidth - widthPx) / 2);
      this.docLeft = docLeft;
      this.docTop = DOC_MARGIN;

      Object.assign(this.stage.style, {
        width: `${stageWidth}px`,
        height: `${heightPx + DOC_MARGIN * 2}px`
      });
      Object.assign(this.documentLayer.style, {
        left: `${docLeft}px`, top: `${DOC_MARGIN}px`,
        width: `${widthPx}px`, height: `${heightPx}px`
      });
      this._renderCursor();
      this._renderSelection();
    }

    _layoutAndSchedule() {
      if (!this.info) return;
      this._layoutDocument();
      this._scheduleVisible();
    }

    _visibleDocumentRectPx() {
      const x = Math.max(0, this.surface.scrollLeft - this.docLeft);
      const y = Math.max(0, this.surface.scrollTop - this.docTop);
      const right = Math.min(this.documentWidthPx, this.surface.scrollLeft + this.surface.clientWidth - this.docLeft);
      const bottom = Math.min(this.documentHeightPx, this.surface.scrollTop + this.surface.clientHeight - this.docTop);
      return {
        x, y,
        width: Math.max(0, right - x),
        height: Math.max(0, bottom - y)
      };
    }

    _scheduleVisible(force = false) {
      if (force) {
        for (const tile of this.tiles.values()) tile.dirty = true;
      }
      if (this.framePending || this.destroyed) return;
      this.framePending = true;
      requestAnimationFrame(() => {
        this.framePending = false;
        this._refreshVisible().catch((error) => console.error('[ROW view]', error));
      });
    }

    async _refreshVisible() {
      if (!this.info || this.destroyed) return;
      const rect = this._visibleDocumentRectPx();
      if (rect.width <= 0 || rect.height <= 0) return;

      const minCol = Math.max(0, Math.floor(rect.x / this.tileCss) - TILE_BUFFER);
      const minRow = Math.max(0, Math.floor(rect.y / this.tileCss) - TILE_BUFFER);
      const maxCol = Math.min(
        Math.ceil(this.documentWidthPx / this.tileCss) - 1,
        Math.floor((rect.x + rect.width) / this.tileCss) + TILE_BUFFER);
      const maxRow = Math.min(
        Math.ceil(this.documentHeightPx / this.tileCss) - 1,
        Math.floor((rect.y + rect.height) / this.tileCss) + TILE_BUFFER);

      const wanted = new Set();
      for (let row = minRow; row <= maxRow; row += 1) {
        for (let col = minCol; col <= maxCol; col += 1) {
          const key = `${col}:${row}`;
          wanted.add(key);
          const tile = this._ensureTile(col, row);
          if (tile.dirty && !tile.rendering) this._renderTile(tile);
        }
      }

      for (const [key, tile] of this.tiles) {
        if (!wanted.has(key)) {
          tile.canvas.remove();
          this.tiles.delete(key);
        }
      }
      await this._updateVisibleArea();
    }

    _ensureTile(col, row) {
      const key = `${col}:${row}`;
      let tile = this.tiles.get(key);
      if (tile) return tile;

      const x = col * this.tileCss;
      const y = row * this.tileCss;
      const cssWidth = Math.min(this.tileCss, this.documentWidthPx - x);
      const cssHeight = Math.min(this.tileCss, this.documentHeightPx - y);
      const canvas = document.createElement('canvas');
      canvas.dataset.rowTile = key;
      Object.assign(canvas.style, {
        position: 'absolute', left: `${x}px`, top: `${y}px`,
        width: `${cssWidth}px`, height: `${cssHeight}px`,
        display: 'block', background: '#fff'
      });
      this.tileLayer.appendChild(canvas);
      tile = {key, col, row, x, y, cssWidth, cssHeight, canvas, dirty: true, rendering: false};
      this.tiles.set(key, tile);
      return tile;
    }

    async _renderTile(tile) {
      if (tile.rendering || this.destroyed) return;
      tile.rendering = true;
      tile.dirty = false;
      const epoch = this.renderEpoch;
      try {
        const backingWidth = Math.max(1, Math.ceil(tile.cssWidth * this.renderScale));
        const backingHeight = Math.max(1, Math.ceil(tile.cssHeight * this.renderScale));
        const result = await this.client.renderTile({
          canvasWidth: backingWidth,
          canvasHeight: backingHeight,
          xTwips: Math.round(tile.x * this.twipsPerCssPx),
          yTwips: Math.round(tile.y * this.twipsPerCssPx),
          widthTwips: Math.max(1, Math.round(tile.cssWidth * this.twipsPerCssPx)),
          heightTwips: Math.max(1, Math.round(tile.cssHeight * this.twipsPerCssPx))
        });
        if (this.destroyed || epoch !== this.renderEpoch || !this.tiles.has(tile.key)) return;
        tile.canvas.width = result.canvasWidth;
        tile.canvas.height = result.canvasHeight;
        const pixels = new Uint8ClampedArray(result.rgba);
        const image = new ImageData(pixels, result.canvasWidth, result.canvasHeight);
        const ctx = tile.canvas.getContext('2d', {alpha: false});
        ctx.putImageData(image, 0, 0);
      } catch (error) {
        tile.dirty = true;
        console.error('[ROW tile]', tile.key, error);
      } finally {
        tile.rendering = false;
        if (tile.dirty && this.tiles.has(tile.key)) this._renderTile(tile);
      }
    }

    async _updateVisibleArea() {
      if (!this.info) return;
      const rect = this._visibleDocumentRectPx();
      if (rect.width <= 0 || rect.height <= 0) return;
      try {
        await this.client.setLokVisibleArea(
          Math.round(rect.x * this.twipsPerCssPx),
          Math.round(rect.y * this.twipsPerCssPx),
          Math.max(1, Math.round(rect.width * this.twipsPerCssPx)),
          Math.max(1, Math.round(rect.height * this.twipsPerCssPx)));
      } catch (error) {
        console.warn('[ROW visible area]', error);
      }
    }

    _invalidateTwips(rect) {
      if (!rect) {
        for (const tile of this.tiles.values()) tile.dirty = true;
        this._scheduleVisible();
        return;
      }
      const pxRect = {
        x: rect.x / this.twipsPerCssPx,
        y: rect.y / this.twipsPerCssPx,
        width: rect.width / this.twipsPerCssPx,
        height: rect.height / this.twipsPerCssPx
      };
      for (const tile of this.tiles.values()) {
        if (intersects(pxRect, tile)) tile.dirty = true;
      }
      this._scheduleVisible();
    }

    _handleLokCallback(type, payload) {
      if (this.destroyed) return;
      switch (Number(type)) {
        case LOK_CALLBACK_INVALIDATE_TILES:
          this._invalidateTwips(String(payload).trim() === 'EMPTY' ? null : parseRect(payload));
          break;
        case LOK_CALLBACK_INVALIDATE_VISIBLE_CURSOR:
          this.cursorRect = parseCursorPayload(payload);
          this._renderCursor();
          break;
        case LOK_CALLBACK_TEXT_SELECTION:
          this.selectionRects = parseRectList(payload);
          this._renderSelection();
          break;
        case LOK_CALLBACK_TEXT_SELECTION_START:
        case LOK_CALLBACK_TEXT_SELECTION_END:
          break;
        case LOK_CALLBACK_CURSOR_VISIBLE:
          this.cursorVisible = String(payload).trim() !== 'false';
          this._renderCursor();
          break;
        case LOK_CALLBACK_DOCUMENT_SIZE_CHANGED:
          this._reloadGeometryFromCallback();
          break;
        default:
          break;
      }
    }

    async _reloadGeometryFromCallback() {
      try {
        this.info = await this.client.lokInfo();
        this.renderEpoch += 1;
        this._dropAllTiles();
        this._layoutDocument();
        this._scheduleVisible(true);
      } catch (error) {
        console.warn('[ROW geometry callback]', error);
      }
    }

    _renderCursor() {
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
        display: 'block', left: `${x}px`, top: `${y}px`,
        width: `${Math.min(width, 2)}px`, height: `${height}px`
      });
      Object.assign(this.ime.style, {left: `${x}px`, top: `${y}px`, height: `${height}px`});
    }

    _renderSelection() {
      this.selectionLayer.innerHTML = '';
      if (!this.info) return;
      for (const r of this.selectionRects) {
        const node = document.createElement('div');
        Object.assign(node.style, {
          position: 'absolute',
          left: `${r.x / this.twipsPerCssPx}px`,
          top: `${r.y / this.twipsPerCssPx}px`,
          width: `${Math.max(1, r.width / this.twipsPerCssPx)}px`,
          height: `${Math.max(1, r.height / this.twipsPerCssPx)}px`,
          background: 'rgba(51, 121, 215, 0.28)'
        });
        this.selectionLayer.appendChild(node);
      }
    }

    _eventDocPoint(event) {
      const rect = this.documentLayer.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      if (x < 0 || y < 0 || x > this.documentWidthPx || y > this.documentHeightPx) return null;
      return {
        xTwips: Math.round(x * this.twipsPerCssPx),
        yTwips: Math.round(y * this.twipsPerCssPx)
      };
    }

    _mouseButtons(event, type) {
      if (type === LOK_MOUSEEVENT_MOUSEBUTTONDOWN || type === LOK_MOUSEEVENT_MOUSEBUTTONUP) {
        if (event.button === 0) return 1;
        if (event.button === 1) return 2;
        if (event.button === 2) return 4;
      }
      let value = 0;
      if (event.buttons & 1) value |= 1;
      if (event.buttons & 4) value |= 2;
      if (event.buttons & 2) value |= 4;
      return value;
    }

    _modifierMask(event) {
      let value = 0;
      if (event.shiftKey) value |= KEY_SHIFT;
      if (event.ctrlKey || event.metaKey) value |= KEY_MOD1;
      if (event.altKey) value |= KEY_MOD2;
      return value;
    }

    _pointer(event, type) {
      const point = this._eventDocPoint(event);
      if (!point) return;
      event.preventDefault();
      if (type === LOK_MOUSEEVENT_MOUSEBUTTONDOWN) {
        this.mouseDown = true;
        try { this.documentLayer.setPointerCapture(event.pointerId); } catch (_) {}
        this.ime.focus({preventScroll: true});
      } else if (type === LOK_MOUSEEVENT_MOUSEBUTTONUP) {
        this.mouseDown = false;
        try { this.documentLayer.releasePointerCapture(event.pointerId); } catch (_) {}
      }
      this.client.postLokMouse(
        type, point.xTwips, point.yTwips,
        event.detail > 1 ? event.detail : 1,
        this._mouseButtons(event, type),
        this._modifierMask(event)
      ).then(() => this._scheduleVisible()).catch((error) => console.error('[ROW mouse]', error));
    }

    async _sendSpecialKey(base, event) {
      const code = base | this._modifierMask(event);
      await this.client.postLokKey(LOK_KEYEVENT_KEYINPUT, 0, code);
      await this.client.postLokKey(LOK_KEYEVENT_KEYUP, 0, code);
      this._scheduleVisible();
    }

    _keyDown(event) {
      if (this.composing || event.isComposing) return;
      const lower = String(event.key || '').toLowerCase();
      if (event.ctrlKey || event.metaKey) {
        const commands = {
          b: '.uno:Bold', i: '.uno:Italic', u: '.uno:Underline',
          z: event.shiftKey ? '.uno:Redo' : '.uno:Undo',
          y: '.uno:Redo', a: '.uno:SelectAll', x: '.uno:Cut'
        };
        if (commands[lower]) {
          event.preventDefault();
          this.client.postUnoCommand(commands[lower]).then(() => this._scheduleVisible(true));
          return;
        }
        if (lower === 'c') {
          event.preventDefault();
          this.client.lokSelection().then(({text}) => navigator.clipboard?.writeText(text || ''));
          return;
        }
        if (lower === 'v') {
          event.preventDefault();
          if (navigator.clipboard?.readText) {
            navigator.clipboard.readText().then((text) => this.client.postTextInput(text))
              .then(() => this._scheduleVisible(true)).catch((error) => console.warn('[ROW paste]', error));
          }
          return;
        }
      }

      if (event.key === 'Backspace') {
        event.preventDefault();
        this.client.removeTextContext(1, 0).then(() => this._scheduleVisible(true));
        return;
      }
      if (event.key === 'Delete') {
        event.preventDefault();
        this.client.removeTextContext(0, 1).then(() => this._scheduleVisible(true));
        return;
      }
      const base = KEY[event.key];
      if (base !== undefined) {
        event.preventDefault();
        this._sendSpecialKey(base, event).catch((error) => console.error('[ROW key]', error));
      }
    }

    _beforeInput(event) {
      if (this.composing || event.isComposing || event.inputType === 'insertCompositionText') return;
      if (event.inputType === 'insertText' && event.data) {
        if (this.compositionCommit && event.data === this.compositionCommit) {
          this.compositionCommit = '';
          event.preventDefault();
          this.ime.value = '';
          return;
        }
        event.preventDefault();
        this.client.postTextInput(event.data).then(() => this._scheduleVisible(true));
        this.ime.value = '';
      }
    }

    _compositionEnd(event) {
      this.composing = false;
      const text = String(event.data || '');
      this.ime.value = '';
      if (!text) return;
      this.compositionCommit = text;
      setTimeout(() => { this.compositionCommit = ''; }, 80);
      this.client.postTextInput(text).then(() => this._scheduleVisible(true))
        .catch((error) => console.error('[ROW IME]', error));
    }

    _dropAllTiles() {
      for (const tile of this.tiles.values()) tile.canvas.remove();
      this.tiles.clear();
    }

    async command(command, args = '') {
      await this.client.postUnoCommand(command, args);
      this._scheduleVisible(true);
    }

    focus() {
      this.ime.focus({preventScroll: true});
    }

    destroy() {
      if (this.destroyed) return;
      this.destroyed = true;
      this.renderEpoch += 1;
      this._dropAllTiles();
      this.surface.removeEventListener('scroll', this.onScroll);
      this.documentLayer.removeEventListener('pointerdown', this.onPointerDown);
      this.documentLayer.removeEventListener('pointermove', this.onPointerMove);
      this.documentLayer.removeEventListener('pointerup', this.onPointerUp);
      this.documentLayer.removeEventListener('pointercancel', this.onPointerUp);
      this.ime.removeEventListener('keydown', this.onKeyDown);
      this.ime.removeEventListener('beforeinput', this.onBeforeInput);
      this.ime.removeEventListener('compositionstart', this.onCompositionStart);
      this.ime.removeEventListener('compositionend', this.onCompositionEnd);
      if (this.offCallback) this.offCallback();
      if (this.resizeObserver) this.resizeObserver.disconnect();
      if (this.onWindowResize) window.removeEventListener('resize', this.onWindowResize);
      this.surface.innerHTML = '';
    }
  }

  globalThis.RowOfficeCanvasView = RowOfficeCanvasView;
})();
