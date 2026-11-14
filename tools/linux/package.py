#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 B Honey (Mhsbrian/bcd-games)
"""Package the archived app as the fork's one unsigned IPA.

    tools/linux/bx python3 tools/linux/package.py [--archive build-out/Madeira.xcarchive] [--out build-out]

What the workflow's "Package Madeira and Madeira2 unsigned IPAs" step does for its first variant, and only
that one: the app as archived, signed ad hoc with the sideload entitlements exactly as
tools/ota-variants.py's fakesign does it (that function is called, not copied), zipped as Payload/.
The second variant (com.thebcd69.bcd2, "BCD 2") is never made here: an install of it would register three
more App IDs on a free Apple ID (ANAL-420).

Before anything is written the app is checked for what an update over an installed BCD needs: exactly the
three identifiers, a version, and a main program that says which SDK it was built with.
"""
import argparse
import importlib.util
import os
import plistlib
import shutil
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IDENTIFIERS = {"com.thebcd69.bcd", "com.thebcd69.bcd.JITHelper", "com.thebcd69.bcd.MemoryHost"}


def sdk_of(program):
    data = program.read_bytes()[:65536]
    count, at = struct.unpack_from("<I", data, 16)[0], 32
    for _ in range(count):
        command, size = struct.unpack_from("<II", data, at)
        if command == 0x32:
            sdk = struct.unpack_from("<I", data, at + 16)[0]
            return f"{sdk >> 16}.{(sdk >> 8) & 255}"
        at += size
    sys.exit("package: the main program has no LC_BUILD_VERSION")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archive", type=Path, default=ROOT / "build-out" / "Madeira.xcarchive")
    ap.add_argument("--out", type=Path, default=ROOT / "build-out")
    a = ap.parse_args()
    apps = list((a.archive / "Products" / "Applications").glob("*.app"))
    if len(apps) != 1:
        sys.exit(f"package: expected one app in {a.archive}, found {len(apps)}")
    source = apps[0]
    info = plistlib.loads((source / "Info.plist").read_bytes())
    found = {plistlib.loads(p.read_bytes())["CFBundleIdentifier"] for p in [source / "Info.plist", *source.glob("PlugIns/*.appex/Info.plist")]}
    if found != IDENTIFIERS:
        sys.exit(f"package: the app's identifiers are {sorted(found)}, not BCD's three; not packaged")
    extras = [p.name for folder in ("PlugIns", "Extensions") for p in (source / folder).glob("*") if (source / folder).is_dir()]
    if len(extras) != 2:
        sys.exit(f"package: expected two extensions, found {extras}")
    version, build = info["CFBundleShortVersionString"], info["CFBundleVersion"]
    sdk = sdk_of(source / info["CFBundleExecutable"])
    # fakesign calls `codesign`; here that is the stand-in, which signs ad hoc with rcodesign.
    os.environ["PATH"] = str(ROOT / "tools" / "linux" / "shims") + os.pathsep + os.environ.get("PATH", "")
    spec = importlib.util.spec_from_file_location("ota_variants", ROOT / "tools" / "ota-variants.py")
    ota = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ota)
    stage = a.out / "ipa-linux"
    shutil.rmtree(stage, ignore_errors=True)
    app = stage / "Payload" / source.name
    shutil.copytree(source, app, symlinks=True)
    # As upstream's public IPAs (tools/make-alpha-ipa.py): Microsoft's Visual C++ runtime, which the workflow
    # fetches into the bundle, is not passed on; its licence does not let BCD redistribute it, and the app
    # downloads it on the device during setup. The folder stays.
    dropped = [p for p in (app / "x86_64-vcruntime").glob("*.dll")]
    for path in dropped:
        path.unlink()
    ota.fakesign(app)
    target = a.out / f"BCD-{version}-sdk{sdk}-linux-unsigned.ipa"
    target.unlink(missing_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(stage.rglob("*")):
            name = str(path.relative_to(stage))
            if path.is_symlink():
                item = zipfile.ZipInfo(name)
                item.external_attr = 0o120777 << 16
                archive.writestr(item, str(path.readlink()))
            elif path.is_file():
                item = zipfile.ZipInfo.from_file(path, name)
                item.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(item, path.read_bytes())
    print(f"package: {target.relative_to(ROOT) if ROOT in target.parents else target}")
    print(f"  {info['CFBundleIdentifier']} {version} ({build}), built with SDK {sdk}, {target.stat().st_size} bytes")
    print(f"  identifiers: {', '.join(sorted(found))}")
    print(f"  left out: {len(dropped)} Microsoft Visual C++ runtime DLLs (the app fetches them on the device)")


if __name__ == "__main__":
    main()
