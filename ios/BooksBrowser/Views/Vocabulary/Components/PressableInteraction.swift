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

/// Shadow constants for LiftableModifier. Extracted per token rules.
private enum LiftShadow {
    static let idleOpacity: Double = 0.06
    static let pressedOpacity: Double = 0.12
    static let idleRadius: CGFloat = 2
    static let pressedRadius: CGFloat = 6
    static let idleY: CGFloat = 1
    static let pressedY: CGFloat = 3
    static let pressedScale: CGFloat = 1.005
}

/// Subtle lift effect for cards inside NavigationLink/Button.
/// Uses ButtonStyle to read isPressed without adding gestures that conflict with navigation.
struct LiftableButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .shadow(
                color: .black.opacity(configuration.isPressed ? LiftShadow.pressedOpacity : LiftShadow.idleOpacity),
                radius: configuration.isPressed ? LiftShadow.pressedRadius : LiftShadow.idleRadius,
                y: configuration.isPressed ? LiftShadow.pressedY : LiftShadow.idleY
            )
            .scaleEffect(configuration.isPressed ? LiftShadow.pressedScale : 1)
            .animation(AppMotion.pressFeedback, value: configuration.isPressed)
    }
}

extension ButtonStyle where Self == LiftableButtonStyle {
    static var liftable: LiftableButtonStyle { LiftableButtonStyle() }
}
