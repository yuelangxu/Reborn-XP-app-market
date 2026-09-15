#!/usr/bin/env python3
"""Build the one-folder Reborn XP package from an accepted browser runtime.

The resulting ZIP deliberately contains explicit directory entries, ordered
parent-before-child.  Reborn's historical ZIP extractor does not recursively
create missing parents the way Explorer does, so this ordering is part of the
release contract rather than cosmetic metadata.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path, PurePosixPath

APP_DIR = "RebornOfficeWasm"
INSTALL_PATH = "C:/Program Files/RebornOfficeWasm"
ICON_REL = "icon.png"

# Proven 0.10 icon retained so release packaging has no binary source-file
# dependency and reproduces the same recognizable app identity.
ICON_B64 = (
    "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"
)

REQUIRED_RUNTIME = (
    "runtime/soffice.js",
    "runtime/soffice.wasm",
    "runtime/soffice.data",
    "runtime/soffice.data.js.metadata",
    "vendor/zeta.js",
    "row-office-client.js",
    "row-office-view.js",
    "row-office-worker-loader.js",
    "row-office-thread.js",
    "reborn-office.js",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def launcher_action(app_source: str) -> str:
    install_js = json.dumps(INSTALL_PATH)
    icon_js = json.dumps(f"{INSTALL_PATH}/{ICON_REL}")
    return (
        "(async function(){var stage='initialize';try{"
        "var app=null;var registerApp=function(a){app=a;};\n"
        + app_source
        + "\nstage='setup';"
        "if(!app||typeof app.setup!=='function'||typeof app.start!=='function')"
        "throw new Error('Missing embedded Reborn Office entry');"
        "await app.setup();stage='start';"
        "await app.start(Object.assign({},window._tempAppOptions||{},"
        f"{{installPath:{install_js},icon:{icon_js}}}));"
        "}catch(e){console.error('[ROW release '+stage+']',e);"
        "var s=String(e&&e.stack||e&&e.message||e)"
        ".replace(/[&<>]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});"
        "if(typeof dialogHandler!=='undefined')dialogHandler.spawnDialog({"
        "icon:'error',title:'Reborn Office · '+stage,text:s});"
        "}})();"
    )


def ensure_runtime(runtime: Path) -> None:
    missing = [name for name in REQUIRED_RUNTIME if not (runtime / name).is_file()]
    if missing:
        raise SystemExit("accepted runtime tree is incomplete: " + ", ".join(missing))


def copy_runtime(runtime: Path, app_dir: Path) -> None:
    for src in sorted(p for p in runtime.rglob("*") if p.is_file()):
        rel = src.relative_to(runtime)
        dst = app_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def create_metadata(app_dir: Path, source_sha: str, accepted: bool) -> None:
    files = []
    for path in sorted(p for p in app_dir.rglob("*") if p.is_file()):
        if path.name in {"IMPORT-MANIFEST.json", "SHA256SUMS.txt"}:
            continue
        data = path.read_bytes()
        files.append({
            "path": path.relative_to(app_dir).as_posix(),
            "bytes": len(data),
            "sha256": sha256(data),
        })

    release = {
        "format": "reborn-office-wasm-release-v1",
        "engine": "LibreOffice Technology",
        "execution": "browser-dedicated-worker-single-thread",
        "sharedMemoryRequired": False,
        "nativeBackendRequired": False,
        "dockerRequired": False,
        "vncRequired": False,
        "installPath": INSTALL_PATH,
        "sourceCommit": source_sha,
        "browserAcceptancePassed": bool(accepted),
    }
    (app_dir / "release.json").write_text(
        json.dumps(release, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Recalculate after adding release.json, then audit every package file except
    # the manifests themselves.
    files = []
    sums = []
    for path in sorted(p for p in app_dir.rglob("*") if p.is_file()):
        if path.name in {"IMPORT-MANIFEST.json", "SHA256SUMS.txt"}:
            continue
        data = path.read_bytes()
        rel = path.relative_to(app_dir).as_posix()
        digest = sha256(data)
        files.append({"path": rel, "bytes": len(data), "sha256": digest})
        sums.append(f"{digest}  {rel}")
    manifest = {
        "format": "reborn-import-manifest-v1",
        "root": APP_DIR,
        "fileCount": len(files),
        "files": files,
    }
    (app_dir / "IMPORT-MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (app_dir / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")


def explicit_dirs(root: Path) -> list[Path]:
    dirs = {root}
    for path in root.rglob("*"):
        if path.is_dir():
            dirs.add(path)
        elif path.is_file():
            parent = path.parent
            while parent != root.parent:
                dirs.add(parent)
                if parent == root:
                    break
                parent = parent.parent
    return sorted(dirs, key=lambda p: (len(p.relative_to(root.parent).parts), p.as_posix()))


def make_zip(package_root: Path, zip_path: Path) -> None:
    top = package_root.parent
    dirs = explicit_dirs(package_root)
    files = sorted(p for p in package_root.rglob("*") if p.is_file())
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in dirs:
            rel = path.relative_to(top).as_posix().rstrip("/") + "/"
            info = zipfile.ZipInfo(rel)
            info.external_attr = (0o40755 << 16) | 0x10
            zf.writestr(info, b"")
        for path in files:
            rel = path.relative_to(top).as_posix()
            zf.write(path, rel)


def verify_zip(zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if not names or names[0] != APP_DIR + "/":
            raise SystemExit("ZIP contract failed: root directory is not the first entry")
        seen_dirs: set[str] = set()
        for name in names:
            posix = PurePosixPath(name.rstrip("/"))
            if name.endswith("/"):
                parent = str(posix.parent)
                if parent not in {".", ""} and parent + "/" not in seen_dirs:
                    raise SystemExit(f"ZIP contract failed: parent directory missing before {name}")
                seen_dirs.add(name)
                continue
            parent = str(posix.parent)
            if parent not in {".", ""} and parent + "/" not in seen_dirs:
                raise SystemExit(f"ZIP contract failed: parent directory missing before {name}")
        bad = zf.testzip()
        if bad:
            raise SystemExit(f"ZIP CRC failure: {bad}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runtime_tree", type=Path)
    ap.add_argument("output_dir", type=Path)
    ap.add_argument("--source-sha", default=os.environ.get("GITHUB_SHA", "unknown"))
    ap.add_argument("--accepted", action="store_true")
    args = ap.parse_args()

    runtime = args.runtime_tree.resolve()
    ensure_runtime(runtime)
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    app_dir = out / APP_DIR
    if app_dir.exists():
        shutil.rmtree(app_dir)
    app_dir.mkdir(parents=True)
    copy_runtime(runtime, app_dir)

    app_source = (app_dir / "reborn-office.js").read_text(encoding="utf-8")
    launcher = {
        "action": launcher_action(app_source),
        "icon": f"{INSTALL_PATH}/{ICON_REL}",
    }
    (app_dir / "RebornOfficeWasm.exe").write_text(
        json.dumps(launcher, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    icon = base64.b64decode(ICON_B64)
    if sha256(icon) != "c57498a720e69a704440823ac27b92578414a89b339e42ec7a34c64a77d63ff6":
        raise SystemExit("embedded icon integrity check failed")
    (app_dir / ICON_REL).write_bytes(icon)

    create_metadata(app_dir, args.source_sha, args.accepted)
    zip_path = out / "RebornOfficeWasm-browser-native.zip"
    make_zip(app_dir, zip_path)
    verify_zip(zip_path)

    print(json.dumps({
        "package": str(zip_path),
        "bytes": zip_path.stat().st_size,
        "sha256": sha256(zip_path.read_bytes()),
        "root": str(app_dir),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
