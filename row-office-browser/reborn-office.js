/* Reborn Office for Reborn XP.
 *
 * This file is the thin OS integration layer.  LibreOffice itself lives in a
 * single DedicatedWorker and operates on bytes transferred to/from the Reborn
 * virtual filesystem.  The document rendering surface is deliberately isolated
 * so the LibreOfficeKit renderer can replace it without changing file I/O.
 */
(function () {
  'use strict';

  const OPEN_FILTERS = [
    {name: 'Writer documents', extensions: ['odt', 'docx', 'doc', 'rtf', 'txt']},
    {name: 'OpenDocument Text (*.odt)', extensions: ['odt']},
    {name: 'Word documents (*.docx, *.doc)', extensions: ['docx', 'doc']},
    {name: 'Rich Text Format (*.rtf)', extensions: ['rtf']},
    {name: 'Text files (*.txt)', extensions: ['txt']},
    {name: 'All files (*.*)', extensions: ['*.*']}
  ];

  const SAVE_FILTERS = [
    {name: 'OpenDocument Text (*.odt)', extensions: ['odt']},
    {name: 'Word 2007-365 (*.docx)', extensions: ['docx']},
    {name: 'Rich Text Format (*.rtf)', extensions: ['rtf']},
    {name: 'Text files (*.txt)', extensions: ['txt']},
    {name: 'PDF document (*.pdf)', extensions: ['pdf']}
  ];

  const TEMPLATE = `
    <appcontentholder class="row-office-app" style="height:100%;display:flex;flex-direction:column;background:#d4d0c8;">
      <appnavigation>
        <ul class="appmenus">
          <li>File
            <ul class="submenu">
              <li data-row-action="new">New</li>
              <li data-row-action="open">Open...</li>
              <li class="divider"></li>
              <li data-row-action="save">Save</li>
              <li data-row-action="saveas">Save As...</li>
              <li class="divider"></li>
              <li data-row-action="exit">Exit</li>
            </ul>
          </li>
          <li>Edit
            <ul class="submenu">
              <li data-row-action="selectall">Select All</li>
            </ul>
          </li>
          <li>Help
            <ul class="submenu">
              <li data-row-action="engine">Engine Status</li>
            </ul>
          </li>
        </ul>
      </appnavigation>
      <div class="row-office-toolbar" style="display:flex;gap:4px;padding:4px;border-bottom:1px solid #808080;">
        <button type="button" data-row-action="new">New</button>
        <button type="button" data-row-action="open">Open</button>
        <button type="button" data-row-action="save">Save</button>
      </div>
      <div class="row-office-surface" style="position:relative;flex:1;overflow:auto;background:#808080;padding:24px;">
        <div class="row-office-engine-card" style="box-sizing:border-box;max-width:760px;min-height:480px;margin:0 auto;background:white;box-shadow:0 0 0 1px #555;padding:32px;font-family:Tahoma,Arial,sans-serif;">
          <h3 style="margin-top:0;font-weight:normal;">LibreOffice Writer</h3>
          <p data-row-role="message">Starting LibreOffice Technology WASM engine...</p>
          <pre data-row-role="diagnostic" style="white-space:pre-wrap;font:12px Consolas,monospace;color:#555;"></pre>
        </div>
      </div>
      <div class="row-office-status" style="height:22px;display:flex;align-items:center;padding:0 6px;border-top:1px solid #808080;font:11px Tahoma,Arial,sans-serif;">
        <span data-row-role="status">Starting...</span>
      </div>
    </appcontentholder>`;

  function extension(path) {
    const name = String(path || '').split('/').pop();
    const dot = name.lastIndexOf('.');
    return dot >= 0 ? name.slice(dot + 1).toLowerCase() : '';
  }

  function exportFormat(path) {
    const ext = extension(path);
    if (['odt', 'docx', 'rtf', 'txt', 'pdf'].includes(ext)) return ext;
    return 'odt';
  }

  async function blobToArrayBuffer(value) {
    if (value instanceof ArrayBuffer) return value;
    if (ArrayBuffer.isView(value)) {
      return value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength);
    }
    if (value instanceof Blob) return value.arrayBuffer();
    if (typeof value === 'string') return new TextEncoder().encode(value).buffer;
    throw new Error('Unsupported Reborn VFS payload type');
  }

  function loadClassicScript(url) {
    return new Promise((resolve, reject) => {
      const old = Array.from(document.scripts).find((script) => script.src === url);
      if (old && globalThis.RowOfficeClient) return resolve();
      const script = document.createElement('script');
      script.src = url;
      script.async = true;
      script.onload = resolve;
      script.onerror = () => reject(new Error(`Failed to load ${url}`));
      document.head.appendChild(script);
    });
  }

  registerApp({
    _template: null,
    _hWnd: null,
    _contents: null,
    _client: null,
    _currentPath: null,
    _installPath: null,
    _engineInfo: null,

    setup: async function () {
      this._template = document.createElement('template');
      this._template.innerHTML = TEMPLATE;
    },

    start: async function (options) {
      if (!options.installPath) {
        dialogHandler.spawnDialog({
          icon: 'error', title: 'Reborn Office', text: 'Missing application install path.'
        });
        return;
      }

      this._installPath = options.installPath;
      this._contents = this._template.content.firstElementChild.cloneNode(true);
      this._hWnd = wm.createNewWindow('reborn-office-writer', this._contents);
      wm.setCaption(this._hWnd, 'Untitled - Reborn Office Writer');
      if (options.icon) wm.setIcon(this._hWnd, options.icon);
      wm.setSize(this._hWnd, 900, 650);
      this._bindActions();

      try {
        const clientUrl = dm.getVfsUrl(dm.join(this._installPath, 'row-office-client.js'));
        const workerUrl = dm.getVfsUrl(dm.join(this._installPath, 'row-office-worker-loader.js'));
        await loadClassicScript(clientUrl);
        this._client = new globalThis.RowOfficeClient(workerUrl);
        this._client.on('stdout', (m) => console.log('[ROW]', m.text));
        this._client.on('stderr', (m) => console.warn('[ROW]', m.text));
        this._client.on('open-url', (m) => {
          try { window.open(m.url, '_blank', 'noopener'); } catch (e) { console.warn(e); }
        });
        this._client.on('fatal', (m) => this._showEngineError(m.message));
        this._engineInfo = await this._client.ready;
        if (this._engineInfo.sharedMemory) {
          throw new Error('ROW invariant failed: LibreOffice WASM memory is shared');
        }
        this._setMessage('LibreOffice Technology engine ready. LibreOfficeKit page rendering is the next bridge attached to this surface.');
        this._setStatus('Ready');

        if (options.filePath && !options.filePath.toLowerCase().endsWith('.exe')) {
          await this.loadFile(options.filePath);
        } else {
          await this._client.newWriter();
        }
      } catch (error) {
        console.error(error);
        this._showEngineError(error.message || String(error));
      }

      const hostWindow = wm._windows[this._hWnd];
      if (hostWindow) {
        hostWindow.addEventListener('wm:windowClosed', () => {
          if (this._client) this._client.terminate();
          this._client = null;
          this._contents = null;
          this._hWnd = null;
        }, {once: true});
      }
      return this._hWnd;
    },

    _bindActions: function () {
      this._contents.querySelectorAll('[data-row-action="new"]').forEach((node) => {
        node.onclick = () => this.newDocument();
      });
      this._contents.querySelectorAll('[data-row-action="open"]').forEach((node) => {
        node.onclick = () => this.openDialog();
      });
      this._contents.querySelectorAll('[data-row-action="save"]').forEach((node) => {
        node.onclick = () => this.saveDocument(false);
      });
      this._contents.querySelector('[data-row-action="saveas"]').onclick = () => this.saveDocument(true);
      this._contents.querySelector('[data-row-action="exit"]').onclick = () => wm.closeWindow(this._hWnd);
      this._contents.querySelector('[data-row-action="engine"]').onclick = () => this.showEngineStatus();
      this._contents.querySelector('[data-row-action="selectall"]').onclick = () => {
        // This command is intentionally a no-op until the LOK view bridge owns
        // the active selection. File I/O and engine lifetime do not depend on it.
      };
    },

    _setStatus: function (text) {
      const node = this._contents && this._contents.querySelector('[data-row-role="status"]');
      if (node) node.textContent = text;
    },

    _setMessage: function (text, diagnostic = '') {
      if (!this._contents) return;
      const message = this._contents.querySelector('[data-row-role="message"]');
      const diag = this._contents.querySelector('[data-row-role="diagnostic"]');
      if (message) message.textContent = text;
      if (diag) diag.textContent = diagnostic;
    },

    _showEngineError: function (message) {
      this._setStatus('Engine error');
      this._setMessage('LibreOffice Technology failed to start.', message || 'Unknown error');
      dialogHandler.spawnDialog({
        icon: 'error', title: 'Reborn Office Engine Error', text: String(message || 'Unknown error')
      });
    },

    _updateCaption: function () {
      const name = this._currentPath ? dm.basename(this._currentPath) : 'Untitled';
      if (this._hWnd) wm.setCaption(this._hWnd, `${name} - Reborn Office Writer`);
    },

    newDocument: async function () {
      if (!this._client) return;
      this._setStatus('Creating document...');
      await this._client.newWriter();
      this._currentPath = null;
      this._updateCaption();
      this._setStatus('Ready');
    },

    openDialog: async function () {
      const path = await wm.openFileDialog({title: 'Open Writer Document', filters: OPEN_FILTERS});
      if (path) await this.loadFile(path);
    },

    loadFile: async function (path) {
      if (!this._client) return;
      this._setStatus(`Opening ${dm.basename(path)}...`);
      const value = await dm.readFile(path);
      const bytes = await blobToArrayBuffer(value);
      await this._client.openBytes(dm.basename(path), bytes);
      this._currentPath = path;
      this._updateCaption();
      this._setStatus('Ready');
    },

    saveDocument: async function (saveAs) {
      if (!this._client) return false;
      let path = this._currentPath;
      if (saveAs || !path) {
        path = await wm.saveFileDialog({title: 'Save Writer Document', filters: SAVE_FILTERS});
        if (!path) return false;
      }

      const format = exportFormat(path);
      this._setStatus(`Saving ${dm.basename(path)}...`);
      const result = await this._client.save(format, dm.basename(path));
      await dm.writeFile(path, new Blob([result.bytes], {type: 'application/octet-stream'}));
      if (format !== 'pdf') {
        this._currentPath = path;
        this._updateCaption();
      }
      this._setStatus('Ready');
      return true;
    },

    showEngineStatus: function () {
      const info = this._engineInfo || {};
      dialogHandler.spawnDialog({
        icon: 'info',
        title: 'Reborn Office Engine',
        text: [
          'LibreOffice Technology (WebAssembly)',
          `Execution: ${info.execution || 'not ready'}`,
          `Shared memory: ${info.sharedMemory ? 'YES (invalid)' : 'No'}`,
          'Native server/process: none'
        ].join('<br>')
      });
    }
  });
})();
