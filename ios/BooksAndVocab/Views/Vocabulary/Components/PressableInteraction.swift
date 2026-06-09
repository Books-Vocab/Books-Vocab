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

/// Lift interaction constant for LiftableButtonStyle.
private enum LiftMetrics {
    static let pressedScale: CGFloat = 1.005
}

/// Subtle lift effect for cards inside NavigationLink/Button.
/// Uses ButtonStyle to read isPressed without adding gestures that conflict with navigation.
struct LiftableButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .appElevation(configuration.isPressed ? .z2 : .z1)
            .scaleEffect(configuration.isPressed ? LiftMetrics.pressedScale : 1)
            .animation(AppMotion.pressFeedback, value: configuration.isPressed)
    }
}

extension ButtonStyle where Self == LiftableButtonStyle {
    static var liftable: LiftableButtonStyle { LiftableButtonStyle() }
}
