/* Reborn Office WASM: UNO/ZetaJS bridge executed inside the LibreOffice worker.
 * Loaded through Module.uno_scripts after LibreOffice's UNO Embind layer exists.
 */
'use strict';

(() => {
  let zetajs;
  let css;
  let context;
  let desktop;
  let xModel;
  let requestQueue = Promise.resolve();
  let serial = 0;

  const FILTERS = Object.freeze({
    odt: 'writer8',
    docx: 'Office Open XML Text',
    pdf: 'writer_pdf_Export',
    rtf: 'Rich Text Format',
    txt: 'Text'
  });

  function emit(kind, payload = {}, transfer = []) {
    self.postMessage({rowOffice: true, kind, ...payload}, transfer);
  }

  function assertReady() {
    if (!zetajs || !css || !desktop) throw new Error('ROW_UNO_NOT_READY');
    if (typeof FS === 'undefined') throw new Error('ROW_EMSCRIPTEN_FS_NOT_VISIBLE');
  }

  function safeName(name, fallback) {
    const value = String(name || fallback).replace(/[^A-Za-z0-9._-]+/g, '_');
    return value || fallback;
  }

  function ensureTempDir() {
    try {
      FS.mkdirTree('/tmp/row-office');
    } catch (error) {
      // mkdirTree is idempotent in Emscripten.  Re-throw only if the directory
      // still does not exist after an unexpected implementation-specific error.
      try {
        const stat = FS.stat('/tmp/row-office');
        if (!FS.isDir(stat.mode)) throw error;
      } catch (_) {
        throw error;
      }
    }
  }

  function uniquePath(name) {
    ensureTempDir();
    serial += 1;
    return `/tmp/row-office/${Date.now()}-${serial}-${safeName(name, 'document.odt')}`;
  }

  function fileUrl(path) {
    return `file://${path}`;
  }

  function closeCurrent() {
    if (!xModel) return;
    try {
      const closeable = xModel.queryInterface(zetajs.type.interface(css.util.XCloseable));
      if (closeable) xModel.close(false);
    } catch (_) {
      // Closing is best effort during replacement.  A load/save failure is
      // reported by the actual operation rather than hidden here.
    }
    xModel = undefined;
  }

  function newWriter() {
    assertReady();
    closeCurrent();
    xModel = desktop.loadComponentFromURL('private:factory/swriter', '_blank', 0, []);
    if (!xModel) throw new Error('ROW_WRITER_FACTORY_FAILED');
    return {text: readText()};
  }

  function openBytes(payload) {
    assertReady();
    const bytes = new Uint8Array(payload.bytes || new ArrayBuffer(0));
    if (!bytes.byteLength) throw new Error('ROW_OPEN_EMPTY_FILE');
    const path = uniquePath(payload.name || 'document.odt');
    FS.writeFile(path, bytes);
    closeCurrent();
    xModel = desktop.loadComponentFromURL(fileUrl(path), '_blank', 0, []);
    if (!xModel) throw new Error('ROW_DOCUMENT_LOAD_FAILED');
    return {path, text: readText(), byteLength: bytes.byteLength};
  }

  function readText() {
    assertReady();
    if (!xModel) throw new Error('ROW_NO_DOCUMENT');
    const xText = xModel.getText();
    return String(xText.getString());
  }

  function replaceAllText(text) {
    assertReady();
    if (!xModel) throw new Error('ROW_NO_DOCUMENT');
    const xText = xModel.getText();
    const cursor = xText.createTextCursor();
    cursor.gotoEnd(true);
    cursor.setString(String(text));
    return {text: readText()};
  }

  function appendText(text) {
    assertReady();
    if (!xModel) throw new Error('ROW_NO_DOCUMENT');
    const xText = xModel.getText();
    const cursor = xText.createTextCursor();
    cursor.gotoEnd(false);
    cursor.setString(String(text));
    return {text: readText()};
  }

  function saveToFs(format, requestedName) {
    assertReady();
    if (!xModel) throw new Error('ROW_NO_DOCUMENT');
    format = String(format || 'odt').toLowerCase();
    const filter = FILTERS[format];
    if (!filter) throw new Error(`ROW_UNSUPPORTED_EXPORT:${format}`);

    const name = safeName(requestedName, `document.${format}`);
    const path = uniquePath(name.endsWith(`.${format}`) ? name : `${name}.${format}`);
    const overwrite = new css.beans.PropertyValue({Name: 'Overwrite', Value: true});
    const filterName = new css.beans.PropertyValue({Name: 'FilterName', Value: filter});
    xModel.storeToURL(fileUrl(path), [overwrite, filterName]);
    const bytes = FS.readFile(path);
    return {path, format, bytes: new Uint8Array(bytes)};
  }

  function saveBytes(payload) {
    const result = saveToFs(payload.format, payload.name);
    const copy = result.bytes.slice();
    return {
      payload: {
        format: result.format,
        path: result.path,
        byteLength: copy.byteLength,
        bytes: copy.buffer
      },
      transfer: [copy.buffer]
    };
  }

  function reopenPath(path) {
    closeCurrent();
    xModel = desktop.loadComponentFromURL(fileUrl(path), '_blank', 0, []);
    if (!xModel) throw new Error('ROW_DOCUMENT_REOPEN_FAILED');
    return readText();
  }

  function roundTrip(payload) {
    const format = String(payload.format || 'odt').toLowerCase();
    const marker = String(payload.marker || '你好 Reborn Office WASM');
    newWriter();
    replaceAllText(marker);
    const saved = saveToFs(format, `roundtrip.${format}`);
    const reopened = reopenPath(saved.path);
    return {
      format,
      marker,
      reopened,
      byteLength: saved.bytes.byteLength,
      pass: reopened.includes(marker)
    };
  }

  function normalizeError(error) {
    let value = error;
    try {
      value = zetajs ? zetajs.catchUnoException(error) : error;
    } catch (_) {
      value = error;
    }
    let unoType = '';
    try {
      unoType = zetajs ? String(zetajs.getAnyType(value)) : '';
    } catch (_) {}
    return {
      message: value && value.Message ? String(value.Message)
        : error && error.message ? String(error.message) : String(error),
      unoType,
      stack: error && error.stack ? String(error.stack) : ''
    };
  }

  function dispatch(command, payload) {
    switch (command) {
      case 'ping': return {pong: true};
      case 'new-writer': return newWriter();
      case 'open-bytes': return openBytes(payload);
      case 'read-text': return {text: readText()};
      case 'replace-text': return replaceAllText(payload.text);
      case 'append-text': return appendText(payload.text);
      case 'save-bytes': return saveBytes(payload);
      case 'roundtrip': return roundTrip(payload);
      case 'close': closeCurrent(); return {closed: true};
      default: throw new Error(`ROW_UNKNOWN_COMMAND:${command}`);
    }
  }

  function installRpc() {
    self.addEventListener('message', (event) => {
      const message = event.data;
      if (!message || message.rowOffice !== true || message.kind !== 'request') return;
      requestQueue = requestQueue.then(() => {
        const result = dispatch(message.command, message.payload || {});
        const wrapped = result && result.payload !== undefined
          ? result : {payload: result, transfer: []};
        emit('response', {id: message.id, ok: true, payload: wrapped.payload}, wrapped.transfer || []);
      }).catch((error) => {
        emit('response', {id: message.id, ok: false, error: normalizeError(error)});
      });
    });
  }

  if (!Module.zetajs || typeof Module.zetajs.then !== 'function') {
    emit('fatal', {message: 'ROW_ZETAJS_NOT_LOADED'});
    return;
  }

  Module.zetajs.then((api) => {
    zetajs = api;
    css = zetajs.uno.com.sun.star;
    context = zetajs.getUnoComponentContext();
    desktop = css.frame.Desktop.create(context);
    ensureTempDir();
    installRpc();
    emit('ready', {
      engine: 'LibreOffice Technology',
      execution: 'single DedicatedWorker',
      sharedMemory: typeof SharedArrayBuffer !== 'undefined'
        && Module && Module.HEAP8 && Module.HEAP8.buffer instanceof SharedArrayBuffer
    });
  }).catch((error) => {
    emit('fatal', {message: normalizeError(error).message, stack: normalizeError(error).stack});
  });
})();
