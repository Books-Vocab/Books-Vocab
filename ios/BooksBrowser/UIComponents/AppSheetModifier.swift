import SwiftUI

// MARK: - AppSheetPreset

enum AppSheetPreset {
    /// `.large` detent + drag indicator visible + content interaction scrolls
    case large
    /// `.medium` detent only
    case medium
    /// `.medium` + `.large` detents + drag indicator visible
    case adaptive
}

// MARK: - AppSheetModifier

private struct AppSheetModifier: ViewModifier {
    let preset: AppSheetPreset
#if KG_RUN_CATALOG_SNAPSHOTS
    @State private var contentVisible = true
#else
    @State private var contentVisible = false
#endif

    func body(content: Content) -> some View {
        // Apply opacity/scale to the content BEFORE presentation modifiers so that
        // presentationDetents and related modifiers remain at the outermost position
        // and are not inadvertently broken by the animation chain.
        let animated = content
            .opacity(contentVisible ? 1 : 0)
            .scaleEffect(contentVisible ? 1 : 0.97)
            .onAppear {
#if KG_RUN_CATALOG_SNAPSHOTS
                contentVisible = true
#else
                withAnimation(AppMotion.sheetContentAppear) {
                    contentVisible = true
                }
#endif
            }

        switch preset {
        case .large:
            animated
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
                .presentationContentInteraction(.scrolls)
        case .medium:
            animated
                .presentationDetents([.medium])
        case .adaptive:
            animated
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
    }
}

// MARK: - View Extension

extension View {
    func appSheet(_ preset: AppSheetPreset) -> some View {
        modifier(AppSheetModifier(preset: preset))
    }
}
