import Foundation

struct PodcastSubtitleCue: Identifiable, Equatable {
    let id: Int
    let startTime: TimeInterval
    let endTime: TimeInterval
    let speaker: String
    let word: String  // compact SRT: one cue = one word
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
    private static let sentenceEndChars: Set<Character> = [".", "!", "?", "…"]

    func load(srtContent: String) {
        cues = parseCues(from: srtContent)
        sentences = aggregateSentences(from: cues)
    }

    func currentCue(at time: TimeInterval) -> PodcastSubtitleCue? {
        // Binary search with gap fallback — compact SRTs stitch end=next.start
        // but any gap (silence / rounding) would otherwise return nil and cause
        // the highlight to strobe off/on once per word. Fall back to the last
        // cue whose startTime <= time.
        guard !cues.isEmpty else { return nil }
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
        // hi is the largest index with startTime <= time (mirrors currentSentence).
        return hi >= 0 ? cues[hi] : nil
    }

    func currentSentence(at time: TimeInterval) -> PodcastSentence? {
        guard !sentences.isEmpty else { return nil }
        var lo = 0, hi = sentences.count - 1
        while lo <= hi {
            let mid = (lo + hi) / 2
            if sentences[mid].endTime < time {
                lo = mid + 1
            } else if sentences[mid].startTime > time {
                hi = mid - 1
            } else {
                return sentences[mid]
            }
        }
        return hi >= 0 ? sentences[hi] : nil
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

            // Extract speaker tag [SpeakerName]
            let speaker: String
            let textAfterSpeaker: String
            if let match = rawText.firstMatch(of: Self.speakerPattern) {
                speaker = String(match.1)
                textAfterSpeaker = String(rawText[match.range.upperBound...])
            } else {
                speaker = ""
                textAfterSpeaker = rawText
            }

            // Defensive: strip any HTML tags (handles legacy SRTs with <font> wrappers).
            let word = textAfterSpeaker
                .replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression)
                .trimmingCharacters(in: .whitespaces)
            guard !word.isEmpty else { continue }

            result.append(PodcastSubtitleCue(
                id: id, startTime: start, endTime: end,
                speaker: speaker, word: word
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
            let prev = currentGroup.last!
            // Boundary rule (matches lab/podcast/preview.py):
            //   • speaker change, OR
            //   • previous word ends with sentence-final punctuation (.!?…)
            //     ignoring trailing quote/paren.
            let prevTrimmed = prev.word.trimmingCharacters(
                in: CharacterSet(charactersIn: "\"')]}”’」』"))
            let endsSentence = prevTrimmed.last.map { Self.sentenceEndChars.contains($0) } ?? false
            if cue.speaker != prev.speaker || endsSentence {
                sentences.append(makeSentence(from: currentGroup, id: sentences.count))
                currentGroup = [cue]
            } else {
                currentGroup.append(cue)
            }
        }
        if !currentGroup.isEmpty {
            sentences.append(makeSentence(from: currentGroup, id: sentences.count))
        }
        return sentences
    }

    private func makeSentence(from cues: [PodcastSubtitleCue], id: Int) -> PodcastSentence {
        let text = cues.map(\.word).joined(separator: " ")
        return PodcastSentence(
            id: id, speaker: cues[0].speaker, text: text,
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
