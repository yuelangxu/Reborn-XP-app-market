/* Reborn Office WASM: browser-native single-thread LibreOffice worker loader.
 *
 * This is intentionally NOT an Emscripten pthread worker.  The whole LibreOffice
 * runtime lives on one ordinary DedicatedWorker with private, non-shared WASM
 * memory.  The UI page talks to it through explicit ROW RPC messages.
 */
'use strict';

(() => {
  const here = new URL('./', self.location.href);
  const runtimeBase = new URL('./runtime/', here);
  const zetaUrl = new URL('./vendor/zeta.js', here);
  const bridgeUrl = new URL('./row-office-thread.js', here);

  function emit(kind, payload = {}) {
    self.postMessage({rowOffice: true, kind, ...payload});
  }

  // Headless soffice.js is a classic Emscripten script.  Supplying Module before
  // importScripts lets us control resource resolution and load the UNO/Zeta bridge
  // without introducing another native process or another WASM thread.
  self.Module = {
    ...(self.Module || {}),
    uno_scripts: [zetaUrl.href, bridgeUrl.href],
    locateFile(path) {
      return new URL(path, runtimeBase).href;
    },
    print(text) {
      emit('stdout', {text: String(text)});
    },
    printErr(text) {
      emit('stderr', {text: String(text)});
    },
    onAbort(reason) {
      emit('fatal', {message: `LibreOffice WASM aborted: ${String(reason)}`});
    }
  };

  emit('loader-start', {runtimeBase: runtimeBase.href});

  try {
    importScripts(new URL('soffice.js', runtimeBase).href);
  } catch (error) {
    emit('fatal', {
      message: error && error.message ? error.message : String(error),
      stack: error && error.stack ? String(error.stack) : ''
    });
    throw error;
  }
})();
