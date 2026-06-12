// Self-contained fixture for cross-symbol custom-ViewModifier resolution.
// Exercises the three expansion fates the resolver must distinguish:
//   1. inlinable pure modifier-chain on `content`   → splice real modifiers (coverage win)
//   2. presentation chain (terminates in .sheet/…)   → scoped (accuracy, not coverage)
//   3. structural wrap (content becomes a child)      → honest unparsed
import SwiftUI

// (1) inlinable: body is a pure modifier chain anchored on `content`.
struct CanvasMod: ViewModifier {
    func body(content: Content) -> some View {
        content.background(appSkin.palette.pageBackground.ignoresSafeArea())
    }
}

// (3) structural wrap: content is embedded as a child of another constructor.
struct WrapMod: ViewModifier {
    func body(content: Content) -> some View {
        AppSectionCard(padding: 0) { content }
    }
}

extension View {
    // (1) ext → modifier(struct) indirection
    func myCanvas() -> some View { modifier(CanvasMod()) }
    // (2) ext → builtin presentation modifier (self.sheet)
    func mySheet(_ flag: Binding<Bool>) -> some View {
        self.sheet(isPresented: flag) { Text("x") }
    }
    // (2) ext → ext (recursive custom) ending in presentation
    func myGate(_ flag: Binding<Bool>) -> some View { mySheet(flag) }
    // (3) ext → modifier(struct) that structurally wraps
    func myWrap() -> some View { modifier(WrapMod()) }
}

struct Demo: View {
    var body: some View {
        VStack {
            Text("hi")
        }
        .myCanvas()
        .myGate(.constant(false))
        .myWrap()
    }
}
