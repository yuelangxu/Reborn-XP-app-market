/* Reborn Office WASM: UNO/ZetaJS + upstream LibreOfficeKit bridge.
 * Loaded through Module.uno_scripts after LibreOffice's UNO Embind layer exists.
 */
'use strict';

(() => {
  let zetajs;
  let css;
  let context;
  let desktop;
  let xModel;
  let lokDoc;
  let requestQueue = Promise.resolve();
  let serial = 0;

  const FILTERS = Object.freeze({
    odt: 'writer8',
    docx: 'Office Open XML Text',
    pdf: 'writer_pdf_Export',
    rtf: 'Rich Text Format',
    txt: 'Text'
  });

  const TILEMODE_RGBA = 0;
  const TILEMODE_BGRA = 1;

  function emit(kind, payload = {}, transfer = []) {
    self.postMessage({rowOffice: true, kind, ...payload}, transfer);
  }

  function lokAvailable() {
    return typeof Module.rowLokSetActive === 'function'
      && typeof Module.RowLokDocument === 'function';
  }

  function assertReady() {
    if (!zetajs || !css || !desktop) throw new Error('ROW_UNO_NOT_READY');
    if (typeof FS === 'undefined') throw new Error('ROW_EMSCRIPTEN_FS_NOT_VISIBLE');
  }

  function assertLok() {
    if (!lokAvailable()) throw new Error('ROW_LOK_BRIDGE_NOT_BUILT');
    if (!lokDoc) throw new Error('ROW_LOK_DOCUMENT_NOT_READY');
  }

  function safeName(name, fallback) {
    const value = String(name || fallback).replace(/[^A-Za-z0-9._-]+/g, '_');
    return value || fallback;
  }

  function ensureTempDir() {
    try {
      FS.mkdirTree('/tmp/row-office');
    } catch (error) {
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

  function releaseLokFacade() {
    if (!lokDoc) return;
    try {
      lokDoc.delete();
    } catch (error) {
      console.warn('[ROW] failed to release LOK facade', error);
    }
    lokDoc = undefined;
  }

  function attachLokFacade() {
    if (!lokAvailable()) return false;
    releaseLokFacade();
    lokDoc = new Module.RowLokDocument();
    lokDoc.initializeForRendering('');
    return true;
  }

  function closeCurrent() {
    if (xModel) {
      try {
        const closeable = xModel.queryInterface(zetajs.type.interface(css.util.XCloseable));
        if (closeable) xModel.close(false);
      } catch (_) {
        // Closing is best effort during replacement. A later load/save failure
        // is reported by the actual operation rather than hidden here.
      }
      xModel = undefined;
    }
    // RowLokDocument owns a strong UNO reference. Releasing it only after the
    // normal XCloseable path means its upstream destructor sees an already
    // disposed component and follows LibreOffice's own tolerant cleanup path.
    releaseLokFacade();
  }

  function newWriter() {
    assertReady();
    closeCurrent();
    xModel = desktop.loadComponentFromURL('private:factory/swriter', '_blank', 0, []);
    if (!xModel) throw new Error('ROW_WRITER_FACTORY_FAILED');
    attachLokFacade();
    return {text: readText(), lok: Boolean(lokDoc)};
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
    attachLokFacade();
    return {path, text: readText(), byteLength: bytes.byteLength, lok: Boolean(lokDoc)};
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
    attachLokFacade();
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
      pass: reopened.includes(marker),
      lok: Boolean(lokDoc)
    };
  }

  function lokInfo() {
    assertLok();
    const size = lokDoc.documentSize();
    return {
      widthTwips: Number(size[0]),
      heightTwips: Number(size[1]),
      pageRectangles: String(lokDoc.pageRectangles()),
      tileMode: Number(lokDoc.tileMode()),
      viewId: Number(lokDoc.viewId())
    };
  }

  function normalizeTileToRgba(bytes, mode) {
    if (mode === TILEMODE_RGBA) return bytes;
    if (mode !== TILEMODE_BGRA) throw new Error(`ROW_UNKNOWN_TILE_MODE:${mode}`);
    for (let i = 0; i + 3 < bytes.length; i += 4) {
      const red = bytes[i];
      bytes[i] = bytes[i + 2];
      bytes[i + 2] = red;
    }
    return bytes;
  }

  function renderTile(payload) {
    assertLok();
    const canvasWidth = Math.max(1, Number(payload.canvasWidth || 256) | 0);
    const canvasHeight = Math.max(1, Number(payload.canvasHeight || 256) | 0);
    const xTwips = Number(payload.xTwips || 0) | 0;
    const yTwips = Number(payload.yTwips || 0) | 0;
    const widthTwips = Math.max(1, Number(payload.widthTwips || canvasWidth * 15) | 0);
    const heightTwips = Math.max(1, Number(payload.heightTwips || canvasHeight * 15) | 0);
    const mode = Number(lokDoc.tileMode());
    const wasmView = lokDoc.paintTile(
      canvasWidth, canvasHeight, xTwips, yTwips, widthTwips, heightTwips);
    const copy = normalizeTileToRgba(new Uint8ClampedArray(wasmView).slice(), mode);
    return {
      payload: {
        canvasWidth,
        canvasHeight,
        xTwips,
        yTwips,
        widthTwips,
        heightTwips,
        rgba: copy.buffer
      },
      transfer: [copy.buffer]
    };
  }

  function lokKey(payload) {
    assertLok();
    lokDoc.postKeyEvent(
      Number(payload.type || 0) | 0,
      Number(payload.charCode || 0) | 0,
      Number(payload.keyCode || 0) | 0);
    return {ok: true};
  }

  function lokText(payload) {
    assertLok();
    const text = String(payload.text || '');
    if (text) lokDoc.postTextInput(text);
    return {ok: true};
  }

  function lokRemoveText(payload) {
    assertLok();
    lokDoc.removeTextContext(
      Math.max(0, Number(payload.before || 0) | 0),
      Math.max(0, Number(payload.after || 0) | 0));
    return {ok: true};
  }

  function lokMouse(payload) {
    assertLok();
    lokDoc.postMouseEvent(
      Number(payload.type || 0) | 0,
      Number(payload.xTwips || 0) | 0,
      Number(payload.yTwips || 0) | 0,
      Math.max(1, Number(payload.count || 1) | 0),
      Number(payload.buttons || 0) | 0,
      Number(payload.modifiers || 0) | 0);
    return {ok: true};
  }

  function lokUno(payload) {
    assertLok();
    lokDoc.postUnoCommand(
      String(payload.command || ''),
      payload.args == null ? '' : String(payload.args),
      Boolean(payload.notifyWhenFinished));
    return {ok: true};
  }

  function lokVisibleArea(payload) {
    assertLok();
    lokDoc.setClientVisibleArea(
      Number(payload.xTwips || 0) | 0,
      Number(payload.yTwips || 0) | 0,
      Math.max(1, Number(payload.widthTwips || 1) | 0),
      Math.max(1, Number(payload.heightTwips || 1) | 0));
    return {ok: true};
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
      case 'lok-info': return lokInfo();
      case 'render-tile': return renderTile(payload);
      case 'lok-key': return lokKey(payload);
      case 'lok-text': return lokText(payload);
      case 'lok-remove-text': return lokRemoveText(payload);
      case 'lok-mouse': return lokMouse(payload);
      case 'lok-uno': return lokUno(payload);
      case 'lok-visible-area': return lokVisibleArea(payload);
      case 'lok-selection': assertLok(); return {text: String(lokDoc.textSelection())};
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

    // LOK must be active before the Writer view is created so document/view
    // construction takes the same tiled-rendering path as normal LOK loads.
    if (lokAvailable()) Module.rowLokSetActive(true);

    installRpc();
    emit('ready', {
      engine: 'LibreOffice Technology',
      execution: 'single DedicatedWorker',
      lokBridge: lokAvailable(),
      sharedMemory: typeof SharedArrayBuffer !== 'undefined'
        && Module && Module.HEAP8 && Module.HEAP8.buffer instanceof SharedArrayBuffer
    });
  }).catch((error) => {
    const normalized = normalizeError(error);
    emit('fatal', {message: normalized.message, stack: normalized.stack});
  });
})();
