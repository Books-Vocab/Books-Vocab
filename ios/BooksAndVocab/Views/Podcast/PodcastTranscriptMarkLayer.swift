#if os(iOS)
import Foundation

enum PodcastTranscriptMarkLayer {
    enum Placement {
        case background
        case overlay
    }

    case vocabHighlight
    case playbackUnderline

    var placement: Placement {
        switch self {
        case .vocabHighlight: return .background
        case .playbackUnderline: return .overlay
        }
    }

    var zIndex: Double {
        switch self {
        case .vocabHighlight: return 0
        case .playbackUnderline: return 1
        }
    }
}
#endif
