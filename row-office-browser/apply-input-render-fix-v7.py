#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def replace_once(rel, old, new):
    p = ROOT / rel
    s = p.read_text(encoding='utf-8')
    if old not in s:
        raise SystemExit(f'v7 patch anchor missing in {rel}: {old[:160]!r}')
    p.write_text(s.replace(old, new, 1), encoding='utf-8')

# Match the trusted Chrome path exactly: small, 1x tiles are much less likely to
# monopolize the single LibreOffice worker than 512px tiles at up to 1.5x DPR.
replace_once('row-office-view.js', "  const TILE_CSS = 512;\n", "  const TILE_CSS = 256;\n")
replace_once('row-office-view.js',
"      this.renderScale = Math.min(Math.max(window.devicePixelRatio || 1, 1), 1.5);\n",
"      this.renderScale = 1;\n")

# UI-side rendering is low-priority and single-flight. Interactive requests still
# go straight to the worker, so they can jump ahead of every not-yet-posted tile.
replace_once('row-office-client.js',
"      this.listeners = new Map();\n",
"""      this.listeners = new Map();
      this.renderQueue = [];
      this.renderInFlight = false;
""")

replace_once('row-office-client.js',
"""    renderTile({
      canvasWidth = 256,
      canvasHeight = 256,
      xTwips = 0,
      yTwips = 0,
      widthTwips = canvasWidth * 15,
      heightTwips = canvasHeight * 15
    } = {}) {
      return this.request('render-tile', {
        canvasWidth, canvasHeight, xTwips, yTwips, widthTwips, heightTwips
      });
    }
""",
"""    _pumpRenderQueue() {
      if (this.renderInFlight || !this.renderQueue.length) return;
      const item = this.renderQueue.shift();
      this.renderInFlight = true;
      // One task boundary gives freshly-arrived text/mouse/UNO requests a chance
      // to reach the worker before the next low-priority tile.
      setTimeout(() => {
        this.request('render-tile', item.payload)
          .then(item.resolve, item.reject)
          .finally(() => {
            this.renderInFlight = false;
            setTimeout(() => this._pumpRenderQueue(), 0);
          });
      }, 0);
    }

    renderTile({
      canvasWidth = 256,
      canvasHeight = 256,
      xTwips = 0,
      yTwips = 0,
      widthTwips = canvasWidth * 15,
      heightTwips = canvasHeight * 15
    } = {}) {
      const payload = {canvasWidth, canvasHeight, xTwips, yTwips, widthTwips, heightTwips};
      return new Promise((resolve, reject) => {
        this.renderQueue.push({payload, resolve, reject});
        this._pumpRenderQueue();
      });
    }
""")

replace_once('row-office-client.js',
"""    terminate() {
      this.worker.terminate();
      this._rejectAll(new Error('ROW_WORKER_TERMINATED'));
    }
""",
"""    terminate() {
      const error = new Error('ROW_WORKER_TERMINATED');
      for (const item of this.renderQueue.splice(0)) item.reject(error);
      this.worker.terminate();
      this._rejectAll(error);
    }
""")

# Defer tile work for an empty Writer until the first text commit has completed.
# The white page backdrop is already a complete representation of a blank page.
replace_once('row-office-view.js',
"      this.debugTimer = 0;\n",
"""      this.debugTimer = 0;
      this.deferInitialTiles = false;
      this.renderHoldUntil = 0;
      this.renderHoldTimer = 0;
""")

replace_once('row-office-view.js',
"""      this.info = await this.client.lokInfo();
      this._layoutDocument();
      await this._updateVisibleArea();
      this._scheduleVisible(true);
""",
"""      this.info = await this.client.lokInfo();
      let state = null;
      try { state = await this.client.readText(); } catch (_) {}
      this.deferInitialTiles = !!state && String(state.text || '') === '';
      this._layoutDocument();
      await this._updateVisibleArea();
      if (!this.deferInitialTiles) this._scheduleVisible(true);
""")

replace_once('row-office-view.js',
"""    _scheduleVisible(force = false) {
      if (force) {
        for (const tile of this.tiles.values()) tile.dirty = true;
      }
      if (this.framePending || this.destroyed) return;
""",
"""    _scheduleVisible(force = false) {
      if (force) {
        for (const tile of this.tiles.values()) tile.dirty = true;
      }
      if (this.destroyed || this.deferInitialTiles) return;
      const wait = this.renderHoldUntil - performance.now();
      if (wait > 0) {
        clearTimeout(this.renderHoldTimer);
        this.renderHoldTimer = setTimeout(() => {
          this.renderHoldTimer = 0;
          this._scheduleVisible(force);
        }, Math.ceil(wait) + 1);
        return;
      }
      if (this.framePending) return;
""")

# Every actual browser input event extends a short render quiet-period. This
# keeps typing responsive and lets repaint catch up immediately after the burst.
replace_once('row-office-view.js',
"""      this.onInputFrameKeyDown = (event) => {
        this.debugState.keydown += 1;
""",
"""      this.onInputFrameKeyDown = (event) => {
        this.renderHoldUntil = Math.max(this.renderHoldUntil, performance.now() + 220);
        this.debugState.keydown += 1;
""")

