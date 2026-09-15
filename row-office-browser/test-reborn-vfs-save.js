'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

let app;
global.registerApp = (value) => { app = value; };

const source = fs.readFileSync('row-office-browser/reborn-office.js', 'utf8');
vm.runInThisContext(source, {filename: 'reborn-office.js'});
assert(app && typeof app.saveDocument === 'function');

let stored = new ArrayBuffer(0);
let corruptWrites = false;

global.wm = {
  saveFileDialog: async () => 'C:/Users/Test/Documents/smoke.odt',
  setCaption() {}
};

global.dm = {
  basename(path) {
    return String(path).split('/').pop();
  },
  async writeFile(_path, value) {
    const bytes = new Uint8Array(await value.arrayBuffer());
    if (corruptWrites && bytes.length) bytes[bytes.length - 1] ^= 0xff;
    stored = bytes.slice().buffer;
  },
  async readFile() {
    return stored.slice(0);
  }
};

app._client = {
  async save(format, name) {
    assert.equal(format, 'odt');
    assert.equal(name, 'smoke.odt');
    return {bytes: new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0x52, 0x4f, 0x57]).buffer};
  }
};
app._currentPath = 'C:/Users/Test/Documents/smoke.odt';
app._view = null;
app._contents = null;
app._hWnd = null;

(async () => {
  assert.equal(await app.saveDocument(false), true);
  assert.deepEqual(Array.from(new Uint8Array(stored)), [0x50, 0x4b, 0x03, 0x04, 0x52, 0x4f, 0x57]);

  corruptWrites = true;
  await assert.rejects(
    () => app.saveDocument(false),
    /Reborn VFS write verification failed/
  );

  console.log('ROW VFS save readback verification passed');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
