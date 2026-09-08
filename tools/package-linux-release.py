#!/usr/bin/env python3
"""Package exactly two architecture-checked shared libraries; never overwrite an archive."""

import argparse
import gzip
import hashlib
import pathlib
import tarfile


def package(source, destination):
    entries = []
    for architecture, machine in (("x64", 62), ("arm64", 183)):
        relative = f"linux-{architecture}/libTrustWalletCore.so"
        path = source / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Expected a regular file: {relative}")
        with path.open("rb") as library:
            header = library.read(20)
        if (header[:6] != b"\x7fELF\x02\x01"
                or int.from_bytes(header[16:18], "little") != 3
                or int.from_bytes(header[18:20], "little") != machine):
            raise ValueError(f"Invalid ELF shared library architecture: {relative}")
        entries.append((relative, path))
    with destination.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for relative, path in entries:
                    metadata = archive.gettarinfo(str(path), arcname=relative)
                    metadata.uid = metadata.gid = metadata.mtime = 0
                    metadata.uname = metadata.gname = ""
                    metadata.mode = 0o644
                    with path.open("rb") as library:
                        archive.addfile(metadata, library)
    print(f"{hashlib.sha256(destination.read_bytes()).hexdigest()}  {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=pathlib.Path)
    parser.add_argument("destination", type=pathlib.Path)
    args = parser.parse_args()
    package(args.source, args.destination)
