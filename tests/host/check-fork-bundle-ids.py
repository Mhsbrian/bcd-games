#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 B Honey (Mhsbrian/bcd-games)
"""The app's identifiers stay the ones an installed BCD already has.

A free Apple ID may register ten App IDs in seven days, and a sideloader registers one for the app
and one for each extension inside it. BCD is three: the app, the JIT helper and the memory host. A
build whose identifiers differ from the installed one's, or that carries one more extension, spends
new App IDs and installs beside the old app instead of over it (the library and settings stay with
the old one). So a change to any of these is a decision, never a side effect:
  1. every build configuration of the app is com.thebcd69.bcd, and the two extensions hang off it;
  2. the Xcode project has one application and two app extensions, no more;
  3. the packaging tool's primary variant is the same identifier.
tests/host/check-fork-bundle-ids.py
"""
import re
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[2]
APP_ID = "com.thebcd69.bcd"
EXPECTED = {APP_ID, APP_ID + ".JITHelper", APP_ID + ".MemoryHost"}
ok = True


def check(what, cond, detail=""):
    global ok
    print(("ok   " if cond else "FAIL ") + what + (("\n     " + str(detail)) if detail and not cond else ""))
    ok = ok and bool(cond)


pbx = (R / "app/Madeira.xcodeproj/project.pbxproj").read_text()
bases = re.findall(r"\bMADEIRA_BUNDLE_IDENTIFIER = ([^;]+);", pbx)
check("every configuration sets the app's identifier to " + APP_ID, bases and set(bases) == {APP_ID}, bases)
raw = [v.strip('"') for v in re.findall(r"\bPRODUCT_BUNDLE_IDENTIFIER = ([^;]+);", pbx)]
resolved = {v.replace("$(MADEIRA_BUNDLE_IDENTIFIER)", APP_ID) for v in raw}
check("the identifiers are the app, its JIT helper and its memory host, and nothing else", resolved == EXPECTED, sorted(resolved))
kinds = re.findall(r'productType = "com\.apple\.product-type\.([^"]+)";', pbx)
check("the project has one application and two app extensions (each extension costs an App ID)",
      sorted(kinds) == ["app-extension", "app-extension", "application"], kinds)
ota = (R / "tools/ota-variants.py").read_text()
check("the packaging tool's primary variant carries the same identifier",
      re.search(r'VARIANTS = \(\("Madeira", "' + re.escape(APP_ID) + r'"\)', ota) is not None)
sys.exit(0 if ok else 1)
