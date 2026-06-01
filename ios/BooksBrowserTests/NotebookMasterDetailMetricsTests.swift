import Testing
import CoreGraphics
@testable import BooksBrowser

struct NotebookMasterDetailMetricsTests {
    @Test func activationUsesInlineSelectionOnlyForRegularLayout() {
        #expect(NotebookActivationMode(layoutMode: .regular) == .selectInline)
        #expect(NotebookActivationMode(layoutMode: .compact) == .navigate)
    }

    @Test func detailWidthKeepsReadableRightPaneAndLeftPane() {
        #expect(NotebookMasterDetailMetrics.detailWidth(containerWidth: 700) == 420)
        #expect(NotebookMasterDetailMetrics.detailWidth(containerWidth: 1_200) == 696)
        #expect(NotebookMasterDetailMetrics.detailWidth(containerWidth: 1_600) == 720)
    }
}
