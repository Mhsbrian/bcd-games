<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- Copyright 2026 B Honey (Mhsbrian/bcd-games) -->

# Building and looking at BCD on Linux

What works without a Mac, what was measured, and what is still open. Fork-only; upstream builds on a
Mac with `.github/workflows/build-ipa.yml`, which this leaves alone and uses as the reference.

Last measured 2026-11-13 on `BCD 0.1.653`, with Swift 6.4.2 (clang 21) and the iOS 27.1 SDK.

## What the host needs

None of it is installed, changed or reset by anything in this repository.

| Piece | What it is | Used for |
|---|---|---|
| A Swift 6.4 image with xtool's Darwin SDK bundle | `swiftc` and `clang` for Linux, the iOS SDKs and toolchain libraries from an Xcode download, and xtool's `ld64.lld` | compiling and linking for iOS |
| x86Code's `x86sim` | iOS simulator runtimes on x86-64 Linux | screenshots on a simulated iPhone or iPad |
| vphone | a whole virtual iPhone19,4 on iOS 27.1 firmware, with fold poses | everything that depends on the foldable iPhone |

`BCD_XT` names the command that runs its arguments in the Swift image with the current directory
mounted (default `~/ios-toolchain/xt`). `BCD_XSD` names `x86sim` for one device, chosen by
`XS_DEVICE` (default `~/ios-toolchain/xsd`).

Building BCD itself uses an image of its own, made by `tools/linux/bx image` from the Swift image, which
adds the build tools the workflow takes from Homebrew, Rust and rcodesign. `BCD_SDK_HOME` names the home
directory that holds the SDK bundle (default `~/ios-toolchain/home`), mounted read-only.

The SDK and Xcode are Apple's, under Apple's licence, which speaks of Apple-branded computers.
Whether to use them elsewhere is for whoever does. Nothing from them is committed here.

## The preview app

`tools/linux/preview.py` is the Linux counterpart of `tools/ui-preview.py`: the same 120 interface
files and sample data, the same flags and bundle identifier (`com.thebcd69.bcd.preview`), read from
`ui-preview.py` so there is one list.

    tools/linux/preview.py build                      # for x86Code's simulated phones, about 45 s
    tools/linux/preview.py shoot --device pro         # install, open every screen, photograph
    tools/linux/preview.py build --platform device    # an unsigned IPA for a virtual iPhone

Differences from the Mac's preview, all limits of having no Xcode: no compiled asset catalog (the
logo goes in as a loose file, there is no app icon), and the link is done by calling `ld64.lld`
directly, because the compiler's own driver refuses to link for these platforms with this lld.

The preview is never installed on a person's own phone. It is not BCD, and it would spend an App ID.

## Two findings about the simulated phones

**x86Code's `duo` device is not an iPhone Duo.** It is the Duo's screen on the ordinary iOS 27.2
runtime. Every app on it, including a ten-line one built against the iOS 27.1 SDK, is shown in a
375x667 pt window. Changing the Info.plist (orientations, device family, launch screen, scene
manifest, minimum iOS) or the SDK version in the program changes nothing there. Do not read
anything about the real phone from it. Use `pro` and `mini` for ordinary iPhone and iPad sizes.

**vphone is the faithful one.** It runs the phone's own firmware, reports `iPhone19,4`, and folds.

## What decides the compatibility window on the foldable iPhone

Measured on vphone (`iPhone19,4`, iOS 27.1, build 24A94425), unfolded.

One program, with the Info.plist keys BCD ships (`UILaunchScreen` empty, three orientations, device
families 1 and 2, minimum iOS 18.0), installed twice. The only difference is the SDK version in the
main program's `LC_BUILD_VERSION` load command:

| SDK version in the program | What the app is given |
|---|---|
| 26.2 | a 375x667 pt window in the middle of the display; `nativeBounds` 1125x2001 |
| 27.1 | the whole inner display; `nativeBounds` 1398x2034 |

