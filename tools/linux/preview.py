#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 B Honey (Mhsbrian/bcd-games)
"""Build BCD's preview app on Linux and photograph it on x86Code's simulated phones.

The Linux counterpart of tools/ui-preview.py, which needs a Mac. The same sources (the app's
BCD*.swift interface files that never touch the engine, plus app/BCDPreview), the same flags
and the same bundle identifier; the lists are read from ui-preview.py, so there is one place
that says what the preview is. No engine, no signing material, nothing for a real device.

    tools/linux/preview.py build                         out/linux-preview/BCDPreview.app
    tools/linux/preview.py build --platform device       out/linux-preview/BCDPreview.ipa, unsigned, for a virtual iPhone
    tools/linux/preview.py shoot --device pro            every default screen, both orientations
    tools/linux/preview.py shoot --device pro --screens library,settings --orient landscape --duo
    tools/linux/preview.py shoot --device pro --focus library.game.wc3

What it needs on the host (nothing here installs, changes or resets any of it):

    BCD_XT    a command that runs its arguments in a Swift image holding xtool's Darwin SDK
              bundle, with the current directory mounted          (default ~/ios-toolchain/xt)
    BCD_XSD   x86Code's `x86sim` for one device, named by XS_DEVICE (default ~/ios-toolchain/xsd)

The simulated phone has to be running already; this tool installs, launches and photographs,
and never boots, stops or resets a device (they are shared with other projects).

Three differences from the Mac's preview build, all limits of building without Xcode:
  - the asset catalog is not compiled (no actool): the logo goes in as a loose BCDLogo.png,
    which Image("BCDLogo") finds, and the app has no icon;
  - the link is done by lld called directly (the compiler's own driver cannot link for the
    simulator with this lld), ad-hoc signed by the linker;
  - screenshots come from the simulator's framebuffer as the panel is mounted, so a landscape
    picture is turned here.
"""
import argparse
import importlib.util
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("ui_preview", ROOT / "tools" / "ui-preview.py")
ui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ui)

XT = shlex.split(os.environ.get("BCD_XT", str(Path.home() / "ios-toolchain" / "xt")))
XSD = shlex.split(os.environ.get("BCD_XSD", str(Path.home() / "ios-toolchain" / "xsd")))
# Inside the image: xtool's Darwin SDK bundle (an Xcode's SDKs and toolchain libraries).
BUNDLE = "$HOME/.swiftpm/swift-sdks/darwin.artifactbundle"
MIN_IOS = "18.0"
ART_CACHE = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "bcd-ui-preview-art"

BUILD = r"""
set -eu
A="{bundle}"
P="$A/Developer/Platforms/{platform}.platform/Developer"
T="$A/Developer/Toolchains/XcodeDefault.xctoolchain/usr/lib"
SDK="$P/SDKs/{platform}.sdk"
SDKV=$(sed -n 's/.*"Version" *: *"\([0-9.]*\)".*/\1/p' "$SDK/SDKSettings.json" | head -1)
RT=$(ls "$T"/clang/*/lib/darwin/libclang_rt.{rt}.a | tail -1)
echo "linux-preview: Swift $(swiftc --version 2>/dev/null | head -1 | sed 's/.*version //'), {platform} SDK $SDKV"
swiftc -c -wmo -target arm64-apple-ios{min}{suffix} -sdk "$SDK" -resource-dir "$T/swift" -I "$P/usr/lib" \
  -Xfrontend -enable-cross-import-overlays -suppress-warnings \
  -parse-as-library -module-name BCDPreview -Onone -D BCD_PREVIEW -o "{obj}" @"{sources}"
"$A/toolset/bin/orig/ld64.lld" -arch arm64 -platform_version {ld} {min} "$SDKV" -syslibroot "$SDK" \
  -L "$T/swift/{swiftlib}" -L "$SDK/usr/lib/swift" -L "$P/usr/lib" -rpath /usr/lib/swift \
  -lSystem -lobjc "$RT" -o "{exe}" "{obj}" 2>&1 | grep -v 'does not support linking for platform' || true
test -x "{exe}"
"""


def say(text):
    print(f"linux-preview: {text}", flush=True)


def sources():
    return (sorted(p for p in ui.APP.glob("BCD*.swift") if p.name not in ui.ENGINE_BOUND)
            + sorted(ui.PREVIEW.glob("*.swift")))


