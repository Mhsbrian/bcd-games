// SPDX-License-Identifier: GPL-3.0-only
// Copyright 2026 thebcd69 (BCD)
// BCD Material: additional terms under GPL-3.0 section 7 apply; see LICENSE-BCD.md.
// Modified 2026-11-13 in the Mhsbrian/bcd-games fork (not the official BCD): the stage takes a safe area (the outer display's status strip).

import SwiftUI

/// -BCDStage <width>x<height>[:<horizontal>,<vertical>] (tools/ui-preview.py --stage): the interface in a window of that many
/// points, centred on the simulator's screen, with the size classes it names (regular or compact; none given leaves them as the
/// screen has them). It stands in for a window no simulator offers: the foldable iPhone's inner display (890x626 or 626x890 pt,
/// regular x regular) and outer display (678x466 or 466x678 pt, compact), or a Split View half of either. Without the argument
/// the modifier does nothing.
/// A third part gives the window a safe area, in points: `:<top>,<leading>,<bottom>,<trailing>`. The iPhone Duo simulator's outer
/// display keeps a strip 84 pt wide for the clock and the status icons (trailing when upright, leading on its side), so
/// `466x678:compact,regular:0,0,34,84` and `678x466:compact,compact:0,84,34,0` stand in for it on a simulator that is not a Duo.
struct BCDPreviewStage: ViewModifier {
    private static let parsed: (size: CGSize, horizontal: UserInterfaceSizeClass?, vertical: UserInterfaceSizeClass?, safe: EdgeInsets)? = {
        guard let spec = UserDefaults.standard.string(forKey: "BCDStage") else { return nil }
        let parts = spec.split(separator: ":", maxSplits: 2).map(String.init)
        let size = parts[0].lowercased().split(separator: "x").compactMap { Double($0) }
        guard size.count == 2, size[0] > 0, size[1] > 0 else { return nil }
        func word(_ w: Substring) -> UserInterfaceSizeClass? { w == "regular" ? .regular : w == "compact" ? .compact : nil }
        let classes = parts.count > 1 ? parts[1].split(separator: ",") : []
        let edges = parts.count > 2 ? parts[2].split(separator: ",").compactMap { Double($0) } : []
        let safe = edges.count == 4 ? EdgeInsets(top: edges[0], leading: edges[1], bottom: edges[2], trailing: edges[3]) : EdgeInsets()
        return (CGSize(width: size[0], height: size[1]), classes.count == 2 ? word(classes[0]) : nil, classes.count == 2 ? word(classes[1]) : nil, safe)
    }()

    @ViewBuilder func body(content: Content) -> some View {
        if let stage = Self.parsed {
            content
                .safeAreaPadding(stage.safe)
                .environment(\.horizontalSizeClass, stage.horizontal)
                .environment(\.verticalSizeClass, stage.vertical)
                .frame(width: stage.size.width, height: stage.size.height)
                .clipped()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color(white: 0.18))
                .ignoresSafeArea()
        } else {
            content
        }
    }
}
