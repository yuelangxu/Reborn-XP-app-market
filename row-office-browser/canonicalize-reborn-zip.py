#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import tempfile
import zipfile
from pathlib import PurePosixPath

FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def sort_key(name: str) -> tuple[int, int, str]:
    clean = name.rstrip('/')
    depth = len(PurePosixPath(clean).parts)
    return (0 if name.endswith('/') else 1, depth if name.endswith('/') else 0, name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('zip_path')
    args = ap.parse_args()
    path = os.path.abspath(args.zip_path)

    with zipfile.ZipFile(path, 'r') as src:
        entries = [(info.filename, src.read(info.filename)) for info in src.infolist()]

    # Explicit directories first, shallow to deep, then files lexicographically.
    entries.sort(key=lambda item: sort_key(item[0]))

    directory_names = {name for name, _ in entries if name.endswith('/')}
    for name, _ in entries:
        if name.endswith('/'):
            parent = str(PurePosixPath(name.rstrip('/')).parent)
            if parent not in ('.', '') and parent + '/' not in directory_names:
                raise SystemExit(f'missing explicit parent directory for {name}')
        else:
            parent = str(PurePosixPath(name).parent)
            if parent not in ('.', '') and parent + '/' not in directory_names:
                raise SystemExit(f'missing explicit parent directory for {name}')

    fd, tmp = tempfile.mkstemp(prefix='.row-canonical-', suffix='.zip', dir=os.path.dirname(path))
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as dst:
            for name, data in entries:
                info = zipfile.ZipInfo(name, FIXED_TIME)
                info.create_system = 3
                if name.endswith('/'):
                    info.external_attr = (0o40755 << 16) | 0x10
                    info.compress_type = zipfile.ZIP_STORED
                    dst.writestr(info, b'')
                else:
                    info.external_attr = 0o100644 << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    dst.writestr(info, data)
        with zipfile.ZipFile(tmp, 'r') as check:
            if check.testzip() is not None:
                raise SystemExit('canonical ZIP failed CRC validation')
            names = check.namelist()
            if not names or not names[0].endswith('/'):
                raise SystemExit('canonical ZIP does not start with a root directory entry')
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
