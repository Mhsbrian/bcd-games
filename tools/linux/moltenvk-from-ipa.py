#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 B Honey (Mhsbrian/bcd-games)
"""MoltenVK for the app's gl/ folder, taken from a built BCD.

    tools/linux/moltenvk-from-ipa.py BCD.ipa

THIS IS A STAND-IN FOR A BUILD THAT IS NOT DONE ON LINUX YET. build/moltenvk-ios/build.sh builds MoltenVK
v1.4.2 (Apache-2.0) with MoltenVK's own Xcode projects, which need Xcode. Until it is built here from the
same source, this copies what that script stages out of a Mac-built BCD: gl/libMoltenVK.dylib, its version
file, and the four licence texts the bundle must carry with it. It refuses a library whose recorded version
is not the one the build script pins. MoltenVK is used unmodified by BCD, and the copies are not committed
(.gitignore lists them).
"""
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app" / "Madeira"
FILES = ["gl/libMoltenVK.dylib", "gl/libMoltenVK.version", "licenses/MoltenVK-Apache-2.0.txt",
         "licenses/SPIRV-Cross-Apache-2.0.txt", "licenses/SPIRV-Tools-Apache-2.0.txt", "licenses/cereal-BSD-3-Clause.txt"]


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    script = (ROOT / "build" / "moltenvk-ios" / "build.sh").read_text()
    pinned = re.search(r"git clone -q -b (v[\d.]+) https://github.com/KhronosGroup/MoltenVK", script)
    if not pinned:
        sys.exit("moltenvk-from-ipa: build/moltenvk-ios/build.sh no longer names the MoltenVK version it clones")
    with zipfile.ZipFile(sys.argv[1]) as archive:
        app = next(n for n in archive.namelist() if n.count("/") == 2 and n.endswith(".app/"))
        missing = [f for f in FILES if app + f not in archive.namelist()]
        if missing:
            sys.exit(f"moltenvk-from-ipa: the IPA lacks {', '.join(missing)}")
        version = archive.read(app + "gl/libMoltenVK.version").decode().strip()
        if version != pinned.group(1):
            sys.exit(f"moltenvk-from-ipa: the IPA's MoltenVK is {version}, the build script pins {pinned.group(1)}; not copied")
        for name in FILES:
            target = APP / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(app + name))
    print(f"moltenvk-from-ipa: MoltenVK {version} and its four licence texts staged from the IPA (not built here)")


if __name__ == "__main__":
    main()
