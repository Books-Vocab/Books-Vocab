// Self-contained fixture for the `.overlay` LAYER model (positioned sub-view overlays).
//
// The histogram's #1 unparsed modifier was `.overlay` ×12 — all of them the
// trailing-closure SUB-VIEW form (`.overlay(alignment:) { badge }` / `.overlay { veil }`),
// since the paren-form `.overlay(Shape().stroke(...))` border idiom already resolves to a
// border via findStrokeCall. This fixture isolates each alignment so the dumper test can
// assert the resolved overlay modifier + the generator's faithful CSS:
//
//   container        → position: relative   (anchors the absolutely-positioned layer)
//   overlay layer     → position:absolute; inset:0; display:flex; align-items/justify per
//                      the SwiftUI Alignment (the layer fills the overlaid view and the
//                      flex box places the child exactly where SwiftUI's alignment would).
//
// Deliberately NOT modeled (honest backlog, asserted as such):
//   - the overlay child's INTERIOR styling (its own font/padding/background) — a separate
//     sub-tree, exactly like stack children are not transpiled by the stack's own decls.
//   - the bare-color tint form `.overlay(palette.x)` (a fill on a Divider, not a layer).
import SwiftUI

// .overlay(alignment: .topTrailing) { subview } → top-right corner layer.
struct OverlayTopTrailing: View {
    var body: some View {
        Text("x")
            .overlay(alignment: .topTrailing) {
                Image(systemName: "waveform")
            }
    }
}

// .overlay(alignment: .bottomLeading) { subview } → bottom-left corner layer.
struct OverlayBottomLeading: View {
    var body: some View {
        Text("x")
            .overlay(alignment: .bottomLeading) {
                Image(systemName: "star.fill")
            }
    }
}

// .overlay(alignment: .bottom) { subview } → bottom-center edge layer.
struct OverlayBottomEdge: View {
    var body: some View {
        Text("x")
            .overlay(alignment: .bottom) {
                Text("pill")
            }
    }
}

// .overlay { subview } (no alignment) → SwiftUI default .center.
struct OverlayCenterDefault: View {
    var body: some View {
        Text("x")
            .overlay {
                Text("veil")
            }
    }
}

// regression: .overlay(Shape().stroke(...)) must STILL resolve to a border, NOT a layer.
struct OverlayStrokeBorder: View {
    var body: some View {
        Text("x")
            .overlay(
                RoundedRectangle(cornerRadius: AppRadius.md, style: .continuous)
                    .stroke(palette.divider, lineWidth: 1)
            )
    }
}

// honesty: .overlay(<bare color>) is a tint fill, NOT a positioned layer → honest unparsed.
struct OverlayColorTint: View {
    var body: some View {
        Text("x")
            .overlay(palette.divider)
    }
}
