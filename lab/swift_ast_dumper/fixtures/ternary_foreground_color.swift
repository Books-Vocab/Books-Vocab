// Ternary foreground color (#2449): both branches are palette tokens, so the first match
// must NOT be reported as the token; a plain palette color stays resolved.
import SwiftUI

struct TernaryForeground: View {
    var isSelected = false
    var body: some View {
        Text("x")
            .foregroundStyle(isSelected ? palette.accent : palette.textSecondary)
    }
}

struct PlainForeground: View {
    var body: some View {
        Text("x")
            .foregroundStyle(palette.accent.opacity(0.5))
    }
}
