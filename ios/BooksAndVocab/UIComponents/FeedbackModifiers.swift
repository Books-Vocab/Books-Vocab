import SwiftUI

enum AppFeedbackEvent: Equatable {
    case selection
    case impactLight
    case success
    case warning
    case error

    var sensoryFeedback: SensoryFeedback {
        switch self {
        case .selection:
            return .selection
        case .impactLight:
            return .impact(weight: .light)
        case .success:
            return .success
        case .warning:
            return .warning
        case .error:
            return .error
        }
    }

    var sound: FeedbackSound {
        switch self {
        case .selection:
            return .tap
        case .impactLight:
            return .review
        case .success:
            return .success
        case .warning:
            return .warning
        case .error:
            return .error
        }
    }
}

private struct AppFeedbackModifier<Trigger: Equatable>: ViewModifier {
    @Environment(\.feedbackSettingsStore) private var settings
    @Environment(\.feedbackAudioService) private var audioService

    let event: AppFeedbackEvent
    let trigger: Trigger
    let condition: (Trigger, Trigger) -> Bool

    func body(content: Content) -> some View {
        Group {
            if settings.hapticFeedbackEnabled {
                content.sensoryFeedback(
                    event.sensoryFeedback,
                    trigger: trigger,
                    condition: condition
                )
            } else {
                content
            }
        }
        .onChange(of: trigger) { oldValue, newValue in
            guard settings.soundFeedbackEnabled, condition(oldValue, newValue) else { return }
            audioService.play(event.sound)
        }
    }
}

extension View {
    func appFeedback<Trigger: Equatable>(
        _ event: AppFeedbackEvent,
        trigger: Trigger,
        condition: @escaping (Trigger, Trigger) -> Bool = { _, _ in true }
    ) -> some View {
        modifier(AppFeedbackModifier(event: event, trigger: trigger, condition: condition))
    }
}
