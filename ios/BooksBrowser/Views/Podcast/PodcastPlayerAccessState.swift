import Foundation

enum PodcastGateDestination: Equatable {
    case login
    case paywall
}

struct PodcastPlayerAccessState: Equatable {
    let tier: PodcastTier
    let episodeNumber: Int?
    let previewAvailable: Bool

    static func resolve(
        hasProAccess: Bool,
        hasToken: Bool,
        episodeNumber: Int?,
        previewAvailable: Bool
    ) -> PodcastPlayerAccessState {
        PodcastPlayerAccessState(
            tier: PodcastAccess.tier(hasProAccess: hasProAccess, hasToken: hasToken),
            episodeNumber: episodeNumber,
            previewAvailable: previewAvailable
        )
    }

    /// Missing episode rows are a bootstrap state, not an auth failure.
    var playableForTier: Bool {
        guard let episodeNumber else { return true }
        return PodcastAccess.canPlay(
            tier: tier,
            episodeNumber: episodeNumber,
            previewAvailable: previewAvailable
        )
    }

    var isPreviewPlayback: Bool {
        guard let episodeNumber else { return false }
        return PodcastAccess.isPreviewPlayback(
            tier: tier,
            episodeNumber: episodeNumber,
            previewAvailable: previewAvailable
        )
    }

    var gateDestination: PodcastGateDestination {
        tier == .guest ? .login : .paywall
    }
}
