#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 B Honey (Mhsbrian/bcd-games)
"""The layout rules for the iPhone Duo's outer display, and that no other device meets them.

The outer display is 466 x 678 pt, and iOS keeps a strip about 83 pt wide at one side of it for the clock (Xcode 27.2's
iPhone Duo simulator, 2026-11-13): an upright page has 383 pt and a page on its side 595 pt, less than any ordinary iPhone
gives a page on its side (667 pt). The rules below decide from sizes alone, with no model identifier, so they hold in a
LiveContainer window and in the preview app too. Each is a small enum inside the view's own file; this check cuts the four
out, compiles them alone and runs them over the Duo's sizes and over every other device's.

  1. BCDDownloadsColumns  (BCDDownloadsView.swift)  one column under 640 pt
  2. BCDGamePageRoom      (BCDGamePage.swift)       the game page's narrow arrangement under 640 pt
  3. BCDSettingsValueColumn (BCDSettings.swift)     how wide a Settings value may be
  4. BCDSideStrip         (BCDComponents.swift)     what counts as the clock's strip

tests/host/check-duo-layout.py [--require-swift] [--swiftc "<command>"] [--work <dir>]
  --swiftc   the compiler to run (default: xcrun swiftc, else swiftc); e.g. a container's, given a --work it can see
"""
import argparse
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

R = Path(__file__).resolve().parents[2]
APP = R / "app/Madeira"
ap = argparse.ArgumentParser()
ap.add_argument("--require-swift", action="store_true")
ap.add_argument("--swiftc")
ap.add_argument("--work", type=Path)
args = ap.parse_args()
ok = True


def check(what, cond, detail=""):
    global ok
    print(("ok   " if cond else "FAIL ") + what + (("\n     " + str(detail)[-3000:]) if detail and not cond else ""))
    ok = ok and bool(cond)


def cut(source, name):
    """`enum <name> { ... }` out of a file, by its braces."""
    start = source.index(f"enum {name} {{")
    depth, end = 1, source.index("{", start) + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


files = {"BCDDownloadsColumns": "BCDDownloadsView.swift", "BCDGamePageRoom": "BCDGamePage.swift",
         "BCDSettingsValueColumn": "BCDSettings.swift", "BCDSideStrip": "BCDComponents.swift"}
text = {name: (APP / f).read_text() for name, f in files.items()}
rules = {name: cut(text[name], name) for name in files}
check("the four rules are pure: no view, no screen, no model identifier",
      not any(word in rule for rule in rules.values() for word in ("UIScreen", "UIDevice", "BCDFoldable", "View", "@State", "uname")))

# Where each rule is used: once, and the old layout is what it falls back to.
downloads, page, settings, home = text["BCDDownloadsColumns"], text["BCDGamePageRoom"], text["BCDSettingsValueColumn"], (APP / "BCDHomeView.swift").read_text()
check("Downloads is one column on an upright phone or where the rule says so, and an iPad's layout never asks",
      "private var stacked: Bool { layout == .phonePortrait || !BCDDownloadsColumns.sideBySide(width: width, pad: layout == .pad) }" in downloads
      and "if stacked {" in downloads)
check("the game page is narrow only on a phone held sideways",
      "var narrow: Bool { !pad && !upright && BCDGamePageRoom.narrow(width: size.width) }" in page
      and "pad ? 320 : narrow ? BCDGamePageRoom.narrowFacts : (size.width < 700 ? 214 : 236)" in page)
check("a Settings value's width comes from its page's width, never from the row measuring itself",
      "@Environment(\\.bcdSettingsRowWidth) private var rowWidth" in settings
      and "if abs($0 - pageWidth) > 2 { pageWidth = $0 }" in settings
      and settings.count("BCDSettingsValueColumn.width(row: rowWidth, upright: layout == .phonePortrait)") == 1)
check("Home clips its page only beside a side strip", ".bcdClipsAtSideStrip(proxy.safeAreaInsets)" in home
      and "if BCDSideStrip.present(leading: insets.leading, trailing: insets.trailing) { clipShape(BCDSideStripShape()) } else { self }" in text["BCDSideStrip"])

