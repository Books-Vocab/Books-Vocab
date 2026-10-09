// Numeric literal forms parseValue must lower faithfully (#2445): underscores, 0x/0b/0o radix,
// float underscores; an unparseable literal (Int overflow) must degrade to unknown, never 0.
import SwiftUI

struct NumericLiterals: View {
    var body: some View {
        Text("x")
            .frame(width: 1_000, height: 0x40, minWidth: 0b101, maxWidth: 0o17)
            .frame(idealWidth: 1_000.5, idealHeight: 99999999999999999999)
    }
}
