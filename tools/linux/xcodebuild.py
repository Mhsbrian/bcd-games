#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 B Honey (Mhsbrian/bcd-games)
"""The one thing build-ipa.yml asks of xcodebuild, done on Linux: archive app/Madeira.xcodeproj.

    xcodebuild -project app/Madeira.xcodeproj -scheme Madeira -sdk iphoneos -configuration Debug \
        CODE_SIGNING_ALLOWED=NO [NAME=VALUE ...] archive -archivePath build-out/Madeira.xcarchive

(tools/linux/shims/xcodebuild hands that call to this file.) It reads the project file itself, so
what is compiled, linked, copied and run is what the project says: the three targets' sources,
the libraries and frameworks of their link phases, their resources, their script phases and
their copy phases, with the Debug configuration's settings. It is not Xcode. It handles what this
project uses, says so when it meets something else, and differs from Xcode in these ways:

  - Swift is compiled a whole module at a time (Xcode's Debug build compiles file by file).
  - Headers are found through -I for every folder of the project that holds one (Xcode uses a
    header map).
  - The asset catalog is not compiled: there is no actool on Linux. With $BCD_UPSTREAM_IPA set,
    Assets.car and the icon files are taken from that built BCD (the catalog holds the logo and
    the app icon, and changes rarely); without it the app has no icon and the logo goes in as a
    loose file.
  - Nothing is signed (the workflow archives with CODE_SIGNING_ALLOWED=NO as well).

Run inside the build image (tools/linux/bx); the compilers are the stand-ins' (tools/linux/shims).
"""
import concurrent.futures
import hashlib
import json
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

DARWIN = Path(os.environ.get("BCD_DARWIN", "/opt/darwin"))
TOOLCHAIN_LIB = DARWIN / "Developer/Toolchains/XcodeDefault.xctoolchain/usr/lib"
SDK = DARWIN / "Developer/Platforms/iPhoneOS.platform/Developer/SDKs/iPhoneOS.sdk"
PLATFORM_DEV = DARWIN / "Developer/Platforms/iPhoneOS.platform/Developer"


def say(text):
    print(f"xcodebuild(linux): {text}", flush=True)


def die(text):
    sys.exit(f"xcodebuild(linux): error: {text}")


def parse_pbx(text):
    """An old-style (OpenStep) property list, which is what a project.pbxproj is."""
    pos, n = 0, len(text)
    bare = re.compile(r"[A-Za-z0-9_./$:-]+")

    def skip():
        nonlocal pos
        while pos < n:
            if text[pos].isspace():
                pos += 1
            elif text.startswith("/*", pos):
                pos = text.index("*/", pos) + 2
            elif text.startswith("//", pos):
                pos = text.index("\n", pos)
            else:
                return

    def value():
        nonlocal pos
        skip()
        c = text[pos]
        if c == "{":
            pos += 1
            out = {}
            while True:
                skip()
                if text[pos] == "}":
                    pos += 1
                    return out
                key = value()
                skip()
                pos += 1          # =
                out[key] = value()
                skip()
                pos += 1          # ;
        if c == "(":
            pos += 1
            out = []
            while True:
                skip()
                if text[pos] == ")":
                    pos += 1
                    return out
                out.append(value())
                skip()
                if text[pos] == ",":
                    pos += 1
        if c == '"':
            pos += 1
            out = []
            while text[pos] != '"':
                if text[pos] == "\\":
                    pos += 1
                    out.append({"n": "\n", "t": "\t"}.get(text[pos], text[pos]))
                else:
                    out.append(text[pos])
                pos += 1
            pos += 1
            return "".join(out)
        m = bare.match(text, pos)
        pos = m.end()
        return m.group(0)

    return value()


