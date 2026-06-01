import Testing
@testable import BooksBrowser

struct ReaderOverlayPanelPlacementTests {
    @Test func compactReaderKeepsBottomCenteredPanel() {
        let placement = ReaderOverlayPanelPlacement(layoutMode: .compact)

        #expect(placement == .centeredBottom)
        #expect(placement.maxWidth == ReaderPresentationMetrics.Overlay.panelMaxWidth)
        #expect(placement.bottomInset == ReaderPresentationMetrics.Overlay.bottomInset)
    }

    @Test func regularReaderUsesTrailingInspectorPanel() {
        let placement = ReaderOverlayPanelPlacement(layoutMode: .regular)

        #expect(placement == .trailingInspector)
        #expect(placement.maxWidth == 460)
        #expect(placement.horizontalInset == AppSpacing.s5)
    }
}
