#if os(iOS)
import Foundation

enum PodcastFollowControlVisibility {
    static func shouldShow(
        isFollowing: Bool,
        hasActiveSelection: Bool,
        isCatalyst: Bool
    ) -> Bool {
        guard !hasActiveSelection else { return false }
        if isCatalyst { return true }
        return !isFollowing
    }
}

enum PodcastSentenceSelectionRange {
    static func range(
        in sentenceText: String,
        words: [PodcastSubtitleCue],
        wordIndex: Int
    ) -> NSRange? {
        let nsText = sentenceText as NSString
        var searchStart = 0
        for (index, cue) in words.enumerated() {
            let searchRange = NSRange(location: searchStart, length: max(0, nsText.length - searchStart))
            let foundRange = nsText.range(of: cue.word, options: [], range: searchRange)
            guard foundRange.location != NSNotFound else { continue }
            if index == wordIndex { return foundRange }
            searchStart = foundRange.location + foundRange.length
        }
        return nil
    }
}
#endif
