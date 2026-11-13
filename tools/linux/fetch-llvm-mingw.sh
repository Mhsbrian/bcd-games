#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 B Honey (Mhsbrian/bcd-games)
#
# llvm-mingw for a Linux build machine, at the place build-ipa.yml and the build scripts name.
#
# The workflow downloads mstorsjo's llvm-mingw 20260421 built for macOS and refers to it everywhere as
# toolchains/llvm-mingw-20260421-ucrt-macos-universal. This fetches the same release built for Linux
# (same compiler, same Windows libraries; only the machine the tools run on differs), checks its SHA-256
# against the release's published digest, and makes that name a link to it. tools/linux/run-workflow.py
# runs this before the workflow's own fetch step, which then finds the toolchain already there.
set -euo pipefail
cd "$(dirname "$0")/../.."
REL=20260421
NAME=llvm-mingw-$REL-ucrt-ubuntu-22.04-x86_64
SHA=f8b8cce779affeab47bcaec6ce6e9e768b166094a366123ef64b2d0b389cc121
LINK=toolchains/llvm-mingw-$REL-ucrt-macos-universal
[ "$(uname -m)" = x86_64 ] || { echo "fetch-llvm-mingw: this script knows the x86_64 Linux build only" >&2; exit 2; }
mkdir -p toolchains
if [ ! -x "toolchains/$NAME/bin/arm64ec-w64-mingw32-clang++" ]; then
    tmp=$(mktemp)
    trap 'rm -f "$tmp"' EXIT
    curl -fL --retry 3 --retry-delay 5 -o "$tmp" "https://github.com/mstorsjo/llvm-mingw/releases/download/$REL/$NAME.tar.xz"
    echo "$SHA  $tmp" | sha256sum -c - >/dev/null || { echo "fetch-llvm-mingw: the download does not match the release's SHA-256" >&2; exit 1; }
    tar -xJf "$tmp" -C toolchains/
fi
ln -sfn "$NAME" "$LINK"
"$LINK/bin/arm64ec-w64-mingw32-clang++" --version | head -1