The same with BCD 0.1.653 itself, upstream's own IPA. Its log, as shipped (SDK 26.2):

    [device] model=iPhone19,4 idiom=phone os=iOS Version 27.1 (Build 24A94425) ...
    [device] settings: ... screen=1125x2001@3.0x ...

and with nothing changed but that number (27.1), installed over the first:

    [device] settings: ... screen=1398x2034@3.0x ...

That is the `screen=1125x2001@3.0x` testers sent from real phones (`app/Madeira/BCDFoldable.swift`).
So upstream's inference holds, and more exactly than "built with the iOS 27 SDK": iOS reads the
number in the main program. The data container was kept across the second install (the first run's
log was there as `bcd-log.prev.txt`).

Not measured: a real iPhone Duo, and iOS 27.2. The point sizes vphone reports (466x678 pt at 3x)
depend on how that virtual phone was created and are not the real display's.

`tools/linux/restamp-ipa.py` reads that number from an IPA, and can write a copy with another one.
It is a workaround and says so at length: nothing is rebuilt, and every behaviour iOS keeps for
"apps linked before iOS 27" changes at once in a program compiled against older headers. It refuses
to write an IPA whose identifiers are not BCD's three.

## Building BCD itself

A whole BCD has been built on Linux from this tree: `com.thebcd69.bcd` 0.1.653 (653), its two extensions,
main program stamped SDK 27.1. Installed over upstream's 0.1.653 on vphone it starts, fills the inner
display (`screen=1398x2034@3.0x`), keeps the app's data, and reports its sideload entitlements present
(`increased-memory-limit: true`, `extended-virtual-addressing: true`). No game has been run with it:
vphone has no JIT pairing and no store account. That is for a real phone.

### How

    export BCD_UPSTREAM_IPA=/path/to/BCD-0.1.653.ipa    # a Mac-built BCD of the same build number
    tools/linux/bx image                                 # once: the build image
    git submodule update --init --depth 1 FEX wine dxmt madeira-dock
    git -C dxmt submodule update --init --depth 1        # and FEX's own: see below
    tools/linux/run-workflow.py run                      # build-ipa.yml's steps, in order
    tools/linux/bx python3 tools/linux/package.py        # build-out/BCD-<version>-sdk<sdk>-linux-unsigned.ipa

`tools/linux/run-workflow.py` runs the `run:` scripts of `.github/workflows/build-ipa.yml`, unchanged and
in order, in the build image, with stand-ins on the PATH for commands only a Mac has (`tools/linux/shims`).
The workflow stays the one description of the build. A step that succeeded is remembered and skipped the
next time; `list`, `show N`, `--only N --redo` and `--keep-going` are there for working on one step.
Summed from the steps' own times, a build from nothing is 20 to 30 minutes on a 32-thread machine; it has not been timed as one run.

FEX's submodules: all except its three test-binary repositories and `range-v3`'s documentation branch,
which are large and not built (`git -C FEX submodule update --init --depth 1 External/{fmt,xxhash,range-v3,unordered_dense,rpmalloc,jemalloc_glibc,vixl,zydis,tracy,Vulkan-Headers,drm-headers,Catch2} Source/Common/cpp-optparse`,
then `git -C FEX/External/zydis submodule update --init --depth 1`).

### What stands in for a Mac

Each of these is a named, deliberate difference. None is hidden in a script.

