import Foundation
import Testing
@testable import BooksBrowser

@Suite("ResizableDividerClamp")
struct ResizableDividerClampTests {
    @Test func clampsWithinBounds() {
        #expect(ResizableDivider.clamp(500, to: 280...600) == 500)
        #expect(ResizableDivider.clamp(100, to: 280...600) == 280)
        #expect(ResizableDivider.clamp(999, to: 280...600) == 600)
    }
}
