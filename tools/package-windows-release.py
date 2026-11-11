#!/usr/bin/env python3
"""Package the verified x64 DLL under the bindings' runtime filename."""

import argparse
import gzip
import hashlib
import io
import pathlib
import tarfile


LICENSES = ("WalletCore.txt", "WalletCore-3rd-party.txt", "Protobuf.txt",
            "TrezorCrypto.txt", "Boost.txt")
README = pathlib.Path(__file__).resolve().parent.parent / "docs/windows-runtime.md"


def package(source, destination):
    def read(relative):
        path = source / relative
        if (not path.is_file() or source.is_symlink()
                or any((source / parent).is_symlink() for parent in (relative, *relative.parents))):
            raise ValueError(f"Expected a regular file: {relative}")
        return path.read_bytes()

    dll = read(pathlib.Path("shared/bin/TrustWalletCore.dll"))
    pe = int.from_bytes(dll[0x3c:0x40], "little")
    if (dll[:2] != b"MZ" or pe < 0x40 or len(dll) < pe + 26
            or dll[pe:pe + 4] != b"PE\0\0"
            or int.from_bytes(dll[pe + 4:pe + 6], "little") != 0x8664
            or not int.from_bytes(dll[pe + 22:pe + 24], "little") & 0x2000
            or int.from_bytes(dll[pe + 24:pe + 26], "little") != 0x20b):
        raise ValueError("Expected an x64 PE32+ DLL")
    entries = [("libTrustWalletCore.dll", dll), ("README.md", README.read_bytes())]
    entries += [(f"licenses/{name}", read(pathlib.Path("licenses") / name)) for name in LICENSES]
    with destination.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for relative, content in entries:
                    metadata = tarfile.TarInfo(f"windows-x64/{relative}")
                    metadata.size = len(content)
                    metadata.mode = 0o644
                    archive.addfile(metadata, io.BytesIO(content))
    print(f"DLL sha256:{hashlib.sha256(dll).hexdigest()}")
    print(f"{hashlib.sha256(destination.read_bytes()).hexdigest()}  {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=pathlib.Path)
    parser.add_argument("destination", type=pathlib.Path)
    args = parser.parse_args()
    package(args.source, args.destination)
