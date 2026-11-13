#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 B Honey (Mhsbrian/bcd-games)
"""DXMT's four compiled Metal shaders, taken from a built BCD of the same version.

    tools/linux/shaders-from-ipa.py BCD.ipa          writes out/shaders/
    tools/linux/shaders-from-ipa.py BCD.ipa --list   what the IPA's main program holds

THIS IS A STAND-IN FOR A COMPILER LINUX DOES NOT HAVE. build-ipa.yml compiles four shader files
with Apple's Metal compiler (`xcrun metal`, `xcrun metallib`), which exists for macOS and Windows
only:

    dxmt/src/airconv/shaders/air_msad.metal          -> air_msad.h          (an AIR module)
    dxmt/src/airconv/shaders/air_samplepos.metal     -> air_samplepos.h     (an AIR module)
    dxmt/src/airconv/shaders/air_tessellation.metal  -> air_tessellation.h  (an AIR module)
    dxmt/src/dxmt/dxmt_command.metal                 -> dxmt_command.h      (a Metal library)

The results are plain data that DXMT carries inside the app's main program, so a BCD built on a
Mac from the same sources holds exactly the bytes this build needs. This reads them out of such
an IPA into out/shaders/, where the stand-ins for `metal` and `metallib` (tools/linux/shims/metal)
find them: asked to compile one of those four files, they hand back its stored result, so every
place the build calls the compiler (the workflow's step, DXMT's meson build, build/dxmt-ios/build.sh)
runs as written. An AIR module is found by the source file name the compiler recorded in it, the
library by its MTLB container, and each carries its own length.

It is only right while the four .metal files (after the workflow's DXMT patches) are the ones the
IPA was built from. That cannot be proved from the bytes, so the rule is the version: the IPA's
build number must equal docs/local-build/BUILD-NUMBER, or --allow-version says you know why not.
Change a shader, and this stand-in is wrong; the real fix is the Metal compiler (a Mac, or Apple's
Metal Developer Tools for Windows).

Nothing it writes is committed (out/ is ignored).
"""
import argparse
import plistlib
import re
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "out" / "shaders"
AIR = ["air_msad", "air_samplepos", "air_tessellation"]
WRAPPER = b"\xde\xc0\x17\x0b"      # LLVM's bitcode wrapper: magic, version, offset, size, cpu type
BITCODE = b"BC\xc0\xde"


def modules(program):
    """{source name recorded in the module, or None: bytes} for every wrapped bitcode module."""
    found, at = [], 0
    while True:
        at = program.find(WRAPPER, at)
        if at < 0:
            return found
        _, version, offset, size, _ = struct.unpack_from("<IIIII", program, at)
        if version == 0 and offset == 20 and 0 < size < 8 << 20 and program[at + offset:at + offset + 4] == BITCODE:
            blob = program[at:at + offset + size]
            name = re.search(rb"(\w+)\.metal(?=\W|$)", blob)
            found.append((at, name.group(1).decode() if name else None, blob))
        at += 4


def libraries(program):
    """Every Metal library container (MTLB; its own size is at offset 16)."""
    found, at = [], 0
    while True:
        at = program.find(b"MTLB", at)
        if at < 0:
            return found
        size = struct.unpack_from("<Q", program, at + 16)[0]
        if 0 < size < 64 << 20 and at + size <= len(program):
            found.append((at, program[at:at + size]))
        at += 4


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ipa")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--allow-version", action="store_true", help="take the shaders although the IPA's build number is not this tree's")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    with zipfile.ZipFile(a.ipa) as archive:
        plist = next(n for n in archive.namelist() if n.count("/") == 2 and n.endswith(".app/Info.plist"))
        info = plistlib.loads(archive.read(plist))
        program = archive.read(plist.rsplit("/", 1)[0] + "/" + info["CFBundleExecutable"])
    air, libs = modules(program), libraries(program)
    inside = lambda at: any(start <= at < start + len(blob) for start, blob in libs)
    loose = [(at, name, blob) for at, name, blob in air if not inside(at)]
    print(f"{info['CFBundleIdentifier']} {info.get('CFBundleShortVersionString')} ({info.get('CFBundleVersion')})")
    if a.list:
        for at, name, blob in loose:
            print(f"  AIR module   {len(blob):7d} bytes  at {at:#x}  {name or '(no source name)'}")
        for at, blob in libs:
            print(f"  Metal library {len(blob):6d} bytes  at {at:#x}  {blob.count(BITCODE)} functions")
        return
    number = (ROOT / "docs" / "local-build" / "BUILD-NUMBER").read_text()
    number = "".join(line for line in number.splitlines() if not line.startswith("#")).strip()
    if str(info.get("CFBundleVersion")) != number and not a.allow_version:
        sys.exit(f"shaders-from-ipa: the IPA is build {info.get('CFBundleVersion')}, this tree is build {number}; "
                 "its shaders may come from other sources (--allow-version to take them anyway)")
    chosen = {}
    for name in AIR:
        matches = [blob for _, source, blob in loose if source == name]
        if len(matches) != 1:
            sys.exit(f"shaders-from-ipa: expected one AIR module compiled from {name}.metal, found {len(matches)}")
        chosen[name] = matches[0]
    if len(libs) != 1:
        sys.exit(f"shaders-from-ipa: expected one Metal library (dxmt_command), found {len(libs)}")
    chosen["dxmt_command"] = libs[0][1]
    a.out.mkdir(parents=True, exist_ok=True)
    for name, data in chosen.items():
        kind = "metallib" if name == "dxmt_command" else "air"
        (a.out / f"{name}.{kind}").write_bytes(data)
        print(f"  {name}.{kind}  {len(data)} bytes")
    (a.out / "FROM-IPA.txt").write_text(
        f"These shaders were not compiled here. tools/linux/shaders-from-ipa.py took them from\n"
        f"{info['CFBundleIdentifier']} {info.get('CFBundleShortVersionString')} ({info.get('CFBundleVersion')}), because Apple's Metal compiler has no Linux build.\n")


if __name__ == "__main__":
    main()