PLATFORMS = {
    # The preview for x86Code's simulated phones, and for a real or virtual iPhone (vphone). Never the owner's own
    # phone: the preview is not BCD, and installing it there would spend an App ID.
    "simulator": dict(platform="iPhoneSimulator", rt="iossim", suffix="-simulator", ld="ios-simulator", swiftlib="iphonesimulator", supported="iPhoneSimulator"),
    "device": dict(platform="iPhoneOS", rt="ios", suffix="", ld="ios", swiftlib="iphoneos", supported="iPhoneOS"),
}


def build(out, platform="simulator"):
    """Compile, link and bundle. Paths handed to the image are relative to ROOT, which it mounts."""
    target = PLATFORMS[platform]
    out = out.resolve()
    if ROOT not in out.parents:
        sys.exit("linux-preview: --out must be inside the checkout (the image mounts only that)")
    app = out / "BCDPreview.app"
    shutil.rmtree(app, ignore_errors=True)
    app.mkdir(parents=True)
    files = sources()
    listing = out / "sources.txt"
    listing.write_text("".join(f"{p.relative_to(ROOT)}\n" for p in files))
    rel = lambda p: str(p.relative_to(ROOT))
    script = BUILD.format(bundle=BUNDLE, min=MIN_IOS, obj=rel(out / "BCDPreview.o"), sources=rel(listing),
                          exe=rel(app / "BCDPreview"), **{k: v for k, v in target.items() if k != "supported"})
    started = time.time()
    done = subprocess.run(XT + ["bash", "-c", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (out / "build.log").write_text(done.stdout)
    errors = [line for line in done.stdout.splitlines() if "error" in line]
    if done.returncode or not (app / "BCDPreview").is_file():
        sys.exit("linux-preview: the build failed (" + rel(out / "build.log") + "):\n" + "\n".join(errors[:40] or done.stdout.splitlines()[-40:]))
    print(done.stdout.splitlines()[0])
    info = {
        "CFBundleIdentifier": ui.BUNDLE_ID, "CFBundleExecutable": "BCDPreview", "CFBundleName": "BCD Preview",
        "CFBundleDisplayName": "BCD Preview", "CFBundlePackageType": "APPL", "CFBundleVersion": "1",
        "CFBundleShortVersionString": "1.0", "CFBundleInfoDictionaryVersion": "6.0", "MinimumOSVersion": MIN_IOS,
        "UIDeviceFamily": [1, 2], "CFBundleSupportedPlatforms": [target["supported"]], "UILaunchScreen": {},
        "UIRequiresFullScreen": True,
        "UIApplicationSceneManifest": {"UIApplicationSupportsMultipleScenes": False},
        "UISupportedInterfaceOrientations": ["UIInterfaceOrientationPortrait", "UIInterfaceOrientationLandscapeLeft",
                                             "UIInterfaceOrientationLandscapeRight"],
        "UISupportedInterfaceOrientations~ipad": ["UIInterfaceOrientationPortrait", "UIInterfaceOrientationPortraitUpsideDown",
                                                  "UIInterfaceOrientationLandscapeLeft", "UIInterfaceOrientationLandscapeRight"],
    }
    (app / "Info.plist").write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY))
    (app / "PkgInfo").write_text("APPL????")
    shutil.copy2(ui.APP / "BCDThemes.json", app / "BCDThemes.json")
    shutil.copy2(ui.APP / "Assets.xcassets" / "BCDLogo.imageset" / "BCDLogo.png", app / "BCDLogo.png")
    # The sample games' store pictures: fetched once into the user's cache and copied into the preview app
    # only. They belong to their publishers and are never committed (ui-preview.py does the same on a Mac).
    ui.ART_CACHE = ART_CACHE
    ui.fetch_art()
    for folder in sorted(ART_CACHE.glob("*")):
        pictures = [f for f in folder.iterdir() if f.name in ui.ART_FILES] if folder.is_dir() else []
        if pictures:
            (app / "PreviewArt" / folder.name).mkdir(parents=True, exist_ok=True)
            for f in pictures:
                shutil.copy2(f, app / "PreviewArt" / folder.name / f.name)
    say(f"built {rel(app)} ({len(files)} Swift files, arm64 {platform}, {time.time() - started:.0f} s)")
    if platform == "device":
        ipa = out / "BCDPreview.ipa"
        with zipfile.ZipFile(ipa, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(app.rglob("*")):
                if path.is_file():
                    item = zipfile.ZipInfo.from_file(path, f"Payload/BCDPreview.app/{path.relative_to(app)}")
                    item.external_attr = (0o755 if path.name == "BCDPreview" else 0o644) << 16
                    item.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(item, path.read_bytes())
        say(f"packaged {rel(ipa)} (unsigned; for a virtual iPhone, e.g. vphone's tools/install-ipa.py)")
    return app


def xsd(device, *args, timeout=240, **kw):
    env = dict(os.environ, XS_DEVICE=device)
    return subprocess.run(XSD + list(args), env=env, text=True, timeout=timeout, **kw)


def turn(png):
    """A landscape picture arrives as the panel is mounted (portrait): turn it the way the app stands."""
    try:
        from PIL import Image
    except ImportError:
        for tool in (["magick", str(png), "-rotate", "270", str(png)], ["convert", str(png), "-rotate", "270", str(png)]):
            if shutil.which(tool[0]):
                subprocess.run(tool, check=True)
                return
        say(f"no Pillow or ImageMagick: {png.name} is left as the panel is mounted")
        return
    with Image.open(png) as picture:
        turned = picture.transpose(Image.Transpose.ROTATE_90)
    turned.save(png)


def shoot(app, a):
    out = a.out.resolve()
    shots = out / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    installed = xsd(a.device, "install", str(app), capture_output=True)
    if installed.returncode:
        sys.exit(f"linux-preview: install on {a.device!r} failed; is that device running?\n{(installed.stdout + installed.stderr)[-1500:]}")
    for orient in [o.strip() for o in a.orient.split(",") if o.strip()]:
        for spec in [s.strip() for s in a.screens.split(",") if s.strip()]:
            # The launch arguments are ui-preview.py's (see its shoot()).
            screen, _, ring = spec.partition("@")
            focus = ring or a.focus
            tab, _, section = (screen, "", "") if screen.startswith("game-") else screen.partition(".")
            args = ["-BCDTab", tab, "-BCDOrientation", orient, "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
            args += ["-BCDSection", section] if section else []
            args += ["-BCDFocus", focus] if focus else []
            args += ["-BCDEmpty", "YES"] if a.empty else []
            args += ["-BCDButtons", a.press] if a.press else []
            args += ["-BCDStage", a.stage] if a.stage else []
            args += ["-BCDDuo", "1"] if a.duo else []
            xsd(a.device, "launch", "--terminate-running-process", ui.BUNDLE_ID, *args, capture_output=True, timeout=180)
            time.sleep(a.settle + (1.6 + 0.4 * len(a.press.split(",")) if a.press else 0))
            name = (f"{a.device}--{screen}{'--ring-' + ring if ring else ''}{'--' + a.press.replace(',', '-') if a.press else ''}"
                    f"{'--duo' if a.duo else ''}{'--empty' if a.empty else ''}--{orient}.png")
            taken = xsd(a.device, "screenshot", str(shots / name), "1", capture_output=True)
            if taken.returncode or not (shots / name).is_file():
                say(f"no picture for {name}: {(taken.stdout + taken.stderr)[-300:]}")
                continue
            if orient == "landscape" and not a.as_mounted:
                turn(shots / name)
            print(f"  {name}", flush=True)
    xsd(a.device, "terminate", ui.BUNDLE_ID, capture_output=True)
    say(f"screenshots in {shots.relative_to(ROOT) if ROOT in shots.parents else shots}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["build", "shoot"])
    ap.add_argument("--out", type=Path, default=ROOT / "out" / "linux-preview")
    ap.add_argument("--device", default="pro", help="x86Code device name (XS_DEVICE): pro, mini (duo is not a faithful iPhone Duo: see docs/local-build/LINUX.md)")
    ap.add_argument("--screens", default=",".join(ui.SCREENS))
    ap.add_argument("--orient", default="landscape,portrait")
    ap.add_argument("--focus")
    ap.add_argument("--press")
    ap.add_argument("--stage")
    ap.add_argument("--duo", action="store_true", help="the native iPhone Duo interface (-BCDDuo 1)")
    ap.add_argument("--empty", action="store_true")
    ap.add_argument("--settle", type=float, default=6.0, help="seconds between launch and the picture")
    ap.add_argument("--as-mounted", action="store_true", help="do not turn landscape pictures")
    ap.add_argument("--platform", choices=sorted(PLATFORMS), default="simulator", help="device: an unsigned IPA for a virtual iPhone (build only)")
    ap.add_argument("--no-build", action="store_true", help="shoot the app already in --out")
    a = ap.parse_args()
    app = a.out.resolve() / "BCDPreview.app"
    if a.action == "build" or not a.no_build:
        app = build(a.out, a.platform)
    if a.action == "shoot":
        if a.platform != "simulator":
            sys.exit("linux-preview: shoot photographs the simulator build; install the device IPA on a virtual iPhone yourself")
        shoot(app, a)


if __name__ == "__main__":
    main()
