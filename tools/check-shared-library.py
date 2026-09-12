#!/usr/bin/env python3
"""Check a native Wallet Core library, then exercise its public C ABI."""

import argparse
import ctypes
import pathlib
import re
import subprocess


def output(*args):
    return subprocess.check_output(args, text=True)


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def check_elf(path, architecture):
    with path.open("rb") as library:
        header = library.read(20)
    machine = {"x64": 62, "arm64": 183}[architecture]
    require(header[:6] == b"\x7fELF\x02\x01", "Expected a little-endian ELF64 library")
    require(int.from_bytes(header[16:18], "little") == 3, "Expected an ELF shared object")
    require(int.from_bytes(header[18:20], "little") == machine, "Wrong ELF architecture")
    dynamic = output("readelf", "-d", str(path))
    require(not re.search(r"\((?:RPATH|RUNPATH)\)", dynamic), "Unexpected runtime search path")
    require("Library soname: [libTrustWalletCore.so]" in dynamic, "Unexpected SONAME")
    needed = re.findall(r"Shared library: \[([^]]+)\]", dynamic)
    allowed = {"libstdc++.so.6", "libm.so.6", "libgcc_s.so.1", "libc.so.6",
               "libpthread.so.0", "libdl.so.2", "librt.so.1",
               "ld-linux-x86-64.so.2" if architecture == "x64" else "ld-linux-aarch64.so.1"}
    require(set(needed) <= allowed, f"Unexpected runtime dependencies: {needed}")
    print(dynamic)
    versions = output("readelf", "--version-info", str(path))
    require(not re.search(r"\bGLIBC_(?:PRIVATE|ABI_\w+)\b", versions),
            "Unexpected private or extended GLIBC ABI requirement")
    for family, limit in (("GLIBC", (2, 34)), ("GLIBCXX", (3, 4, 29))):
        found = {tuple(map(int, item.split(".")))
                 for item in re.findall(rf"\b{family}_([0-9.]+)", versions)}
        require(bool(found), f"No {family} requirements found")
        maximum = max(found)
        require(maximum <= limit, f"{family} requirement exceeds baseline: {maximum} > {limit}")
        print(f"Maximum {family}: {'.'.join(map(str, maximum))}")
    dependencies = output("ldd", str(path))
    require("not found" not in dependencies, dependencies)
    print(dependencies)


def check_api(path):
    library = ctypes.CDLL(str(path))
    for symbol in ("TWHDWalletCreateWithMnemonic", "TWAnySignerSign", "TWDataCopyBytes",
                   "TWStoredKeyStoreWithTemporaryFile", "TWStringUTF8Bytes", "TWStringDelete",
                   "TWCoinTypeConfigurationGetNativeTokenName"):
        getattr(library, symbol)
    library.TWStringUTF8Bytes.argtypes = [ctypes.c_void_p]
    library.TWStringUTF8Bytes.restype = ctypes.c_char_p
    library.TWStringDelete.argtypes = [ctypes.c_void_p]
    library.TWStringDelete.restype = None
    for symbol, expected in (("TWCoinTypeConfigurationGetName", "Arc"),
                             ("TWCoinTypeConfigurationGetID", "arc"),
                             ("TWCoinTypeConfigurationGetSymbol", "USDC"),
                             ("TWCoinTypeConfigurationGetNativeTokenName", "USDC")):
        function = getattr(library, symbol)
        function.argtypes = [ctypes.c_uint32]
        function.restype = ctypes.c_void_p
        string = function(10005042)
        require(bool(string), f"{symbol} returned null")
        try:
            actual = library.TWStringUTF8Bytes(string).decode("utf-8")
            require(actual == expected, f"{symbol}: {actual!r} != {expected!r}")
            print(f"{symbol}(Arc): {actual}")
        finally:
            library.TWStringDelete(string)
    library.TWCoinTypeConfigurationGetDecimals.argtypes = [ctypes.c_uint32]
    library.TWCoinTypeConfigurationGetDecimals.restype = ctypes.c_int
    require(library.TWCoinTypeConfigurationGetDecimals(10005042) == 18, "Wrong Arc decimals")
    print("Public C ABI smoke check passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library", type=pathlib.Path)
    parser.add_argument("--elf-architecture", choices=["x64", "arm64"])
    arguments = parser.parse_args()
    library_path = arguments.library.resolve(strict=True)
    if arguments.elf_architecture:
        check_elf(library_path, arguments.elf_architecture)
    check_api(library_path)
