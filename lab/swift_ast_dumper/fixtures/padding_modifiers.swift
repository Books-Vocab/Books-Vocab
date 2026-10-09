// Padding shapes (#2455). One struct per form so the test asserts each in isolation.
import SwiftUI

struct PadLoneEdge: View {
    var body: some View { Text("x").padding(.horizontal) }
}

struct PadEdgeSet: View {
    var body: some View { Text("x").padding([.horizontal, .vertical], 8) }
}

struct PadEdgeSetDefault: View {
    var body: some View { Text("x").padding([.top, .bottom]) }
}

struct PadUnknownShape: View {
    var body: some View { Text("x").padding(edges, 8) }
}

struct PadNamedEdge: View {
    var body: some View { Text("x").padding(.leading, 4) }
}

struct PadAll: View {
    var body: some View { Text("x").padding(12) }
}

struct PadDefault: View {
    var body: some View { Text("x").padding() }
}
