/* Reborn Office WASM: UI-side client for the single-thread LibreOffice worker.
 * Classic-script form on purpose: Reborn XP app entrypoints are ordinary scripts.
 */
'use strict';

(() => {
  class RowOfficeClient {
    constructor(workerUrl) {
      if (!workerUrl) throw new Error('ROW_WORKER_URL_REQUIRED');
      this.worker = new Worker(workerUrl, {name: 'reborn-office-libreoffice'});
      this.nextId = 1;
      this.pending = new Map();
      this.listeners = new Map();
      this.ready = new Promise((resolve, reject) => {
        this._resolveReady = resolve;
        this._rejectReady = reject;
      });

      this.worker.addEventListener('message', (event) => this._onMessage(event.data));
      this.worker.addEventListener('error', (event) => {
        const error = new Error(event.message || 'ROW_WORKER_ERROR');
        this._rejectReady(error);
        this._rejectAll(error);
      });
    }

    _onMessage(message) {
      if (!message || message.rowOffice !== true) return;
      if (message.kind === 'ready') {
        this._resolveReady(message);
        this._emit('ready', message);
        return;
      }
      if (message.kind === 'fatal') {
        const error = new Error(message.message || 'ROW_LIBREOFFICE_FATAL');
        if (message.stack) error.stack = message.stack;
        this._rejectReady(error);
        this._rejectAll(error);
        this._emit('fatal', message);
        return;
      }
      if (message.kind === 'response') {
        const pending = this.pending.get(message.id);
        if (!pending) return;
        this.pending.delete(message.id);
        if (message.ok) {
          pending.resolve(message.payload);
        } else {
          const error = new Error(message.error?.message || 'ROW_RPC_FAILED');
          error.unoType = message.error?.unoType || '';
          error.remoteStack = message.error?.stack || '';
          pending.reject(error);
        }
        return;
      }
      this._emit(message.kind, message);
    }

    _rejectAll(error) {
      for (const {reject} of this.pending.values()) reject(error);
      this.pending.clear();
    }

    _emit(type, payload) {
      for (const listener of this.listeners.get(type) || []) listener(payload);
    }

    on(type, listener) {
      const bucket = this.listeners.get(type) || new Set();
      bucket.add(listener);
      this.listeners.set(type, bucket);
      return () => bucket.delete(listener);
    }

    async request(command, payload = {}, transfer = []) {
      await this.ready;
      const id = this.nextId++;
      return new Promise((resolve, reject) => {
        this.pending.set(id, {resolve, reject});
        this.worker.postMessage({rowOffice: true, kind: 'request', id, command, payload}, transfer);
      });
    }

    ping() {
      return this.request('ping');
    }

    newWriter() {
      return this.request('new-writer');
    }

    async openFile(file) {
      const bytes = await file.arrayBuffer();
      return this.request('open-bytes', {name: file.name, bytes}, [bytes]);
    }

    openBytes(name, bytes) {
      const buffer = bytes instanceof ArrayBuffer
        ? bytes : bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
      return this.request('open-bytes', {name, bytes: buffer}, [buffer]);
    }

    readText() {
      return this.request('read-text');
    }

    replaceText(text) {
      return this.request('replace-text', {text});
    }

    appendText(text) {
      return this.request('append-text', {text});
    }

    save(format = 'odt', name = `document.${format}`) {
      return this.request('save-bytes', {format, name});
    }

    roundTrip(format = 'odt', marker = '你好 Reborn Office WASM') {
      return this.request('roundtrip', {format, marker});
    }

    lokInfo() {
      return this.request('lok-info');
    }

    renderTile({
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

    postLokKey(type, charCode = 0, keyCode = 0) {
      return this.request('lok-key', {type, charCode, keyCode});
    }

    postTextInput(text) {
      return this.request('lok-text', {text});
    }

    removeTextContext(before = 0, after = 0) {
      return this.request('lok-remove-text', {before, after});
    }

    postLokMouse(type, xTwips, yTwips, count = 1, buttons = 0, modifiers = 0) {
      return this.request('lok-mouse', {type, xTwips, yTwips, count, buttons, modifiers});
    }

    postUnoCommand(command, args = '', notifyWhenFinished = false) {
      return this.request('lok-uno', {command, args, notifyWhenFinished});
    }

    setLokVisibleArea(xTwips, yTwips, widthTwips, heightTwips) {
      return this.request('lok-visible-area', {xTwips, yTwips, widthTwips, heightTwips});
    }

    lokSelection() {
      return this.request('lok-selection');
    }

    closeDocument() {
      return this.request('close');
    }

    terminate() {
      this.worker.terminate();
      this._rejectAll(new Error('ROW_WORKER_TERMINATED'));
    }
  }

  globalThis.RowOfficeClient = RowOfficeClient;
})();
