import Testing
@testable import BooksAndVocab

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

    @Test func compactPanelsKeepBottomSheetChrome() {
        let chrome = ReaderPanelChromeStyle(layoutMode: .compact)

        #expect(chrome == .bottomSheet)
        #expect(chrome.showsDragHandle)
        #expect(chrome.allowsDragDismiss)
        #expect(chrome.contentTopInset == 0)
    }

    @Test func regularPanelsUseInspectorChrome() {
        let chrome = ReaderPanelChromeStyle(layoutMode: .regular)

        #expect(chrome == .floatingInspector)
        #expect(!chrome.showsDragHandle)
        #expect(!chrome.allowsDragDismiss)
        #expect(chrome.contentTopInset == AppSpacing.s4)
    }

    @Test func compactTOCUsesFullWidthSheetContent() {
        let presentation = ReaderTOCPresentation(layoutMode: .compact)

        #expect(presentation.contentMaxWidth == .infinity)
        #expect(presentation.stateCardMaxWidth == .infinity)
        #expect(presentation.horizontalPadding == 0)
    }

    @Test func regularTOCConstrainContentForDesktopScanning() {
        let presentation = ReaderTOCPresentation(layoutMode: .regular)

        #expect(presentation.contentMaxWidth == 560)
        #expect(presentation.stateCardMaxWidth == 440)
        #expect(presentation.horizontalPadding == AppSpacing.s5)
    }

    @Test func compactNotebookPickerUsesFullWidthSheetContent() {
        let presentation = ReaderNotebookPickerPresentation(layoutMode: .compact)

        #expect(presentation.contentMaxWidth == .infinity)
        #expect(presentation.horizontalPadding == 0)
    }

    @Test func regularNotebookPickerConstrainShortChoiceList() {
        let presentation = ReaderNotebookPickerPresentation(layoutMode: .regular)

        #expect(presentation.contentMaxWidth == 500)
        #expect(presentation.horizontalPadding == AppSpacing.s5)
    }
}
