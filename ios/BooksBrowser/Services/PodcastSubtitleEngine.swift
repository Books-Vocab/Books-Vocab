import Foundation

struct PodcastSubtitleCue: Identifiable, Equatable {
    let id: Int
    let startTime: TimeInterval
    let endTime: TimeInterval
    let speaker: String
    let fullText: String
    let highlightedWord: String?
}

struct PodcastSentence: Identifiable, Equatable {
    let id: Int
    let speaker: String
    let text: String
    let startTime: TimeInterval
    let endTime: TimeInterval
    let words: [PodcastSubtitleCue]
}

final class PodcastSubtitleEngine {
    private(set) var cues: [PodcastSubtitleCue] = []
    private(set) var sentences: [PodcastSentence] = []

    private static let speakerPattern = /^\[(\w+)\]\s*/
    private static let fontTagPattern = /<font[^>]*>(.*?)<\/font>/

    func load(srtContent: String) {
        cues = parseCues(from: srtContent)
        sentences = aggregateSentences(from: cues)
    }

    func currentCue(at time: TimeInterval) -> PodcastSubtitleCue? {
        // Binary search
        var lo = 0, hi = cues.count - 1
        while lo <= hi {
            let mid = (lo + hi) / 2
            if cues[mid].endTime < time {
                lo = mid + 1
            } else if cues[mid].startTime > time {
                hi = mid - 1
            } else {
                return cues[mid]
            }
        }
        return nil
    }

    func currentSentence(at time: TimeInterval) -> PodcastSentence? {
        sentences.last { $0.startTime <= time && time <= $0.endTime }
    }

    // MARK: - Parsing

    private func parseCues(from content: String) -> [PodcastSubtitleCue] {
        let blocks = content.components(separatedBy: "\n\n")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }

        var result: [PodcastSubtitleCue] = []

        for block in blocks {
            let lines = block.components(separatedBy: .newlines)
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty }

            guard lines.count >= 3,
                  let id = Int(lines[0]),
                  let (start, end) = parseTimeRange(lines[1]) else { continue }

            let rawText = lines[2...].joined(separator: " ")

            // Extract speaker
            let speaker: String
            let textAfterSpeaker: String
            if let match = rawText.firstMatch(of: Self.speakerPattern) {
                speaker = String(match.1)
                textAfterSpeaker = String(rawText[match.range.upperBound...])
            } else {
                speaker = ""
                textAfterSpeaker = rawText
            }

            // Extract highlighted word
            let highlightedWord: String?
            if let match = textAfterSpeaker.firstMatch(of: Self.fontTagPattern) {
                highlightedWord = String(match.1)
            } else {
                highlightedWord = nil
            }

            // Strip all HTML tags
            let fullText = textAfterSpeaker
                .replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression)
                .trimmingCharacters(in: .whitespaces)

            result.append(PodcastSubtitleCue(
                id: id, startTime: start, endTime: end,
                speaker: speaker, fullText: fullText, highlightedWord: highlightedWord
            ))
        }

        return result.sorted { $0.startTime < $1.startTime }
    }

    private func aggregateSentences(from cues: [PodcastSubtitleCue]) -> [PodcastSentence] {
        guard !cues.isEmpty else { return [] }
        var sentences: [PodcastSentence] = []
        var currentGroup: [PodcastSubtitleCue] = [cues[0]]

        for i in 1..<cues.count {
            let cue = cues[i]
            let prev = currentGroup[0]
            if cue.speaker == prev.speaker && cue.fullText == prev.fullText {
                currentGroup.append(cue)
            } else {
                sentences.append(makeSentence(from: currentGroup, id: sentences.count))
                currentGroup = [cue]
            }
        }
        if !currentGroup.isEmpty {
            sentences.append(makeSentence(from: currentGroup, id: sentences.count))
        }
        return sentences
    }

    private func makeSentence(from cues: [PodcastSubtitleCue], id: Int) -> PodcastSentence {
        PodcastSentence(
            id: id, speaker: cues[0].speaker, text: cues[0].fullText,
            startTime: cues[0].startTime, endTime: cues.last!.endTime, words: cues
        )
    }

    private func parseTimeRange(_ line: String) -> (TimeInterval, TimeInterval)? {
        let parts = line.components(separatedBy: " --> ")
        guard parts.count == 2,
              let start = parseTimestamp(parts[0]),
              let end = parseTimestamp(parts[1]) else { return nil }
        return (start, end)
    }

    private func parseTimestamp(_ ts: String) -> TimeInterval? {
        let c = ts.components(separatedBy: CharacterSet(charactersIn: ":,"))
        guard c.count == 4,
              let h = Double(c[0]), let m = Double(c[1]),
              let s = Double(c[2]), let ms = Double(c[3]) else { return nil }
        return h * 3600 + m * 60 + s + ms / 1000
    }
}