| On a Mac | On Linux | Where |
|---|---|---|
| Apple's clang | The open clang 21 from the Swift image, told the triple, the SDK and the linker. Compiles C with common symbols, as Apple's clang does. | `shims/clang` |
| Apple's `ld` | lld from xtool's SDK bundle. Signs iOS output ad hoc, and links three zero-filled Wine globals that the server and ntdll both define as one, as Apple's linker evidently does (upstream's Mac build links the same sources). The names are printed at every link. | `shims/ld64.lld` |
| `xcodebuild archive` | A reader of `project.pbxproj` that compiles, links, copies and runs what the project's three targets say. Swift is compiled a module at a time; headers are found by `-I`, not a header map. | `tools/linux/xcodebuild.py` |
| `actool` (asset catalog) | **Not done.** `Assets.car` and the icon files are taken from `$BCD_UPSTREAM_IPA`. | `xcodebuild.py` |
| `xcrun metal`, `metallib` | **Not done.** No Linux build of Apple's Metal compiler exists. DXMT's four shaders are handed back as a Mac build of the same build number compiled them, read out of `$BCD_UPSTREAM_IPA`. Right only while those four `.metal` files are unchanged; the tool refuses another build number. | `shims/metal`, `tools/linux/shaders-from-ipa.py` |
| `codesign --sign -` | `rcodesign` (ad hoc, with the sideload entitlements). | `shims/codesign` |
| MoltenVK's Xcode build | **Not done.** The Mac-built library of the pinned version is staged from `$BCD_UPSTREAM_IPA`. | `tools/linux/moltenvk-from-ipa.py` |
| llvm-mingw for macOS | The same release built for Linux, SHA-256 checked. | `tools/linux/fetch-llvm-mingw.sh` |
| `xcrun`, `libtool`, `lipo`, `PlistBuddy`, `plutil`, `ditto`, `dyld_info`, `sysctl`, `brew`, BSD `sed -i ''` | Small stand-ins that do what the build asks of each and refuse anything else. | `tools/linux/shims` |

Apple's Metal Shader Converter library (`app/Madeira/d3d12/libmetalirconverter.dylib`) is not in this
public tree and the build stops without it. `tools/linux/converter-from-ipa.py` takes it out of
`$BCD_UPSTREAM_IPA`. The app's own build signs that library ad hoc, which changes its bytes, so
`build/madeira-d3d12/deps.sh` now also accepts the library exactly as released (releases 0.1.634 and
0.1.653 carry byte-identical copies). It is Apple's, under Apple's agreement
(`app/Madeira/d3d12/NOTICE.txt`), listed in `.gitignore`, and never committed.

### What the Linux build does not have yet

- **MoltenVK from source** (`gl/libMoltenVK.dylib`): upstream builds it with MoltenVK's own Xcode projects.
  Until it is built here, `tools/linux/moltenvk-from-ipa.py` stages the Mac-built library of the pinned
  version (v1.4.2, Apache-2.0, unmodified by BCD) and its licence texts from `$BCD_UPSTREAM_IPA`.
- **`d3d8to9.dll`, `cnc-ddraw.dll`**: their steps refuse because `third-party/` in this public tree lacks
  two files their checksum lists name. Not a Linux matter: the same would happen on a Mac from this tree.
  With the 32-bit `winscard.dll` and three README files, these are the only files upstream's 0.1.653 IPA
  has that this build's does not (1,342 files against 1,336, signatures aside).
- **`7zFM.exe`**: its sources include `CommCtrl.h`, which only a case-insensitive file system finds. The
  tracked program is kept, as the step does on any failure.
- **The workflow's 523 "Check" steps** are not run by default (`--checks` runs them). Of the first 216
  (the ones before the build steps), 152 pass on Linux. Most of the other 64 compile the app's Swift into
  a program for the build machine and need Apple-only frameworks (CryptoKit, security-scoped URLs); a few
  compile engine code with macOS headers or look for files the public tree does not have. The remaining
  307 have not been run here.
- **Microsoft's Visual C++ runtime** is fetched by the workflow into the bundle and left out of the
  package, as in upstream's public IPAs; the app downloads it on the device.

### What is not known

- Whether a game runs. Everything up to the app's interface is verified on vphone; the engine is not.
- Whether Apple's clang and the open clang differ in some other default that matters to Wine or FEX. Two
  were found by the link failing (common symbols, merged zero-filled globals); a difference that links
  cleanly would not have shown.