class Project:
    def __init__(self, path, configuration, overrides):
        self.dir = path.resolve().parent                 # SRCROOT
        self.objects = parse_pbx((path / "project.pbxproj").read_text())["objects"]
        self.configuration = configuration
        self.overrides = overrides
        self.parent = {child: key for key, obj in self.objects.items() for child in obj.get("children", [])}
        self.project = next(o for o in self.objects.values() if o["isa"] == "PBXProject")
        self.targets = {o["name"]: o for o in self.objects.values() if o["isa"] == "PBXNativeTarget"}
        self.sdk_version = json.loads((SDK / "SDKSettings.json").read_text())["Version"]

    def path_of(self, ref):
        """A file reference's path, following its groups (relative to SRCROOT, or to the SDK)."""
        parts, key = [], ref
        while key in self.objects:
            obj = self.objects[key]
            if obj.get("path") and obj["isa"] != "PBXProject":
                parts.append(obj["path"])
                tree = obj.get("sourceTree")
                if tree == "SDKROOT":
                    return SDK.joinpath(*reversed(parts))
                if tree == "DEVELOPER_DIR":
                    return Path("/DEVELOPER_DIR").joinpath(*reversed(parts))
                if tree != "<group>":
                    break
            key = self.parent.get(key)
        return self.dir.joinpath(*reversed(parts))

    def configuration_of(self, owner):
        configurations = self.objects[owner["buildConfigurationList"]]["buildConfigurations"]
        return next(self.objects[c] for c in configurations if self.objects[c]["name"] == self.configuration)["buildSettings"]

    def settings(self, target):
        """Project settings, then the target's, then the command line's; [sdk=...] conditions resolved for iphoneos."""
        merged = {}
        for layer in (self.configuration_of(self.project), self.configuration_of(target), self.overrides):
            plain = {k: v for k, v in layer.items() if "[" not in k}
            conditional = {k: v for k, v in layer.items() if "[" in k}
            for group in (plain, conditional):
                for key, value in group.items():
                    name, _, condition = key.partition("[")
                    if condition:
                        m = re.fullmatch(r"sdk=([\w.*]+)\]", condition)
                        if not m:
                            die(f"build setting condition not handled: {key}")
                        if not re.fullmatch(m.group(1).replace(".", r"\.").replace("*", ".*"), f"iphoneos{self.sdk_version}"):
                            continue
                    inherited = merged.get(name, [] if isinstance(value, list) else "")
                    if isinstance(value, list):
                        out = []
                        for item in value:
                            out += (inherited if isinstance(inherited, list) else shlex.split(inherited)) if item == "$(inherited)" else [item]
                        merged[name] = out
                    else:
                        inherited_text = " ".join(inherited) if isinstance(inherited, list) else inherited
                        merged[name] = value.replace("$(inherited)", inherited_text).strip()
        merged.setdefault("TARGET_NAME", target["name"])
        merged.setdefault("SRCROOT", str(self.dir))
        merged.setdefault("PROJECT_DIR", str(self.dir))
        merged.setdefault("DEVELOPMENT_LANGUAGE", "en")
        merged.setdefault("PLATFORM_NAME", "iphoneos")
        merged.setdefault("PRODUCT_BUNDLE_PACKAGE_TYPE", "APPL" if target["productType"].endswith(".application") else "XPC!")
        return merged


def expand(text, settings, depth=0):
    def one(m):
        value = settings.get(m.group(1))
        if value is None:
            die(f"build setting $({m.group(1)}) has no value")
        return " ".join(value) if isinstance(value, list) else value
    out = re.sub(r"\$[({](\w+)[)}]", one, text)
    return expand(out, settings, depth + 1) if out != text and depth < 8 else out


def listed(settings, name):
    value = settings.get(name, [])
    return [expand(v, settings) for v in (value if isinstance(value, list) else shlex.split(value))]


def run(args, log, **kw):
    done = subprocess.run([str(a) for a in args], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)
    log.write("$ " + " ".join(shlex.quote(str(a)) for a in args) + "\n" + done.stdout + "\n")
    log.flush()
    return done


def plist_values(value, settings):
    if isinstance(value, str):
        return expand(value, settings)
    if isinstance(value, list):
        return [plist_values(v, settings) for v in value]
    if isinstance(value, dict):
        return {k: plist_values(v, settings) for k, v in value.items()}
    return value


