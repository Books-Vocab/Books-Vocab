import Foundation

/// Client-side mirror of the backend tiered-access policy (`podcast_access.py`).
///
/// The backend is the *security* boundary — it serves a free caller a separate
/// 3-min `preview.*` object and 403s gated episodes regardless of what the app
/// does. This type is the *UX* boundary: the app knows its own tier, so it can
/// pre-empt (show the login sheet / paywall, lock badges, label previews)
/// instead of optimistically hitting the endpoint and reacting to a 401/403.
/// Keep the predicates in lock-step with `podcast_access.py`.
enum PodcastTier {
    case guest   // no auth token — may browse, may not play
    case free    // authenticated, no active Pro entitlement — ep1 preview only
    case pro     // active Pro entitlement — full access
}

enum PodcastAccess {
    /// Mirrors backend `FREE_PREVIEW_EP_NUM`.
    static let freePreviewEpisodeNumber = 1

    /// Resolve the caller's tier. Mirrors backend `resolve_podcast_tier`:
    /// Pro entitlement wins; otherwise a present token = free, none = guest.
    /// (`hasToken` discriminates guest exactly as the backend does — both free
    /// and pro require a valid token; only the absence of one is a guest.)
    static func tier(hasProAccess: Bool, hasToken: Bool) -> PodcastTier {
        if hasProAccess { return .pro }
        if hasToken { return .free }
        return .guest
    }

    static func isFreePreviewable(episodeNumber: Int) -> Bool {
        episodeNumber == freePreviewEpisodeNumber
    }

    /// May this tier start *any* playback of this episode? (guest never; free
    /// only the previewable episode; pro always.)
    static func canPlay(tier: PodcastTier, episodeNumber: Int) -> Bool {
        switch tier {
        case .pro: return true
        case .free: return isFreePreviewable(episodeNumber: episodeNumber)
        case .guest: return false
        }
    }

    /// Is the playback the free *preview* (capped clip) rather than the full
    /// episode? True only for a free caller on the previewable episode.
    static func isPreviewPlayback(tier: PodcastTier, episodeNumber: Int) -> Bool {
        tier == .free && isFreePreviewable(episodeNumber: episodeNumber)
    }

    /// Should the UI show a Pro lock (cannot play the full episode)? True when
    /// the caller can't play at all, OR can only preview. Used for episode-row
    /// lock badges + the upgrade CTA. Pro is never locked.
    static func showsProLock(tier: PodcastTier, episodeNumber: Int) -> Bool {
        switch tier {
        case .pro: return false
        case .free: return !isFreePreviewable(episodeNumber: episodeNumber)
        case .guest: return true
        }
    }
}
