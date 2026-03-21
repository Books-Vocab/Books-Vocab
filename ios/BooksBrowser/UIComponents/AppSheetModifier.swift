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
    @State private var contentVisible = false

    func body(content: Content) -> some View {
        Group {
            switch preset {
            case .large:
                content
                    .presentationDetents([.large])
                    .presentationDragIndicator(.visible)
                    .presentationContentInteraction(.scrolls)
            case .medium:
                content.presentationDetents([.medium])
            case .adaptive:
                content
                    .presentationDetents([.medium, .large])
                    .presentationDragIndicator(.visible)
            }
        }
        .opacity(contentVisible ? 1 : 0)
        .scaleEffect(contentVisible ? 1 : 0.97)
        .onAppear {
            withAnimation(AppMotion.sheetContentAppear) {
                contentVisible = true
            }
        }
    }
}

// MARK: - View Extension

extension View {
    func appSheet(_ preset: AppSheetPreset) -> some View {
        modifier(AppSheetModifier(preset: preset))
    }
}
