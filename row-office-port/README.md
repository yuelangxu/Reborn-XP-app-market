# Reborn Office core port CI

Private development lane for compiling LibreOffice Writer Technology to browser WebAssembly without pthread/shared memory.

This is build infrastructure only. Docker, when used, is only a reproducible CI compiler environment; the shipped Reborn Office runtime remains browser-native WASM with no native Office backend.

Pinned LibreOffice/core commit: `31eabe1e534a70a2b7d5c39eb31e56a75c17be3b`.

The CI intentionally stops on the first real compile/link blocker and uploads `row-build.log`, `row-build-summary.json`, and any produced `soffice.*` files. No user-facing Reborn package is cut until Writer core can start and round-trip a document.
