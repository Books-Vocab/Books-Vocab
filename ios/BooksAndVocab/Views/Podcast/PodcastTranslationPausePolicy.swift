#if os(iOS)
enum PodcastTranslationPauseAction: Equatable {
    case none
    case pauseAndMarkAutoPaused
    case resumeAndClearAutoPaused
    case clearAutoPaused
}

enum PodcastTranslationPausePolicy {
    static func action(
        autoPauseEnabled: Bool,
        wasPanelVisible: Bool,
        isPanelVisible: Bool,
        playerState: PodcastPlayerState,
        autoPausedByTranslation: Bool
    ) -> PodcastTranslationPauseAction {
        guard autoPauseEnabled else { return .none }

        if !wasPanelVisible && isPanelVisible {
            return playerState == .playing ? .pauseAndMarkAutoPaused : .none
        }

        if !isPanelVisible && autoPausedByTranslation {
            return playerState == .paused ? .resumeAndClearAutoPaused : .clearAutoPaused
        }

        return .none
    }
}
#endif