class Build:
    def __init__(self, project, out, log):
        self.p, self.out, self.log = project, out, log
        self.products = {}
        self.jobs = int(os.environ.get("BCD_JOBS", os.cpu_count() or 4))

    def header_dirs(self):
        dirs = {h.parent for h in self.p.dir.rglob("*.h") if ".xcframework" not in h.parts and "build" not in h.relative_to(self.p.dir).parts[:1]}
        return sorted(dirs)

    def target(self, name):
        if name in self.products:
            return self.products[name]
        target = self.p.targets[name]
        for dependency in target.get("dependencies", []):
            self.target(self.p.objects[self.p.objects[dependency]["target"]]["name"])
        s = self.p.settings(target)
        application = target["productType"] == "com.apple.product-type.application"
        s["PRODUCT_NAME"] = expand(s.get("PRODUCT_NAME", name), s)
        s["EXECUTABLE_NAME"] = s["PRODUCT_NAME"]
        s["PRODUCT_BUNDLE_IDENTIFIER"] = expand(s["PRODUCT_BUNDLE_IDENTIFIER"], s)
        wrapper = self.out / "Products" / (s["PRODUCT_NAME"] + (".app" if application else ".appex"))
        shutil.rmtree(wrapper, ignore_errors=True)
        wrapper.mkdir(parents=True)
        s.update(TARGET_BUILD_DIR=str(wrapper.parent), BUILT_PRODUCTS_DIR=str(wrapper.parent), WRAPPER_NAME=wrapper.name,
                 CODESIGNING_FOLDER_PATH=str(wrapper), FRAMEWORKS_FOLDER_PATH=f"{wrapper.name}/Frameworks",
                 UNLOCALIZED_RESOURCES_FOLDER_PATH=wrapper.name, CONTENTS_FOLDER_PATH=wrapper.name,
                 EXPANDED_CODE_SIGN_IDENTITY="", CODE_SIGNING_ALLOWED=s.get("CODE_SIGNING_ALLOWED", "NO"))
        objects_dir = self.out / "Intermediates" / name
        objects_dir.mkdir(parents=True, exist_ok=True)
        say(f"target {name} ({'application' if application else 'app extension'}, iOS {s['IPHONEOS_DEPLOYMENT_TARGET']}, SDK {self.p.sdk_version})")
        objects, link_inputs = [], []
        for phase_id in target["buildPhases"]:
            phase = self.p.objects[phase_id]
            kind = phase["isa"]
            if kind == "PBXSourcesBuildPhase":
                objects = self.compile(target, phase, s, objects_dir, application)
            elif kind == "PBXFrameworksBuildPhase":
                link_inputs = self.link(target, phase, s, objects, wrapper, application)
                self.info_plist(s, wrapper, application)
            elif kind == "PBXResourcesBuildPhase":
                self.resources(phase, wrapper)
            elif kind == "PBXShellScriptBuildPhase":
                self.script(phase, s)
            elif kind == "PBXCopyFilesBuildPhase":
                self.copy(phase, wrapper)
            else:
                die(f"build phase {kind} is not handled")
        self.products[name] = wrapper
        return wrapper

    def compile(self, target, phase, s, objects_dir, application):
        files = []
        for build_file in phase["files"]:
            entry = self.p.objects[build_file]
            if entry.get("settings"):
                die(f"per-file build settings are not handled ({self.p.path_of(entry['fileRef'])})")
            files.append(self.p.path_of(entry["fileRef"]))
        swift = [f for f in files if f.suffix == ".swift"]
        other = [f for f in files if f.suffix != ".swift"]
        deployment = s["IPHONEOS_DEPLOYMENT_TARGET"]
        triple = f"arm64-apple-ios{deployment}"
        include = [f"-I{d}" for d in self.header_dirs()] + [f"-I{h}" for h in listed(s, "HEADER_SEARCH_PATHS")]
        frameworks = [f"-F{f}" for f in listed(s, "FRAMEWORK_SEARCH_PATHS")]
        defines = [f"-D{d}" for d in listed(s, "GCC_PREPROCESSOR_DEFINITIONS")]
        extension = [] if application else ["-fapplication-extension"]
        objects, failed = [], []
        if swift:
            started = time.time()
            module = s["PRODUCT_NAME"]
            obj = objects_dir / f"{module}.swift.o"
            args = ["swiftc", "-c", "-wmo", "-target", triple, "-sdk", SDK, "-resource-dir", TOOLCHAIN_LIB / "swift",
                    "-I", PLATFORM_DEV / "usr/lib", "-Xfrontend", "-enable-cross-import-overlays",
                    "-swift-version", s.get("SWIFT_VERSION", "5.0").split(".")[0], s.get("SWIFT_OPTIMIZATION_LEVEL", "-Onone"), "-g",
                    "-module-name", module, "-parse-as-library", "-suppress-warnings",
                    "-emit-objc-header-path", objects_dir / f"{module}-Swift.h", "-emit-module-path", objects_dir / f"{module}.swiftmodule"]
            for condition in listed(s, "SWIFT_ACTIVE_COMPILATION_CONDITIONS"):
                args += ["-D", condition]
            if s.get("SWIFT_OBJC_BRIDGING_HEADER"):
                args += ["-import-objc-header", self.p.dir / expand(s["SWIFT_OBJC_BRIDGING_HEADER"], s)]
                for flag in include + defines:
                    args += ["-Xcc", flag]
            if not application:
                args += ["-application-extension"]
            args += frameworks + ["-o", obj] + swift
            done = run(args, self.log, cwd=self.p.dir)
            if done.returncode:
                print("\n".join(line for line in done.stdout.splitlines() if "error:" in line)[:6000])
                die(f"{target['name']}: the Swift module did not compile")
            say(f"  {len(swift)} Swift files, {time.time() - started:.0f} s")
            objects.append(obj)

        def one(source):
            digest = hashlib.sha1(str(source).encode()).hexdigest()[:8]
            obj = objects_dir / f"{source.stem}-{digest}.o"
            cxx = source.suffix in (".mm", ".cpp", ".cc")
            args = ["clang++" if cxx else "clang", f"--target={triple}", "-isysroot", SDK, "-c", source, "-o", obj,
                    "-O" + s.get("GCC_OPTIMIZATION_LEVEL", "0"), "-g", "-fmodules" if not cxx and s.get("CLANG_ENABLE_MODULES") == "YES" else "-fno-modules",
                    f"-I{objects_dir}"] + include + frameworks + defines + extension
            if cxx:
                args += ["-std=" + s.get("CLANG_CXX_LANGUAGE_STANDARD", "gnu++20")]
            if source.suffix in (".m", ".mm") and s.get("CLANG_ENABLE_OBJC_ARC") == "YES":
                args += ["-fobjc-arc"]
            if s.get("GCC_WARN_ABOUT_RETURN_TYPE") == "YES_ERROR":
                args += ["-Werror=return-type"]
            done = run(args, self.log, cwd=self.p.dir)
            return source, obj, done
        started = time.time()
        with concurrent.futures.ThreadPoolExecutor(self.jobs) as pool:
            for source, obj, done in pool.map(one, other):
                if done.returncode:
                    failed.append(source)
                    print("\n".join(line for line in done.stdout.splitlines() if "error" in line)[:3000])
                objects.append(obj)
        if failed:
            die(f"{target['name']}: {len(failed)} C/Objective-C file(s) did not compile: {', '.join(f.name for f in failed)}")
        if other:
            say(f"  {len(other)} C, Objective-C and Objective-C++ files, {time.time() - started:.0f} s")
        return objects

    def link(self, target, phase, s, objects, wrapper, application):
        deployment = s["IPHONEOS_DEPLOYMENT_TARGET"]
        args = ["clang++", f"--target=arm64-apple-ios{deployment}", "-isysroot", SDK, "-o", wrapper / s["EXECUTABLE_NAME"]] + objects
        args += ["-L", TOOLCHAIN_LIB / "swift" / "iphoneos", "-L", SDK / "usr/lib/swift", "-Xlinker", "-rpath", "-Xlinker", "/usr/lib/swift"]
        for rpath in listed(s, "LD_RUNPATH_SEARCH_PATHS"):
            args += ["-Xlinker", "-rpath", "-Xlinker", rpath]
        args += [f"-L{d}" for d in listed(s, "LIBRARY_SEARCH_PATHS")] + [f"-F{d}" for d in listed(s, "FRAMEWORK_SEARCH_PATHS")]
        for build_file in phase["files"]:
            entry = self.p.objects[build_file]
            path = self.p.path_of(entry["fileRef"])
            weak = "Weak" in (entry.get("settings") or {}).get("ATTRIBUTES", [])
            if path.suffix == ".framework":
                args += ["-weak_framework" if weak else "-framework", path.stem]
            elif path.suffix == ".tbd":
                args += ["-l" + path.stem[3:]]
            elif path.suffix == ".a":
                # As Xcode does: -lNAME, found in the reference's own folder or the library search paths (some
                # of this project's references point outside the checkout and resolve through the latter).
                folders = [path.parent] + [Path(d) for d in listed(s, "LIBRARY_SEARCH_PATHS")]
                if not any((folder / path.name).is_file() for folder in folders):
                    die(f"{target['name']} links {path.name}, which is not built")
                if path.is_file():
                    args += [f"-L{path.parent}"]
                args += ["-l" + path.stem[3:]]
            else:
                die(f"link input not handled: {path}")
        args += listed(s, "OTHER_LDFLAGS")
        if s.get("EXPORTED_SYMBOLS_FILE"):
            args += ["-Xlinker", "-exported_symbols_list", "-Xlinker", self.p.dir / expand(s["EXPORTED_SYMBOLS_FILE"], s)]
        if not application:
            args += ["-fapplication-extension", "-e", "_NSExtensionMain"]
        started = time.time()
        done = run(args, self.log, cwd=self.p.dir)
        if done.returncode:
            print("\n".join(done.stdout.splitlines()[:60]))
            die(f"{target['name']}: the link failed")
        say(f"  linked {s['EXECUTABLE_NAME']} ({(wrapper / s['EXECUTABLE_NAME']).stat().st_size} bytes), {time.time() - started:.0f} s")
        return args

    def info_plist(self, s, wrapper, application):
        info = plist_values(plistlib.loads((self.p.dir / expand(s["INFOPLIST_FILE"], s)).read_bytes()), s)
        # What Xcode adds to every Info.plist it processes for a phone.
        info.setdefault("CFBundleSupportedPlatforms", ["iPhoneOS"])
        info["MinimumOSVersion"] = s["IPHONEOS_DEPLOYMENT_TARGET"]
        info["UIDeviceFamily"] = [int(f) for f in s.get("TARGETED_DEVICE_FAMILY", "1").split(",")]
        info.update(DTPlatformName="iphoneos", DTPlatformVersion=self.p.sdk_version, DTSDKName=f"iphoneos{self.p.sdk_version}",
                    DTCompiler="com.apple.compilers.llvm.clang.1_0")
        if application:
            info.setdefault("UIRequiredDeviceCapabilities", ["arm64"])
            (wrapper / "PkgInfo").write_text("APPL????")
        (wrapper / "Info.plist").write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY, sort_keys=False))

    def resources(self, phase, wrapper):
        for build_file in phase["files"]:
            path = self.p.path_of(self.p.objects[build_file]["fileRef"])
            if path.suffix == ".xcassets":
                self.assets(path, wrapper)
            elif path.is_dir():
                shutil.copytree(path, wrapper / path.name, symlinks=True, dirs_exist_ok=True)
            elif path.is_file():
                shutil.copy2(path, wrapper / path.name)
            else:
                die(f"resource {path} does not exist")

    def assets(self, catalog, wrapper):
        ipa = os.environ.get("BCD_UPSTREAM_IPA", "")
        if ipa and Path(ipa).is_file():
            with zipfile.ZipFile(ipa) as archive:
                taken = []
                for name in archive.namelist():
                    m = re.fullmatch(r"Payload/[^/]+\.app/(Assets\.car|AppIcon[^/]*\.png)", name)
                    if m:
                        (wrapper / m.group(1)).write_bytes(archive.read(name))
                        taken.append(m.group(1))
                plist = next(n for n in archive.namelist() if re.fullmatch(r"Payload/[^/]+\.app/Info\.plist", n))
                theirs = plistlib.loads(archive.read(plist))
            info = plistlib.loads((wrapper / "Info.plist").read_bytes())
            for key in ("CFBundleIcons", "CFBundleIcons~ipad"):
                if key in theirs:
                    info[key] = theirs[key]
            (wrapper / "Info.plist").write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY, sort_keys=False))
            say(f"  asset catalog NOT compiled (no actool): {', '.join(sorted(taken))} taken from {Path(ipa).name}")
            return
        for image in catalog.glob("*.imageset/*.png"):
            shutil.copy2(image, wrapper / image.name)
        say("  asset catalog NOT compiled (no actool) and no $BCD_UPSTREAM_IPA: loose images, no app icon")

    def script(self, phase, s):
        env = dict(os.environ)
        env.update({k: (" ".join(v) if isinstance(v, list) else str(v)) for k, v in s.items() if re.fullmatch(r"\w+", k)})
        shell = phase.get("shellPath", "/bin/sh")
        done = run([shell, "-c", phase["shellScript"]], self.log, cwd=self.p.dir, env=env)
        if done.returncode:
            print(done.stdout[-3000:])
            die(f"script phase \"{phase.get('name', '')}\" failed")
        say(f"  script phase \"{phase.get('name', '')}\"")

    def copy(self, phase, wrapper):
        folders = {"13": "PlugIns", "10": "Frameworks", "7": "", "16": ""}
        spec = phase["dstSubfolderSpec"]
        if spec not in folders:
            die(f"copy phase destination {spec} is not handled")
        destination = wrapper / folders[spec] / phase.get("dstPath", "")
        for build_file in phase["files"]:
            ref = self.p.objects[self.p.objects[build_file]["fileRef"]]
            name = ref.get("path", "")
            source = self.out / "Products" / name
            if not source.exists():
                die(f"copy phase \"{phase.get('name')}\": {name} is not a built product")
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, destination / name, symlinks=True, dirs_exist_ok=True)
            say(f"  embedded {name} in {folders[spec] or '.'}")


