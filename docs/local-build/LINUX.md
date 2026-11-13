<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- Copyright 2026 B Honey (Mhsbrian/bcd-games) -->

# Building and looking at BCD on Linux

What works without a Mac, what was measured, and what is still open. Fork-only; upstream builds on a
Mac with `.github/workflows/build-ipa.yml`, which this leaves alone and uses as the reference.

Last measured 2026-11-13 on `BCD 0.1.653`, with Swift 6.4.2 and the iOS 27.1 SDK.

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

## Building BCD itself: where it stands

In the order ANAL-420 set.

1. **The preview app: done.** Builds, runs on x86Code's phones and on vphone.
2. **The app's own sources against the iOS 27 SDK: the Swift half is answered.** All 313 Swift files
   under `app/Madeira` type-check for `arm64-apple-ios18.0` against the iOS 27.1 SDK, with the
   bridging header and `-D BCD_SDK_IOS27_1` (the condition `project.pbxproj` sets for that SDK), with
   no error. The Objective-C and C files were not compiled; they need the FEX submodule's generated
   headers.
3. **The native libraries: not started.** The main program is one 92.6 MB file that has Wine's Unix
   side, FEX and DXMT linked into it, so no change to the app's interface reaches a phone without
   all of them. What the workflow does for them that Linux has no direct answer for:
   - `xcrun -sdk macosx metal`: Apple's Metal shader compiler, for DXMT's shaders.
   - `xcodebuild` for the app itself. Replaceable by the direct compile and link above; the asset
     catalog (`Assets.car`) would need `actool` or to be taken from a built IPA.
   - `app/Madeira/d3d12/libmetalirconverter.dylib`, Apple's Metal Shader Converter library. The
     workflow fails without it, and it is not in this public tree (`tools/export-public.py` leaves
     it out). This blocks a from-source build on a Mac too, not only on Linux.
   The rest is cross-compiling C and C++ with clang, llvm-mingw, meson and cmake, which is work, not
   a wall.
4. **Packaging: not started.** vphone installs an unsigned IPA and signs it in the guest; a person's
   phone gets it through their sideloader.
