# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 B Honey (Mhsbrian/bcd-games)
#
# The image BCD's native parts are cross-compiled in on Linux (docs/local-build/LINUX.md): the open Swift
# toolchain's clang and swiftc, plus the build tools build-ipa.yml takes from Homebrew on a Mac. It holds
# nothing of Apple's: the iOS SDK is mounted at run time from wherever the host keeps it (tools/linux/bx).
FROM swift:6.4-noble
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      cmake ninja-build meson python3 python3-pip pkg-config bison flex make autoconf automake libtool \
      nasm yasm gettext gperf texinfo patch file zip unzip xz-utils bzip2 curl ca-certificates rsync \
      cabextract msitools git perl libdigest-sha-perl \
      llvm-18 lld-18 clang-18 python3-mako python3-yaml python3-packaging python3-setuptools glslang-tools \
      libxml2-utils gawk bc cpio wget jq \
      libx11-dev libfreetype-dev python3-venv xxd \
    && rm -rf /var/lib/apt/lists/*
# What `brew --prefix llvm` stands for on Linux (tools/linux/shims/brew): LLVM's binary tools (llvm-dlltool,
# llvm-lipo, ...) without a second clang or lld, so the compiler stays the Swift toolchain's clang 21. Ubuntu's
# clang 18 is too old for the iOS 27 SDK's libc++ headers (__builtin_clzg).
RUN mkdir -p /opt/bcd-llvm/bin && for f in /usr/lib/llvm-18/bin/llvm-*; do ln -s "$f" /opt/bcd-llvm/bin/; done
# build-ipa.yml names /usr/bin/clang and /usr/bin/clang++ outright in places: on a Mac that is Apple's clang,
# which works out the SDK and the linker by itself. Here those two names hand over to the stand-in
# (tools/linux/shims/clang, when tools/linux/bx says where it is), which calls the real compiler as clang-21.
RUN rm /usr/bin/clang /usr/bin/clang++ \
 && printf '#!/bin/sh\n[ -n "$BCD_SHIMS" ] && exec "$BCD_SHIMS/clang" "$@"\nexec /usr/bin/clang-21 "$@"\n' > /usr/bin/clang \
 && printf '#!/bin/sh\n[ -n "$BCD_SHIMS" ] && exec "$BCD_SHIMS/clang++" "$@"\nexec /usr/bin/clang-21 --driver-mode=g++ "$@"\n' > /usr/bin/clang++ \
 && chmod +x /usr/bin/clang /usr/bin/clang++
# /usr/libexec/PlistBuddy is named by its full path in the workflow; it hands over to the stand-in.
RUN mkdir -p /usr/libexec && printf '#!/bin/sh\nexec "${BCD_SHIMS:?PlistBuddy needs tools/linux/bx}/PlistBuddy" "$@"\n' > /usr/libexec/PlistBuddy \
 && chmod +x /usr/libexec/PlistBuddy
# Rust with the iPhone target, for the pairing library (build/rppairing-ios). Anyone may write there, so
# `rustup target add` and cargo's registry work for whichever user tools/linux/bx runs as.
ENV RUSTUP_HOME=/opt/rustup CARGO_HOME=/opt/cargo
RUN curl -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path --profile minimal --target aarch64-apple-ios \
 && chmod -R a+rwX /opt/rustup /opt/cargo
ENV PATH=/opt/cargo/bin:$PATH
# rcodesign (apple-codesign, MPL-2.0): ad-hoc signatures with entitlements, which tools/ota-variants.py asks of
# `codesign` when it packages the unsigned IPA (tools/linux/shims/codesign).
RUN ln -s clang /usr/bin/cc && ln -s clang++ /usr/bin/c++ \
 && cargo install --locked --version 0.29.0 apple-codesign --root /opt/rcodesign \
 && rm -rf /opt/cargo/registry /opt/cargo/git && chmod -R a+rwX /opt/cargo
ENV PATH=/opt/rcodesign/bin:$PATH
