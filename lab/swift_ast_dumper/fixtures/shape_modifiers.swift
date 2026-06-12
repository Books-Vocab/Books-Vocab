// Self-contained fixture for shape-derived geometry modifiers (clipShape / overlay color).
// Each struct isolates ONE form so the dumper test can assert the resolved IR shape/radius
// without cross-contamination. Values are the deterministic ones the generator can map to
// a CSS var or fixed geometry — bare-var shapes (clipShape(shape)) are deliberately absent
// (they are honest backlog: the shape value is out of component scope).
import SwiftUI

// clipShape(RoundedRectangle(cornerRadius: AppRadius.X)) — already supported; regression anchor.
struct ClipAppRadius: View {
    var body: some View {
        Text("x")
            .clipShape(RoundedRectangle(cornerRadius: AppRadius.md, style: .continuous))
    }
}

// clipShape(RoundedRectangle(cornerRadius: skin.radii.X)) — skin radii path (the gap).
// skin.radii.card == AppRadius.md == --radius-md (SoT: AppSkin+BaseValues.baseRadii).
struct ClipSkinRadiiCard: View {
    var body: some View {
        Text("x")
            .clipShape(RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous))
    }
}

// skin.radii.control == AppRadius.sm == --radius-sm.
struct ClipSkinRadiiControl: View {
    var body: some View {
        Text("x")
            .clipShape(RoundedRectangle(cornerRadius: appSkin.radii.control, style: .continuous))
    }
}

// clipShape(Circle()) → border-radius:50% (deterministic).
struct ClipCircle: View {
    var body: some View {
        Text("x")
            .clipShape(Circle())
    }
}

// clipShape(Capsule(style:.continuous)) — already supported; regression anchor.
struct ClipCapsule: View {
    var body: some View {
        Text("x")
            .clipShape(Capsule(style: .continuous))
    }
}

// .opacity(<literal>) → CSS opacity (deterministic, view-level alpha).
struct OpacityLiteral: View {
    var body: some View {
        Text("x")
            .opacity(0.4)
    }
}

// .opacity(<ternary>) is state-dependent → honest degrade (no single component-scope value).
struct OpacityTernary: View {
    let isActionable = true
    var body: some View {
        Text("x")
            .opacity(isActionable ? 1 : 0.6)
    }
}
