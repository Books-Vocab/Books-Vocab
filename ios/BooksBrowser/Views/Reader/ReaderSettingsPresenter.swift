#if os(iOS)
import SwiftUI

// MARK: - Presenter

struct ReaderSettingsPresenter: View {
    @Environment(\.appTheme) var appTheme
    @Environment(\.vocabSkin) var vocabSkin

    struct State {
        let fontSizeText: String
        let canDecreaseFontSize: Bool
        let canIncreaseFontSize: Bool
    }

    struct Bindings {
        let lineHeight: Binding<Double>
        let font: Binding<ReaderFont>
        let theme: Binding<ReaderTheme>
        let underlineOpacity: Binding<Double>
        let showHitTestingDebug: Binding<Bool>
    }

    let state: State
    let bindings: Bindings
    let onDecreaseFontSize: () -> Void
    let onIncreaseFontSize: () -> Void
    let onSelectTheme: (ReaderTheme) -> Void
    let onSelectUnderlineOpacity: (Double) -> Void
    let onDismiss: () -> Void

    let opacityOptions: [(label: String, value: Double)] = [
        ("隱藏", 0.0),
        ("淡", 0.15),
        ("中", 0.35),
        ("深", 0.60)
    ]

    var fontToneLabel: String {
        switch bindings.font.wrappedValue {
        case .serif: "classic"
        case .athelas: "reader"
        case .sans: "clean"
        case .mono: "coded"
        @unknown default: bindings.font.wrappedValue.rawValue
        }
    }

    var body: some View {
        vocabLayout
    }
}

// MARK: - Previews

#Preview("ReaderSettings / Default") {
    AppThemeContainer {
        ReaderSettingsPresenter(
            state: .init(
                fontSizeText: "17pt",
                canDecreaseFontSize: true,
                canIncreaseFontSize: true
            ),
            bindings: .init(
                lineHeight: .constant(1.4),
                font: .constant(.serif),
                theme: .constant(.light),
                underlineOpacity: .constant(0.35),
                showHitTestingDebug: .constant(false)
            ),
            onDecreaseFontSize: {},
            onIncreaseFontSize: {},
            onSelectTheme: { _ in },
            onSelectUnderlineOpacity: { _ in },
            onDismiss: {}
        )
        .padding()
    }
}

#Preview("ReaderSettings / Bounds") {
    AppThemeContainer {
        ReaderSettingsPresenter(
            state: .init(
                fontSizeText: "0.75x",
                canDecreaseFontSize: false,
                canIncreaseFontSize: true
            ),
            bindings: .init(
                lineHeight: .constant(2.5),
                font: .constant(.sans),
                theme: .constant(.dark),
                underlineOpacity: .constant(0.0),
                showHitTestingDebug: .constant(true)
            ),
            onDecreaseFontSize: {},
            onIncreaseFontSize: {},
            onSelectTheme: { _ in },
            onSelectUnderlineOpacity: { _ in },
            onDismiss: {}
        )
    }
    .preferredColorScheme(.dark)
}
#endif
