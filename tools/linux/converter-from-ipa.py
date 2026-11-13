#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 B Honey (Mhsbrian/bcd-games)
"""Put Apple's Metal Shader Converter library where the build looks for it, from a built BCD.

    tools/linux/converter-from-ipa.py BCD.ipa

build-ipa.yml stops without app/Madeira/d3d12/libmetalirconverter.dylib (build/madeira-d3d12/deps.sh),
and this public tree does not carry it: it is Apple's, not covered by BCD's licence, and
app/Madeira/d3d12/NOTICE.txt says it is distributed inside built packages under Apple's Metal Shader
Converter agreement. This copies it out of such a package into the working tree, and only if its
SHA-256 is the one deps.sh pins. The file is listed in .gitignore and must never be committed; a
build that carries it is distributed under the same agreement (METAL-SHADER-CONVERTER-AGREEMENT.txt).
"""
import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "app" / "Madeira" / "d3d12" / "libmetalirconverter.dylib"


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    pinned = re.search(r'ios_lib_sha="([0-9a-f]{64})"', (ROOT / "build" / "madeira-d3d12" / "deps.sh").read_text())
    if not pinned:
        sys.exit("converter-from-ipa: build/madeira-d3d12/deps.sh no longer pins the library's SHA-256")
    if TARGET.exists() and hashlib.sha256(TARGET.read_bytes()).hexdigest() == pinned.group(1):
        print("converter-from-ipa: already in place, SHA-256 as pinned")
        return
    with zipfile.ZipFile(sys.argv[1]) as archive:
        names = [n for n in archive.namelist() if re.fullmatch(r"Payload/[^/]+\.app/d3d12/libmetalirconverter\.dylib", n)]
        if len(names) != 1:
            sys.exit(f"converter-from-ipa: expected the library once in the IPA, found it {len(names)} times")
        data = archive.read(names[0])
    found = hashlib.sha256(data).hexdigest()
    if found != pinned.group(1):
        sys.exit(f"converter-from-ipa: the IPA's library is {found}, deps.sh pins {pinned.group(1)}; not copied")
    TARGET.write_bytes(data)
    print(f"converter-from-ipa: {TARGET.relative_to(ROOT)} ({len(data)} bytes), SHA-256 as pinned; never commit it")


if __name__ == "__main__":
    main()
