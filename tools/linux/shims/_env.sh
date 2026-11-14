# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 B Honey (Mhsbrian/bcd-games)
# A Linux stand-in for a command build-ipa.yml expects on a Mac (tools/linux/run-workflow.py).
# Where things are in the build image (tools/linux/bx mounts the Darwin SDK bundle at /opt/darwin).
BCD_DARWIN=${BCD_DARWIN:-/opt/darwin}
BCD_PLATFORMS=$BCD_DARWIN/Developer/Platforms
BCD_XCTOOLCHAIN=$BCD_DARWIN/Developer/Toolchains/XcodeDefault.xctoolchain
BCD_LD64=$BCD_DARWIN/toolset/bin/orig/ld64.lld
bcd_sdk_path() {
    case $1 in
        iphoneos*|"") echo "$BCD_PLATFORMS/iPhoneOS.platform/Developer/SDKs/iPhoneOS.sdk" ;;
        iphonesimulator*) echo "$BCD_PLATFORMS/iPhoneSimulator.platform/Developer/SDKs/iPhoneSimulator.sdk" ;;
        macosx*) echo "$BCD_PLATFORMS/MacOSX.platform/Developer/SDKs/MacOSX.sdk" ;;
        /*) echo "$1" ;;
        *) echo "xcrun stand-in: no SDK named $1" >&2; return 1 ;;
    esac
}
bcd_sdk_version() { sed -n 's/.*"Version" *: *"\([0-9.]*\)".*/\1/p' "$(bcd_sdk_path "$1")/SDKSettings.json" | head -1; }
# The directory of the real tools, without this folder, so a stand-in can call what it stands in for.
bcd_real_path() { echo "$PATH" | tr ':' '\n' | grep -v "/tools/linux/shims$" | paste -sd: -; }
