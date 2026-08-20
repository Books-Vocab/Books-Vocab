#if os(iOS)
import SwiftUI
import Testing
@testable import BooksAndVocab

struct AppGlassPrimitiveTests {
    @Test("compact action hierarchy keeps primary solid and secondary tones glass")
    func compactActionSurfaceHierarchy() {
        #expect(AppCompactActionButtonStyle.surface(for: .primary) == .solid)
        #expect(AppCompactActionButtonStyle.surface(for: .neutral) == .glass)
        #expect(AppCompactActionButtonStyle.surface(for: .outline) == .glass)
        #expect(AppCompactActionButtonStyle.surface(for: .destructive) == .glass)
    }

    @Test("AppCard defaults to the flat surface")
    func appCardDefaultSurface() {
        #expect(AppCardVariant.defaultVariant == .flat)
    }

    @Test("settings section cards use flat grouping rather than a border shell")
    func settingsSectionSurface() {
        #expect(AppSectionCardStyle.settings(AppSkin.previewNeutral).isFlat)
    }
}
#endif