def main():
    args = sys.argv[1:]
    options, overrides, actions = {}, {}, []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-project", "-scheme", "-sdk", "-configuration", "-archivePath", "-destination", "-derivedDataPath"):
            options[a] = args[i + 1]
            i += 2
        elif re.fullmatch(r"\w+=.*", a, re.S):
            name, _, value = a.partition("=")
            overrides[name] = value
            i += 1
        elif a.startswith("-"):
            die(f"option {a} is not handled")
        else:
            actions.append(a)
            i += 1
    if actions != ["archive"] or options.get("-sdk", "iphoneos") != "iphoneos" or "-archivePath" not in options:
        die("only `-project P -scheme S -sdk iphoneos -configuration C archive -archivePath A` is handled")
    project = Project(Path(options["-project"]), options.get("-configuration", "Release"), overrides)
    archive = Path(options["-archivePath"]).resolve()
    out = archive.parent / "linux-build"
    out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with (out / "build.log").open("w") as log:
        build = Build(project, out, log)
        app = build.target(options["-scheme"])
    shutil.rmtree(archive, ignore_errors=True)
    (archive / "Products" / "Applications").mkdir(parents=True)
    shutil.copytree(app, archive / "Products" / "Applications" / app.name, symlinks=True)
    info = plistlib.loads((app / "Info.plist").read_bytes())
    (archive / "Info.plist").write_bytes(plistlib.dumps({
        "ApplicationProperties": {"ApplicationPath": f"Applications/{app.name}", "CFBundleIdentifier": info["CFBundleIdentifier"],
                                  "CFBundleShortVersionString": info.get("CFBundleShortVersionString"), "CFBundleVersion": info.get("CFBundleVersion")},
        "ArchiveVersion": 2, "Name": options["-scheme"], "SchemeName": options["-scheme"]}))
    say(f"** ARCHIVE SUCCEEDED ** {archive} ({time.time() - started:.0f} s)")


if __name__ == "__main__":
    main()