MAIN = r"""
import Foundation
var failed = false
func check(_ what: String, _ ok: Bool, _ detail: String = "") {
    print((ok ? "ok   " : "FAIL ") + what + (ok || detail.isEmpty ? "" : "\n     " + detail))
    if !ok { failed = true }
}

@main struct Run {
    static func main() {
        // A page on its side, in points: the screen's long side less the safe area at both ends.
        let duoSide: CGFloat = 678 - 83
        // iPhone SE (667, no insets), 13 mini (812 - 2x50), 15 (852 - 2x59), 16 Pro (874 - 2x62), 16 Pro Max (956 - 2x62), 17 Pro Max.
        let phonesSide: [CGFloat] = [667, 712, 734, 750, 832, 844]

        // 1. Downloads
        check("Downloads: the Duo's outer display on its side (595 pt) is one column", !BCDDownloadsColumns.sideBySide(width: duoSide, pad: false))
        check("Downloads: every ordinary iPhone on its side keeps two columns", phonesSide.allSatisfy { BCDDownloadsColumns.sideBySide(width: $0, pad: false) })
        check("Downloads: an iPad keeps two columns at any width, and a page not laid out yet (0) changes nothing",
              [320, 507, 595, 744, 1024].allSatisfy { BCDDownloadsColumns.sideBySide(width: $0, pad: true) } && BCDDownloadsColumns.sideBySide(width: 0, pad: false))
        check("Downloads: the queue beside the 300 pt column has at least 300 pt where two columns stay",
              BCDDownloadsColumns.minimum - 40 - 16 - 300 >= 280 && 667 - 40 - 16 - 300 >= 300)

        // 2. The game page
        check("game page: 595 pt is narrow, 667 pt and wider are not, 0 is not", BCDGamePageRoom.narrow(width: duoSide)
              && phonesSide.allSatisfy { !BCDGamePageRoom.narrow(width: $0) } && !BCDGamePageRoom.narrow(width: 0))
        let inner = BCDGamePageRoom.narrowFacts - 32
        check("game page: the facts card has room for \"Program\" and \"64-bit · Direct3D 11\" on one line (55 + 12 + 130 pt of 204)",
              55 + BCDGamePageRoom.narrowFactGap + 130 <= inner, "\(inner)")
        check("game page: the main column keeps at least 260 pt", duoSide - 40 - BCDGamePageRoom.narrowFacts - 22 >= 260)

        // 3. A Settings value
        let upright = BCDSettingsValueColumn.upright, wide = BCDSettingsValueColumn.wide
        // An upright iPhone's rows: the screen less 36 pt (320 to 440 pt screens).
        check("Settings: every upright iPhone's value column is the 150 pt it was", [284, 339, 347, 354, 357, 366, 394, 404].allSatisfy {
            BCDSettingsValueColumn.width(row: CGFloat($0), upright: true) == upright })
        check("Settings: a page that never said its width (0) keeps 150 pt upright and 230 pt otherwise",
              BCDSettingsValueColumn.width(row: 0, upright: true) == upright && BCDSettingsValueColumn.width(row: 0, upright: false) == wide
              && !BCDSettingsValueColumn.valueFirst(row: 0, upright: false))
        check("Settings: the native Duo Settings on its side (rows of 559 pt) gives a value 194 pt and more, never over 230",
              BCDSettingsValueColumn.width(row: 559, upright: true) >= 194 && BCDSettingsValueColumn.width(row: 2000, upright: true) == wide)
        check("Settings: beside the sidebar only the Duo's rows (330 pt) put the value first; an iPhone SE's (403 pt) and wider do not, nor any upright row",
              BCDSettingsValueColumn.valueFirst(row: 330, upright: false) && [403, 448, 470, 520, 700].allSatisfy { !BCDSettingsValueColumn.valueFirst(row: CGFloat($0), upright: false) }
              && !BCDSettingsValueColumn.valueFirst(row: 330, upright: true))

        // 4. The clock's strip
        check("strip: the Duo's outer display has one, upright (trailing 83) and on its side (leading 83)",
              BCDSideStrip.present(leading: 0, trailing: 83) && BCDSideStrip.present(leading: 83, trailing: 0) && BCDSideStrip.present(leading: 83, trailing: 21))
        check("strip: an upright iPhone and an iPad have none (no side insets)", !BCDSideStrip.present(leading: 0, trailing: 0))
        check("strip: an iPhone on its side has none: the same inset on both sides, 44 to 68 pt",
              [44, 47, 50, 59, 62, 68, 83, 90].allSatisfy { !BCDSideStrip.present(leading: CGFloat($0), trailing: CGFloat($0)) })
        check("strip: one side alone under 70 pt is none", !BCDSideStrip.present(leading: 62, trailing: 0) && !BCDSideStrip.present(leading: 0, trailing: 69))
        exit(failed ? 1 : 0)
    }
}
"""

compiler = shlex.split(args.swiftc) if args.swiftc else (["xcrun", "swiftc"] if shutil.which("xcrun") else ["swiftc"] if shutil.which("swiftc") else None)
if not compiler:
    check("a Swift compiler is here to run the rules", not args.require_swift)
else:
    with tempfile.TemporaryDirectory(prefix="bcd-duo-layout-", dir=args.work) as t:
        t = Path(t)
        (t / "Main.swift").write_text(MAIN)
        (t / "Rules.swift").write_text("import Foundation\n\n" + "\n\n".join(rules.values()) + "\n")
        r = subprocess.run(compiler + ["-parse-as-library", "-swift-version", "5", "-o", str(t / "run"), str(t / "Main.swift"), str(t / "Rules.swift")],
                           capture_output=True, text=True)
        check("the four rules compile alone", r.returncode == 0, r.stderr or r.stdout)
        if r.returncode == 0:
            # A container's compiler makes a program for the container: run it there too.
            runner = compiler[:-1] if args.swiftc and len(compiler) > 1 else []
            r = subprocess.run(runner + [str(t / "run")], capture_output=True, text=True)
            print(r.stdout, end="")
            check("the rules hold for the Duo and leave every other device alone", r.returncode == 0, r.stdout + r.stderr)
sys.exit(0 if ok else 1)
