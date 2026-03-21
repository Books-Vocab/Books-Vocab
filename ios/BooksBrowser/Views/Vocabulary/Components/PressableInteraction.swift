import SwiftUI

/// Spring-driven press feedback for buttons. Scale down + opacity dim.
/// For cards, use LiftableModifier instead (scale up + shadow).
struct PressableStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.96 : 1)
            .opacity(configuration.isPressed ? 0.85 : 1)
            .animation(AppMotion.pressFeedback, value: configuration.isPressed)
            .sensoryFeedback(.selection, trigger: configuration.isPressed) { _, newValue in newValue }
    }
}

extension ButtonStyle where Self == PressableStyle {
    static var pressable: PressableStyle { PressableStyle() }
}
