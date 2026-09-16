#!/usr/bin/env python3
"""Build a reproducible one-folder Reborn Office package.

Input must be a browser-runtime tree that has already passed ROW acceptance.
The ZIP format intentionally uses explicit parent directory entries because the
Reborn XP extractor historically did not synthesize missing parent folders.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import zlib
import zipfile
from pathlib import Path, PurePosixPath

APP_DIR = "RebornOfficeWasm"
INSTALL_PATH = "C:/Program Files/RebornOfficeWasm"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
TRANSIENT_RUNTIME_PREFIXES = ("row-acceptance-",)
REQUIRED = (
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


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def make_icon() -> bytes:
    """Generate a dependency-free deterministic 64x64 RGBA Office icon."""
    w = h = 64
    rows = bytearray()
    for y in range(h):
        rows.append(0)  # PNG filter: None
        for x in range(w):
            # Transparent outside a softly clipped blue app tile.
            in_tile = 4 <= x < 60 and 4 <= y < 60
            corner = ((x - 8) ** 2 + (y - 8) ** 2 > 16 and x < 8 and y < 8) or \
                     ((x - 55) ** 2 + (y - 8) ** 2 > 16 and x > 55 and y < 8) or \
                     ((x - 8) ** 2 + (y - 55) ** 2 > 16 and x < 8 and y > 55) or \
                     ((x - 55) ** 2 + (y - 55) ** 2 > 16 and x > 55 and y > 55)
            if not in_tile or corner:
                rgba = (0, 0, 0, 0)
            else:
                rgba = (37, 94, 219, 255)
                # White document sheet.
                if 17 <= x < 48 and 11 <= y < 53:
                    rgba = (247, 249, 255, 255)
                # Folded page corner.
                if 40 <= x < 48 and 11 <= y < 19 and x + y >= 58:
                    rgba = (194, 211, 250, 255)
                # Writer-style blue text rules.
                if 23 <= x < 43 and y in (26, 32, 38, 44):
                    rgba = (37, 94, 219, 255)
                if 23 <= x < 36 and y == 20:
                    rgba = (37, 94, 219, 255)
            rows.extend(rgba)
    raw = bytes(rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(raw, 9))
        + png_chunk(b"IEND", b"")
    )


def launcher_action(app_source: str) -> str:
    install = json.dumps(INSTALL_PATH)
    icon = json.dumps(f"{INSTALL_PATH}/icon.png")
    return (
        "(async function(){var stage='initialize';try{"
        "var app=null;var registerApp=function(a){app=a;};\n"
        + app_source
        + "\nstage='setup';"
        "if(!app||typeof app.setup!=='function'||typeof app.start!=='function')"
        "throw new Error('Missing embedded Reborn Office entry');"
        "await app.setup();stage='start';"
        "await app.start(Object.assign({},window._tempAppOptions||{},"
        f"{{installPath:{install},icon:{icon}}}));"
        "}catch(e){console.error('[ROW release '+stage+']',e);"
        "var s=String(e&&e.stack||e&&e.message||e)"
        ".replace(/[&<>]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});"
        "if(typeof dialogHandler!=='undefined')dialogHandler.spawnDialog({"
        "icon:'error',title:'Reborn Office · '+stage,text:s});"
        "}})();"
    )


def require_runtime(root: Path) -> None:
    missing = [rel for rel in REQUIRED if not (root / rel).is_file()]
    if missing:
        raise SystemExit("runtime tree incomplete: " + ", ".join(missing))


def is_transient_runtime_file(rel: Path) -> bool:
    return any(rel.name.startswith(prefix) for prefix in TRANSIENT_RUNTIME_PREFIXES)


def copy_runtime(src: Path, dst: Path) -> None:
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = path.relative_to(src)
        if is_transient_runtime_file(rel):
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def package_files(app_dir: Path) -> list[dict[str, object]]:
    result = []
    for path in sorted(p for p in app_dir.rglob("*") if p.is_file()):
        if path.name in {"IMPORT-MANIFEST.json", "SHA256SUMS.txt"}:
            continue
        data = path.read_bytes()
        result.append({
            "path": path.relative_to(app_dir).as_posix(),
            "bytes": len(data),
            "sha256": digest(data),
        })
    return result


def write_metadata(app_dir: Path, source_sha: str, accepted: bool) -> None:
    release = {
        "format": "reborn-office-wasm-release-v2",
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
        json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    files = package_files(app_dir)
    (app_dir / "IMPORT-MANIFEST.json").write_text(
        json.dumps({
            "format": "reborn-import-manifest-v2",
            "root": APP_DIR,
            "fileCount": len(files),
            "files": files,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (app_dir / "SHA256SUMS.txt").write_text(
        "".join(f"{item['sha256']}  {item['path']}\n" for item in files),
        encoding="utf-8",
    )


def directories(app_dir: Path) -> list[Path]:
    found = {app_dir}
    for path in app_dir.rglob("*"):
        parent = path if path.is_dir() else path.parent
        while parent != app_dir.parent:
            found.add(parent)
            if parent == app_dir:
                break
            parent = parent.parent
    return sorted(found, key=lambda p: (len(p.relative_to(app_dir.parent).parts), p.as_posix()))


def zip_info(name: str, directory: bool) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_TIME)
    info.create_system = 3
    if directory:
        info.external_attr = (0o40755 << 16) | 0x10
        info.compress_type = zipfile.ZIP_STORED
    else:
        info.external_attr = 0o100644 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
    return info


def make_zip(app_dir: Path, out_zip: Path) -> None:
    top = app_dir.parent
    if out_zip.exists():
        out_zip.unlink()
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in directories(app_dir):
            name = path.relative_to(top).as_posix().rstrip("/") + "/"
            zf.writestr(zip_info(name, True), b"")
        for path in sorted(p for p in app_dir.rglob("*") if p.is_file()):
            name = path.relative_to(top).as_posix()
            zf.writestr(zip_info(name, False), path.read_bytes())


def verify_zip(out_zip: Path) -> None:
    with zipfile.ZipFile(out_zip) as zf:
        names = zf.namelist()
        if not names or names[0] != APP_DIR + "/":
            raise SystemExit("ZIP root directory entry is not first")
        transient = [
            name for name in names
            if is_transient_runtime_file(PurePosixPath(name))
        ]
        if transient:
            raise SystemExit(
                "ZIP contains transient acceptance diagnostics: " + ", ".join(transient)
            )
        seen_dirs: set[str] = set()
        for name in names:
            p = PurePosixPath(name.rstrip("/"))
            parent = str(p.parent)
            if parent not in {".", ""} and parent + "/" not in seen_dirs:
                raise SystemExit(f"ZIP parent missing before child: {name}")
            if name.endswith("/"):
                seen_dirs.add(name)
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
    require_runtime(runtime)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    app_dir = output / APP_DIR
    if app_dir.exists():
        shutil.rmtree(app_dir)
    app_dir.mkdir(parents=True)
    copy_runtime(runtime, app_dir)

    source = (app_dir / "reborn-office.js").read_text(encoding="utf-8")
    (app_dir / "RebornOfficeWasm.exe").write_text(
        json.dumps({
            "action": launcher_action(source),
            "icon": f"{INSTALL_PATH}/icon.png",
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    icon = make_icon()
    if not icon.startswith(b"\x89PNG\r\n\x1a\n"):
        raise SystemExit("generated icon is not a PNG")
    (app_dir / "icon.png").write_bytes(icon)
    write_metadata(app_dir, args.source_sha, args.accepted)

    out_zip = output / "RebornOfficeWasm-browser-native.zip"
    make_zip(app_dir, out_zip)
    verify_zip(out_zip)
    print(json.dumps({
        "package": str(out_zip),
        "bytes": out_zip.stat().st_size,
        "sha256": digest(out_zip.read_bytes()),
        "iconSha256": digest(icon),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
