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

/// Subtle lift effect for cards. Scale up + shadow deepen on press.
/// For buttons, use PressableStyle instead (scale down + opacity dim).
struct LiftableModifier: ViewModifier {
    @GestureState private var isPressed = false

    func body(content: Content) -> some View {
        content
            .shadow(
                color: .black.opacity(isPressed ? LiftShadow.pressedOpacity : LiftShadow.idleOpacity),
                radius: isPressed ? LiftShadow.pressedRadius : LiftShadow.idleRadius,
                y: isPressed ? LiftShadow.pressedY : LiftShadow.idleY
            )
            .scaleEffect(isPressed ? LiftShadow.pressedScale : 1)
            .animation(AppMotion.pressFeedback, value: isPressed)
            .simultaneousGesture(
                DragGesture(minimumDistance: 0)
                    .updating($isPressed) { _, state, _ in state = true }
            )
    }
}

extension View {
    func liftable() -> some View {
        modifier(LiftableModifier())
    }
}
