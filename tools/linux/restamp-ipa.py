#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 B Honey (Mhsbrian/bcd-games)
"""Read, or set, the iOS SDK version an IPA's main program says it was built with.

    tools/linux/restamp-ipa.py BCD.ipa                       what the IPA says (changes nothing)
    tools/linux/restamp-ipa.py BCD.ipa --sdk 27.1 -o OUT.ipa a copy whose main program says 27.1

THIS IS A WORKAROUND, NOT A BUILD. iOS decides how to show an app on the foldable iPhone from
the SDK version in the main program's LC_BUILD_VERSION load command: below 27.1 the app gets a
375x667 pt compatibility window on the inner display, from 27.1 the whole display (measured on
iOS 27.1 for iPhone19,4 with one program stamped both ways; see docs/local-build/LINUX.md).
Setting the number does not rebuild anything: the program was still compiled against the older
SDK's headers, and every UIKit and SwiftUI behaviour that iOS keeps for "apps linked before
iOS 27" changes at once, untested. It is for finding out what an iOS 27 SDK build of BCD will
look like before one exists. The real fix is building the app against the iOS 27 SDK.

What it never changes: the bundle identifiers, the version and build number, Info.plist, the
extensions, the entitlements. It refuses to write an IPA whose identifiers are not exactly the
three BCD has (tests/host/check-fork-bundle-ids.py holds the same three for the source tree).
The result is unsigned in effect (the old signature no longer matches the program); a
sideloader signs it again, as it does every IPA.
"""
import argparse
import plistlib
import struct
import sys
import zipfile

MH_MAGIC_64 = 0xFEEDFACF
LC_BUILD_VERSION = 0x32
PLATFORM_IOS = 2
IDENTIFIERS = {"com.thebcd69.bcd", "com.thebcd69.bcd.JITHelper", "com.thebcd69.bcd.MemoryHost"}


def version(packed):
    return f"{packed >> 16}.{(packed >> 8) & 255}" + (f".{packed & 255}" if packed & 255 else "")


def pack(text):
    parts = [int(p) for p in text.split(".")]
    if not 2 <= len(parts) <= 3 or any(not 0 <= p <= 255 for p in parts[1:]) or not 0 < parts[0] < 65536:
        sys.exit(f"restamp-ipa: {text!r} is not a version like 27.1")
    parts += [0] * (3 - len(parts))
    return (parts[0] << 16) | (parts[1] << 8) | parts[2]


def build_version(program):
    """(offset of the sdk field, platform, minimum OS, sdk) of a thin 64-bit Mach-O's LC_BUILD_VERSION."""
    if len(program) < 32 or struct.unpack_from("<I", program, 0)[0] != MH_MAGIC_64:
        sys.exit("restamp-ipa: the main program is not a thin 64-bit Mach-O")
    count = struct.unpack_from("<I", program, 16)[0]
    at = 32
    for _ in range(count):
        command, size = struct.unpack_from("<II", program, at)
        if command == LC_BUILD_VERSION:
            platform, minimum, sdk = struct.unpack_from("<III", program, at + 8)
            return at + 16, platform, minimum, sdk
        at += size
    sys.exit("restamp-ipa: the main program has no LC_BUILD_VERSION")


def bundles(archive):
    """{path of a bundle's Info.plist: its dictionary} for the app and what is inside it."""
    found = {}
    for name in archive.namelist():
        parts = name.split("/")
        if parts[0] == "Payload" and parts[-1] == "Info.plist" and parts[-2].endswith((".app", ".appex")):
            found[name] = plistlib.loads(archive.read(name))
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ipa")
    ap.add_argument("--sdk", help="the SDK version to write, e.g. 27.1")
    ap.add_argument("-o", "--out", help="where the copy goes (required with --sdk; never the input)")
    a = ap.parse_args()
    with zipfile.ZipFile(a.ipa) as archive:
        infos = bundles(archive)
        apps = [n for n in infos if n.count("/") == 2]
        if len(apps) != 1:
            sys.exit(f"restamp-ipa: expected one app in Payload, found {len(apps)}")
        info = infos[apps[0]]
        program_name = apps[0].rsplit("/", 1)[0] + "/" + info["CFBundleExecutable"]
        program = bytearray(archive.read(program_name))
        at, platform, minimum, sdk = build_version(program)
        identifiers = {d["CFBundleIdentifier"] for d in infos.values()}
        print(f"{info['CFBundleIdentifier']} {info.get('CFBundleShortVersionString')} ({info.get('CFBundleVersion')})")
        print(f"  identifiers: {', '.join(sorted(identifiers))}")
        print(f"  main program: platform {platform}, minimum iOS {version(minimum)}, built with SDK {version(sdk)}")
        if not a.sdk:
            return
        if not a.out or a.out == a.ipa:
            sys.exit("restamp-ipa: --sdk needs -o OUT.ipa, a different file from the input")
        if platform != PLATFORM_IOS:
            sys.exit(f"restamp-ipa: the main program is for platform {platform}, not iOS")
        if identifiers != IDENTIFIERS:
            sys.exit("restamp-ipa: this IPA's identifiers are not BCD's three; an install would register new App IDs")
        struct.pack_into("<I", program, at, pack(a.sdk))
        with zipfile.ZipFile(a.out, "w") as out:
            for item in archive.infolist():
                data = bytes(program) if item.filename == program_name else archive.read(item.filename)
                out.writestr(item, data, compress_type=item.compress_type)
    with zipfile.ZipFile(a.out) as written:
        _, _, _, now = build_version(written.read(program_name))
        after = {d["CFBundleIdentifier"] for d in bundles(written).values()}
    if after != IDENTIFIERS or version(now) != version(pack(a.sdk)):
        sys.exit("restamp-ipa: the copy did not come out as asked; do not install it")
    print(f"  wrote {a.out}: main program now says SDK {version(now)}; identifiers, version and build unchanged")


if __name__ == "__main__":
    main()
