#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def replace_once(rel, old, new):
    p = ROOT / rel
    s = p.read_text(encoding='utf-8')
    if old not in s:
        raise SystemExit(f'v9 patch anchor missing in {rel}: {old[:180]!r}')
    p.write_text(s.replace(old, new, 1), encoding='utf-8')

# Track suppressed paint-originated invalidations in the existing HUD.
replace_once('row-office-view.js',
"""        workerPhase: '-', workerCommand: '-', workerId: 0,
        clientPostCommand: '-', clientPostId: 0,
""",
"""        workerPhase: '-', workerCommand: '-', workerId: 0,
        clientPostCommand: '-', clientPostId: 0,
        paintInvalidationsSuppressed: 0, tilesPainted: 0,
""")
replace_once('row-office-view.js',
"""        `worker=${d.workerPhase}:${d.workerCommand}#${d.workerId}`,
        `writerLen=${d.writerLength} textareaLen=${d.textareaLength}`,
""",
"""        `worker=${d.workerPhase}:${d.workerCommand}#${d.workerId}`,
        `tiles=${d.tilesPainted} suppressedInv=${d.paintInvalidationsSuppressed}`,
        `writerLen=${d.writerLength} textareaLen=${d.textareaLength}`,
""")

# Do not force every visible tile dirty after every character. The first commit
# needs one complete paint because an empty document started as a white backdrop;
# later commits rely on LOK's actual invalidation rectangles.
replace_once('row-office-view.js',
"""          this.debugState.commitsOk += 1;
          if (result && typeof result.text === 'string') {
            this.debugState.writerLength = result.text.length;
          }
          this.deferInitialTiles = false;
          this.renderHoldUntil = Math.max(this.renderHoldUntil, performance.now() + 160);
          this._debug('commit-ok');
          this._scheduleVisible(true);
""",
"""          this.debugState.commitsOk += 1;
          if (result && typeof result.text === 'string') {
            this.debugState.writerLength = result.text.length;
          }
          const releaseInitialPaint = this.deferInitialTiles;
          this.deferInitialTiles = false;
          this.renderHoldUntil = Math.max(this.renderHoldUntil, performance.now() + 160);
          this._debug('commit-ok');
          this._scheduleVisible(releaseInitialPaint);
""")

# Build/retain all visible canvases, but launch at most one dirty tile at a time.
# This keeps the UI-side low-priority render queue effectively length <= 1.
replace_once('row-office-view.js',
"""      const wanted = new Set();
      for (let row = minRow; row <= maxRow; row += 1) {
        for (let col = minCol; col <= maxCol; col += 1) {
          const key = `${col}:${row}`;
          wanted.add(key);
          const tile = this._ensureTile(col, row);
          if (tile.dirty && !tile.rendering) this._renderTile(tile);
        }
      }

      for (const [key, tile] of this.tiles) {
""",
"""      const wanted = new Set();
      let nextDirty = null;
      let anyRendering = false;
      for (let row = minRow; row <= maxRow; row += 1) {
        for (let col = minCol; col <= maxCol; col += 1) {
          const key = `${col}:${row}`;
          wanted.add(key);
          const tile = this._ensureTile(col, row);
          if (tile.rendering) anyRendering = true;
          else if (!nextDirty && tile.dirty) nextDirty = tile;
        }
      }

      for (const [key, tile] of this.tiles) {
""")
replace_once('row-office-view.js',
"""      }
      await this._updateVisibleArea();
    }

    _ensureTile(col, row) {
""",
"""      }
      // Never accumulate a tile backlog. One completion schedules the next frame.
      if (this.active && !anyRendering && nextDirty) this._renderTile(nextDirty);
      await this._updateVisibleArea();
    }

    _ensureTile(col, row) {
""")

# paintTile can itself cause LOK invalidation callbacks. Repainting because paint
# invalidated paint creates an endless feedback loop on the single-thread port.
# Worker telemetry is ordered with callbacks, so START:render-tile is a reliable
# marker for paint-originated invalidations.
replace_once('row-office-view.js',
"""        case LOK_CALLBACK_INVALIDATE_TILES:
          this._invalidateTwips(String(payload).trim() === 'EMPTY' ? null : parseRect(payload));
          break;
""",
"""        case LOK_CALLBACK_INVALIDATE_TILES:
          if (this.debugState && this.debugState.workerPhase === 'START'
              && this.debugState.workerCommand === 'render-tile') {
            this.debugState.paintInvalidationsSuppressed += 1;
            this._refreshDebugHud();
            break;
          }
          this._invalidateTwips(String(payload).trim() === 'EMPTY' ? null : parseRect(payload));
          break;
""")

# Never recursively re-enter painting from finally. A dirty-during-render tile is
# reconsidered on the next animation frame, after input/message tasks can run.
replace_once('row-office-view.js',
"""      } finally {
        tile.rendering = false;
        if (tile.dirty && this.tiles.has(tile.key)) this._renderTile(tile);
      }
    }
""",
"""      } finally {
        tile.rendering = false;
        if (this.debugState) this.debugState.tilesPainted += 1;
        if (this.tiles.has(tile.key) && this.active) this._scheduleVisible(false);
        this._refreshDebugHud();
      }
    }
""")

# Once the Writer becomes inactive, repaint work pauses. Existing single-flight
# paint may finish, but it is not followed by another tile until Writer is clicked.
replace_once('row-office-view.js',
"""      if (this.destroyed || this.deferInitialTiles) return;
      const wait = this.renderHoldUntil - performance.now();
""",
"""      if (this.destroyed || this.deferInitialTiles || !this.active) return;
      const wait = this.renderHoldUntil - performance.now();
""")

# Re-activation should resume any coalesced dirty work without forcing all tiles.
replace_once('row-office-view.js',
"""    _activateInput() {
      this.active = true;
      this._ensureInputFocus();
""",
"""    _activateInput() {
      this.active = true;
      this._ensureInputFocus();
      this._scheduleVisible(false);
""")

print('applied ROW v9 coalesced single-flight repaint scheduling')
