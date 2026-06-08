#if os(iOS)
import Foundation

struct PodcastPlayerLoadPlan: Equatable {
    enum SubtitleSource: Equatable {
        case inline(String)
        case remote(String)
        case unavailable
    }

    let audioURL: URL
    let usesLocalAudio: Bool
    let subtitleSource: SubtitleSource
    let title: String
    let durationSec: Double

    static func make(
        episode: PodcastEpisode,
        fileExists: (String) -> Bool = { FileManager.default.fileExists(atPath: $0) }
    ) -> PodcastPlayerLoadPlan? {
        let localURL: URL? = {
            guard let path = episode.localAudioPath, fileExists(path) else { return nil }
            return URL(fileURLWithPath: path)
        }()
        guard let audioURL = localURL ?? episode.audioURL.flatMap(URL.init(string:)) else {
            return nil
        }

        return PodcastPlayerLoadPlan(
            audioURL: audioURL,
            usesLocalAudio: localURL != nil,
            subtitleSource: subtitleSource(for: episode),
            title: episode.displayTitle,
            durationSec: episode.durationSec
        )
    }

    private static func subtitleSource(for episode: PodcastEpisode) -> SubtitleSource {
        if let inline = episode.inlineSubtitle, !inline.isEmpty {
            return .inline(inline)
        }
        if let subtitleURL = episode.subtitleURL {
            return .remote(subtitleURL)
        }
        return .unavailable
    }
}
#endif
