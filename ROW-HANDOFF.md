# Reborn Office browser-native handoff

Updated: 2026-09-15

## Goal

Port real LibreOffice Writer into Reborn XP as browser-native WebAssembly.

Hard invariants:

- no native helper/server process
- no iframe remote-office workaround
- no `SharedArrayBuffer` requirement
- no Emscripten pthread pool
- one ordinary `DedicatedWorker` owns LibreOffice WASM with private memory
- Reborn main UI communicates with the worker through explicit RPC
- real ODT/DOCX open/edit/save/reopen
- LibreOfficeKit tile rendering and input
- Chinese text/IME and pinned CJK font
- Reborn VFS open/save with post-write byte verification

## Branches

- Stable development branch: `row-office-core-port`
- Integrated candidate branch: `row-office-core-port-prep`
- `row-office-core-port-prep` is a fast-forward descendant of the stable branch; do not force-update the stable branch.

At the time of this note, the integrated candidate includes:

- single-thread LibreOffice core patches
- synchronous UNO/ZetaJS worker startup
- RowLokBridge integration
- pinned Noto Sans CJK staging and filesystem-image integration
- browser worker/RPC/view layer
- browser acceptance page
- deterministic Reborn package builder
- ccache and external-tarball caches
- exact pinned-source transform smoke tests
- Reborn VFS save/read-back verification

## Canonical product/runtime files

Browser/runtime layer:

- `row-office-browser/reborn-office.js`
- `row-office-browser/row-office-client.js`
- `row-office-browser/row-office-worker-loader.js`
- `row-office-browser/row-office-thread.js`
- `row-office-browser/row-office-view.js`
- `row-office-browser/acceptance.html`
- `row-office-browser/run-acceptance.sh`
- `row-office-browser/prepare-runtime-tree.sh`

Release builder:

- `row-office-browser/build-reborn-package-v2.py`

Core port:

- `row-office-port/patch_lo.py`
- `row-office-port/build.sh`

LOK/CJK:

- `row-office-lok/row_lok_bridge.cxx`
- `row-office-lok/integrate_bridge.py`
- `row-office-lok/integrate_cjk_font.py`
- `row-office-lok/prepare_cjk_font.sh`

CI:

- `.github/workflows/row-office-browser-smoke.yml`
- `.github/workflows/row-office-core-port.yml`

## Verified cheap gates

Latest browser smoke has passed all of these together:

1. JS/Python/shell syntax.
2. Exact `31eabe1e534a70a2b7d5c39eb31e56a75c17be3b` LibreOffice checkout accepts the full transform stack.
3. `git diff --check` passes after all transforms.
4. no explicit `SharedArrayBuffer` / Atomics / pthread-proxy browser architecture.
5. synchronous `importScripts()` ROW path is present for UNO scripts.
6. RowLokBridge and CJK FS-image transforms are present.
7. deterministic Reborn ZIP built twice has identical SHA-256.
8. ZIP contains explicit parent-before-child directory entries for the historical Reborn extractor.
9. self-contained JSON launcher does not call `apps.load`.
10. Reborn VFS successful save round-trip passes and deliberately corrupted persisted bytes are rejected.

The exact-source patch footprint before adding the bridge source itself was small: 12 LibreOffice files, 118 insertions and 6 deletions.

## Full-build / acceptance contract

A full core run is not green merely because `make` exits 0.

Required sequence:

1. configure and build pinned LibreOffice Writer for no-pthread Emscripten
2. collect sibling `soffice.js`, `soffice.wasm`, `soffice.data`, `soffice.data.js.metadata`
3. inspect WASM and require non-shared memory
4. assemble browser runtime with pinned ZetaJS and CJK licensing
5. run headless-Chromium acceptance:
   - UNO ready
   - ODT marker save/reopen
   - DOCX marker save/reopen
   - Chinese text input
   - LOK document dimensions
   - non-empty 128x128 tile render
6. only after acceptance passes, build `RebornOfficeWasm-browser-native.zip`
7. upload the final release artifact and SHA-256

## Cache rules

Python cache:

- fixed builder-compatible Python 3.12 cache

LibreOffice ccache:

- per-run save key
- prefix restore key

External tarballs:

- `v2` per-run save keys with prefix restore
- this deliberately avoids a cancelled run permanently poisoning one fixed key with an empty cache

## Active runs at handoff creation

- Old core Run 16: `35009363868`
  - head: `6bfb4fa0519ccee64dbd5e21b7d7e5e5bd3287bb`
  - still inside full no-pthread Writer build
  - useful as the earliest likely compiler-evidence source

- Prep Run 18: `35019567358`
  - superseded by the newest cache fix but may finish Python bootstrap and seed the Python cache before cancellation

- Prep Run 19: `35019766555`
  - head: `9336aec8e9b161584b0de0445a26069be2a3f342`
  - newest integrated core candidate
  - should be treated as the primary full-build run once scheduled

- Browser smoke Run 33: `35019646255`
  - includes the executed Reborn VFS durability test

## Next action

Do not add speculative core patches while a full build is running.

First consume whichever full run finishes first:

- if it fails: download compiler evidence, identify the first real blocker, patch only that blocker, rerun
- if it links: continue immediately into the browser acceptance contract above
- if acceptance passes: use the generated final Reborn ZIP rather than making an ad-hoc package

Do not claim the project is finished until the actual browser acceptance page passes against the real generated LibreOffice runtime.
