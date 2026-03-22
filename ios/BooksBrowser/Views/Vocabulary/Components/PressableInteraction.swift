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

// MARK: - Swipe Action Row

/// Custom swipe-to-reveal actions for rows inside LazyVStack (where native .swipeActions is unavailable).
/// Leading actions appear on right-swipe, trailing on left-swipe. Rubber-bands past threshold.
struct SwipeActionRow<Leading: View, Trailing: View>: ViewModifier {
    let leading: Leading
    let trailing: Trailing

    @State private var offset: CGFloat = 0
    @GestureState private var dragOffset: CGFloat = 0

    private let threshold: CGFloat = 80

    private var isSwiping: Bool { offset != 0 || dragOffset != 0 }

    func body(content: Content) -> some View {
        ZStack {
            if isSwiping {
                HStack {
                    leading
                        .frame(width: threshold)
                    Spacer()
                }

                HStack {
                    Spacer()
                    trailing
                        .frame(width: threshold)
                }
            }

            content
                .offset(x: offset + dragOffset)
                .gesture(
                    DragGesture()
                        .updating($dragOffset) { value, state, _ in
                            let translation = value.translation.width
                            if abs(translation) > threshold {
                                let excess = abs(translation) - threshold
                                let dampened = threshold + excess * 0.3
                                state = translation > 0 ? dampened : -dampened
                            } else {
                                state = translation
                            }
                        }
                        .onEnded { value in
                            let translation = value.translation.width
                            if abs(translation) > threshold {
                                withAnimation(AppMotion.swipeRowSnap) {
                                    offset = translation > 0 ? threshold : -threshold
                                }
                            } else {
                                withAnimation(AppMotion.swipeRowSnap) {
                                    offset = 0
                                }
                            }
                        }
                )
                .overlay {
                    if offset != 0 {
                        Color.clear
                            .contentShape(Rectangle())
                            .onTapGesture {
                                withAnimation(AppMotion.swipeRowSnap) {
                                    offset = 0
                                }
                            }
                    }
                }
        }
        .clipped()
    }
}

extension View {
    /// Vocab-specific swipe-to-reveal actions. Named `vocabSwipeActions` to avoid
    /// shadowing the system `swipeActions(_:allowsFullSwipe:content:)` API.
    func vocabSwipeActions(
        @ViewBuilder leading: () -> some View,
        @ViewBuilder trailing: () -> some View
    ) -> some View {
        modifier(SwipeActionRow(leading: leading(), trailing: trailing()))
    }
}
