#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def replace_once(rel, old, new):
    p = ROOT / rel
    s = p.read_text(encoding='utf-8')
    if old not in s:
        raise SystemExit(f'v10 patch anchor missing in {rel}: {old[:180]!r}')
    p.write_text(s.replace(old, new, 1), encoding='utf-8')

# Emit a marker synchronously at Worker message-event entry, before the Promise
# requestQueue is touched. RECEIVED without START means the Promise queue stalled;
# no RECEIVED means the Worker task loop itself stopped consuming message events.
replace_once('row-office-thread.js',
"""    self.addEventListener('message', (event) => {
      const message = event.data;
      if (!message || message.rowOffice !== true || message.kind !== 'request') return;
      requestQueue = requestQueue.then(() => {
""",
"""    self.addEventListener('message', (event) => {
      const message = event.data;
      if (!message || message.rowOffice !== true || message.kind !== 'request') return;
      emit('rpc-debug', {phase: 'received', id: message.id, command: message.command});
      requestQueue = requestQueue.then(() => {
""")

# Independent Worker macrotask heartbeat. If this freezes after paintTile returns,
# LibreOffice/Emscripten is starving the browser Worker task loop itself.
replace_once('row-office-thread.js',
"""    installRpc();
    emit('ready', {
""",
"""    installRpc();
    let rowWorkerHeartbeat = 0;
    setInterval(() => {
      rowWorkerHeartbeat += 1;
      emit('worker-heartbeat', {seq: rowWorkerHeartbeat, wallTime: Date.now()});
    }, 250);
    emit('ready', {
""")

# Surface heartbeat state in the existing HUD and trace snapshots.
replace_once('row-office-view.js',
"""        workerPhase: '-', workerCommand: '-', workerId: 0,
        clientPostCommand: '-', clientPostId: 0,
""",
"""        workerPhase: '-', workerCommand: '-', workerId: 0,
        workerHeartbeat: 0, workerHeartbeatAt: 0,
        clientPostCommand: '-', clientPostId: 0,
""")
replace_once('row-office-view.js',
"""        `worker=${d.workerPhase}:${d.workerCommand}#${d.workerId}`,
        `tiles=${d.tilesPainted} suppressedInv=${d.paintInvalidationsSuppressed}`,
""",
"""        `worker=${d.workerPhase}:${d.workerCommand}#${d.workerId} hb=${d.workerHeartbeat}`,
        `tiles=${d.tilesPainted} suppressedInv=${d.paintInvalidationsSuppressed}`,
""")
replace_once('row-office-view.js',
"""      this.offRpcDebug = this.client.on('rpc-debug', (message) => {
        this.debugState.workerPhase = String(message.phase || '-').toUpperCase();
        this.debugState.workerCommand = String(message.command || '-');
        this.debugState.workerId = Number(message.id || 0);
        this._refreshDebugHud();
      });
""",
"""      this.offRpcDebug = this.client.on('rpc-debug', (message) => {
        this.debugState.workerPhase = String(message.phase || '-').toUpperCase();
        this.debugState.workerCommand = String(message.command || '-');
        this.debugState.workerId = Number(message.id || 0);
        this._refreshDebugHud();
      });
      this.offWorkerHeartbeat = this.client.on('worker-heartbeat', (message) => {
        this.debugState.workerHeartbeat = Number(message.seq || 0);
        this.debugState.workerHeartbeatAt = performance.now();
        this._refreshDebugHud();
      });
""")
replace_once('row-office-view.js',
"""      if (this.offRpcDebug) this.offRpcDebug();
      if (this.offClientRpcDebug) this.offClientRpcDebug();
""",
"""      if (this.offRpcDebug) this.offRpcDebug();
      if (this.offWorkerHeartbeat) this.offWorkerHeartbeat();
      if (this.offClientRpcDebug) this.offClientRpcDebug();
""")

print('applied ROW v10 Worker message-entry and heartbeat diagnostics')
