import Foundation

struct PodcastPlayerCatalogPreview: Equatable {
    let durationSec: TimeInterval
    let currentSec: TimeInterval
    let subtitleSRT: String?
}

#if DEBUG && os(iOS)
import SwiftUI

private struct PodcastPlayerCatalogPreviewKey: EnvironmentKey {
    static let defaultValue: PodcastPlayerCatalogPreview? = nil
}

extension EnvironmentValues {
    var podcastPlayerCatalogPreview: PodcastPlayerCatalogPreview? {
        get { self[PodcastPlayerCatalogPreviewKey.self] }
        set { self[PodcastPlayerCatalogPreviewKey.self] = newValue }
    }
}
#endif
