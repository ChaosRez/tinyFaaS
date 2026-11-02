#!/usr/bin/env python3
# I/O-bound: file-system work inside the container's writable root.
#  - 200 small files: open/write 4 KiB/close/stat/unlink (metadata + syscall heavy)
#  - one 4 MiB file: write in 64 KiB chunks, fsync, read back, unlink
# Every step is a system call that gVisor's Sentry intercepts and serves
# through its own VFS (and the Gofer / overlay for the root file system).
import os
import typing

DIR = "/tmp/tf-io-bench"
SMALL = b"x" * 4096
CHUNK = b"y" * 65536


def fn(input: typing.Optional[str], headers: typing.Optional[typing.Dict[str, str]]) -> typing.Optional[str]:
    os.makedirs(DIR, exist_ok=True)
    total = 0
    for i in range(200):
        p = os.path.join(DIR, f"s{i}")
        with open(p, "wb") as f:
            f.write(SMALL)
        total += os.stat(p).st_size
        os.unlink(p)

    p = os.path.join(DIR, "big")
    with open(p, "wb") as f:
        for _ in range(64):
            f.write(CHUNK)
        f.flush()
        os.fsync(f.fileno())
    with open(p, "rb") as f:
        while True:
            b = f.read(65536)
            if not b:
                break
            total += len(b)
    os.unlink(p)
    return str(total)
