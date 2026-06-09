#if os(iOS)
import SwiftUI

/// Speaker → tint mapping. Hoisted out of the view so both the transcript column
/// and the follow pill share one source of truth.
enum PodcastSpeakerTint {
    static func color(for idx: Int?, skin: AppSkin) -> Color {
        switch idx {
        case 0: return skin.palette.accent
        case 1: return skin.palette.success
        case 2: return skin.palette.warning
        case 3: return skin.palette.info
        default: return skin.palette.tertiaryText
        }
    }
}
#endif
