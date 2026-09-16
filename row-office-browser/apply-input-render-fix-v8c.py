#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def replace_once(rel,old,new):
    p=ROOT/rel
    s=p.read_text(encoding='utf-8')
    if old not in s:
        raise SystemExit(f'v8c anchor missing in {rel}: {old[:180]!r}')
    p.write_text(s.replace(old,new,1),encoding='utf-8')

# Once the worker has announced ready, interactive requests must cross the
# UI->Worker boundary synchronously in the same task. Avoid an unnecessary
# `await this.ready` microtask hop for every keystroke.
replace_once('row-office-client.js',
"      this.listeners = new Map();\n",
"      this.listeners = new Map();\n      this.isReady = false;\n")
replace_once('row-office-client.js',
"""      if (message.kind === 'ready') {
        this._resolveReady(message);
""",
"""      if (message.kind === 'ready') {
        this.isReady = true;
        this._resolveReady(message);
""")
replace_once('row-office-client.js', '''    async request(command, payload = {}, transfer = []) {
      await this.ready;
      const id = this.nextId++;
      return new Promise((resolve, reject) => {
        this.pending.set(id, {resolve, reject});
        this.worker.postMessage({rowOffice: true, kind: 'request', id, command, payload}, transfer);
      });
    }
''', '''    _requestNow(command, payload = {}, transfer = []) {
      const id = this.nextId++;
      this._emit('rpc-client-debug', {phase:'post', id, command});
      return new Promise((resolve, reject) => {
        this.pending.set(id, {resolve, reject});
        try {
          this.worker.postMessage({rowOffice: true, kind: 'request', id, command, payload}, transfer);
        } catch (error) {
          this.pending.delete(id);
          reject(error);
        }
      });
    }

    request(command, payload = {}, transfer = []) {
      if (this.isReady) return this._requestNow(command, payload, transfer);
      return this.ready.then(() => this._requestNow(command, payload, transfer));
    }
''')

# The diagnostic readText poll generated continuous unrelated Worker traffic and
# made request IDs race ahead. Writer length is now updated from each successful
# committed-text response, so the HUD is passive.
replace_once('row-office-view.js', '''      if (!this.debugTimer) {
        this.debugTimer = setInterval(() => {
          if (this.destroyed) return;
          this._refreshDebugHud();
          this.client.readText().then(({text}) => {
            this.debugState.writerLength = String(text || '').length;
            this._refreshDebugHud();
          }).catch((error) => {
            this.debugState.lastError = `readText: ${String(error && error.message ? error.message : error)}`;
            this._refreshDebugHud();
          });
        }, 500);
      }
''', '''      // HUD deliberately does not poll the Worker. Every diagnostic request can
      // perturb the single-worker scheduler we are trying to observe.
      this._refreshDebugHud();
''')
replace_once('row-office-view.js', '''      return this.client.postTextInput(value)
        .then(() => {
          this.debugState.commitsOk += 1;
''', '''      return this.client.postTextInput(value)
        .then((result) => {
          this.debugState.commitsOk += 1;
          if (result && typeof result.text === 'string') {
            this.debugState.writerLength = result.text.length;
          }
''')

# Client-side post telemetry distinguishes "_postText called" from an RPC that
# actually crossed Worker.postMessage.
replace_once('row-office-view.js', '''      this.offRpcDebug = this.client.on('rpc-debug', (message) => {
        this.debugState.workerPhase = String(message.phase || '-').toUpperCase();
''', '''      this.offClientRpcDebug = this.client.on('rpc-client-debug', (message) => {
        this.debugState.clientPostId = Number(message.id || 0);
        this.debugState.clientPostCommand = String(message.command || '-');
        this._refreshDebugHud();
      });
      this.offRpcDebug = this.client.on('rpc-debug', (message) => {
        this.debugState.workerPhase = String(message.phase || '-').toUpperCase();
''')
replace_once('row-office-view.js', '''        workerPhase: '-', workerCommand: '-', workerId: 0,
        lastEvent: 'init', lastKey: '', lastInputType: '', lastError: ''
''', '''        workerPhase: '-', workerCommand: '-', workerId: 0,
        clientPostCommand: '-', clientPostId: 0,
        lastEvent: 'init', lastKey: '', lastInputType: '', lastError: ''
''')
replace_once('row-office-view.js', '''        `worker=${d.workerPhase}:${d.workerCommand}#${d.workerId}`,
        `writerLen=${d.writerLength} textareaLen=${d.textareaLength}`,
''', '''        `post=${d.clientPostCommand}#${d.clientPostId}`,
        `worker=${d.workerPhase}:${d.workerCommand}#${d.workerId}`,
        `writerLen=${d.writerLength} textareaLen=${d.textareaLength}`,
''')
replace_once('row-office-view.js', '''      if (this.offRpcDebug) this.offRpcDebug();
      if (this.resizeObserver) this.resizeObserver.disconnect();
''', '''      if (this.offRpcDebug) this.offRpcDebug();
      if (this.offClientRpcDebug) this.offClientRpcDebug();
      if (this.resizeObserver) this.resizeObserver.disconnect();
''')

# Remove now-dead debug timer state/cleanup.
replace_once('row-office-view.js', "      this.debugTimer = 0;\n", "")
replace_once('row-office-view.js', '''      if (this.debugTimer) {
        clearInterval(this.debugTimer);
        this.debugTimer = 0;
      }
''', '')

print('applied ROW v8c synchronous UI-to-worker RPC dispatch')