# Once a committed-text RPC succeeds, release the initial blank-document render
# gate but still respect the short typing quiet-period.
replace_once('row-office-view.js',
"""          this.debugState.commitsOk += 1;
          this._debug('commit-ok');
          this._scheduleVisible(true);
""",
"""          this.debugState.commitsOk += 1;
          this.deferInitialTiles = false;
          this.renderHoldUntil = Math.max(this.renderHoldUntil, performance.now() + 160);
          this._debug('commit-ok');
          this._scheduleVisible(true);
""")

# A normal left click only needs the synchronous Writer cursor-placement path.
# Do not also queue the known-unreliable async LOK mouse down/up behind it.
replace_once('row-office-view.js',
"""      this.client.postLokMouse(
        type,
        point.xTwips,
        point.yTwips,
        event.detail > 1 ? event.detail : 1,
        this._mouseButtons(event, type),
        this._modifierMask(event)
      ).then(() => this._scheduleVisible())
        .catch((error) => console.error('[ROW mouse]', error));
""",
"""      if (event.button === 0 &&
          (type === LOK_MOUSEEVENT_MOUSEBUTTONDOWN || type === LOK_MOUSEEVENT_MOUSEBUTTONUP)) {
        return;
      }
      this.client.postLokMouse(
        type,
        point.xTwips,
        point.yTwips,
        event.detail > 1 ? event.detail : 1,
        this._mouseButtons(event, type),
        this._modifierMask(event)
      ).then(() => this._scheduleVisible())
        .catch((error) => console.error('[ROW mouse]', error));
""")

replace_once('row-office-view.js',
"""      clearTimeout(this.refocusTimer2);
      if (this.focusWatchdog) {
""",
"""      clearTimeout(this.refocusTimer2);
      clearTimeout(this.renderHoldTimer);
      this.renderHoldTimer = 0;
      if (this.focusWatchdog) {
""")

# Worker-side RPC telemetry: if Reborn still wedges, the HUD will show the exact
# synchronous command that entered but never returned.
replace_once('row-office-thread.js',
"""      requestQueue = requestQueue.then(() => {
        const result = dispatch(message.command, message.payload || {});
        const wrapped = result && result.payload !== undefined
          ? result : {payload: result, transfer: []};
        emit('response', {id: message.id, ok: true, payload: wrapped.payload}, wrapped.transfer || []);
      }).catch((error) => {
        emit('response', {id: message.id, ok: false, error: normalizeError(error)});
      });
""",
"""      requestQueue = requestQueue.then(() => {
        emit('rpc-debug', {phase: 'start', id: message.id, command: message.command});
        const result = dispatch(message.command, message.payload || {});
        const wrapped = result && result.payload !== undefined
          ? result : {payload: result, transfer: []};
        emit('rpc-debug', {phase: 'end', id: message.id, command: message.command});
        emit('response', {id: message.id, ok: true, payload: wrapped.payload}, wrapped.transfer || []);
      }).catch((error) => {
        emit('rpc-debug', {phase: 'error', id: message.id, command: message.command});
        emit('response', {id: message.id, ok: false, error: normalizeError(error)});
      });
""")

replace_once('row-office-view.js',
"""        writerLength: -1, textareaLength: 0,
        lastEvent: 'init', lastKey: '', lastInputType: '', lastError: ''
""",
"""        writerLength: -1, textareaLength: 0,
        workerPhase: '-', workerCommand: '-', workerId: 0,
        lastEvent: 'init', lastKey: '', lastInputType: '', lastError: ''
""")

replace_once('row-office-view.js',
"""        `Q=${d.commitsQueued} OK=${d.commitsOk} ERR=${d.commitsError}`,
        `writerLen=${d.writerLength} textareaLen=${d.textareaLength}`,
""",
"""        `Q=${d.commitsQueued} OK=${d.commitsOk} ERR=${d.commitsError}`,
        `worker=${d.workerPhase}:${d.workerCommand}#${d.workerId}`,
        `writerLen=${d.writerLength} textareaLen=${d.textareaLength}`,
""")

replace_once('row-office-view.js',
"""      this.offCallback = this.client.on('lok-callback', (message) => {
        this._handleLokCallback(message.callbackType, message.payload);
      });
""",
"""      this.offCallback = this.client.on('lok-callback', (message) => {
        this._handleLokCallback(message.callbackType, message.payload);
      });
      this.offRpcDebug = this.client.on('rpc-debug', (message) => {
        this.debugState.workerPhase = String(message.phase || '-').toUpperCase();
        this.debugState.workerCommand = String(message.command || '-');
        this.debugState.workerId = Number(message.id || 0);
        this._refreshDebugHud();
      });
""")

replace_once('row-office-view.js',
"""      if (this.offCallback) this.offCallback();
      if (this.resizeObserver) this.resizeObserver.disconnect();
""",
"""      if (this.offCallback) this.offCallback();
      if (this.offRpcDebug) this.offRpcDebug();
      if (this.resizeObserver) this.resizeObserver.disconnect();
""")

print('applied ROW input/render fix v7 input-priority rendering')
