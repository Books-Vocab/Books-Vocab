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
        // Half-open `[startTime, endTime)` binary search with gap fallback —
        // compact SRTs stitch end=next.start, so a closed interval would make a
        // shared boundary instant ambiguous between adjacent cues (the same
        // seek off-by-one fixed in `locateSentence`). `endTime <= time` assigns
        // each boundary solely to the next cue; a real gap still falls back to the
        // last cue whose startTime <= time. Mirrors `locateSentence`.
        guard !cues.isEmpty else { return nil }
        var lo = 0, hi = cues.count - 1
        while lo <= hi {
            let mid = (lo + hi) / 2
            if cues[mid].endTime <= time {
                lo = mid + 1
            } else if cues[mid].startTime > time {
                hi = mid - 1
            } else {
                return cues[mid]
            }
        }
        return hi >= 0 ? cues[hi] : nil
    }

    func currentSentence(at time: TimeInterval) -> PodcastSentence? {
        Self.locateSentence(in: sentences, at: time)
    }

    /// Sentence id the auto-follow scroll should target. Pure + static so the lead
    /// semantics are unit-testable without driving the player.
    ///
    /// Natural playback ticks LEAD the playhead by `leadSec` so the next bubble
    /// glides to viewport center ~0.5 s before it is actually spoken — the scroll
    /// arrives early rather than chasing. A seek instead pins to the CURRENT
    /// sentence (no lead): `seek(to:)` drives `handleTimeUpdate` synchronously, so
    /// leading there would resolve to the NEXT sentence and a transcript tap would
    /// scroll past the tapped bubble to its successor (★B1 race). The next natural
    /// tick restores the lead. Returns nil only for empty/pre-roll input — gap and
    /// end-of-track cases fall back gracefully via `locateSentence`.
    static func scrollLeadSentenceId(
        in sentences: [PodcastSentence],
        at time: TimeInterval,
        isSeek: Bool,
        leadSec: TimeInterval
    ) -> Int? {
        let leadTime = isSeek ? time : time + leadSec
        return locateSentence(in: sentences, at: leadTime)?.id
    }

    /// Locate the sentence active at `time` using a **half-open** interval
    /// `[startTime, endTime)`. Pure + static so it can be unit-tested directly
    /// without driving the parser.
    ///
    /// Why half-open (the seek off-by-one fix): compact SRTs stitch sentences
    /// gap-free, so `sentence[i-1].endTime == sentence[i].startTime`. With a
    /// CLOSED interval (`endTime < time` / `startTime > time` ⇒ else), that shared
    /// boundary instant belongs to BOTH neighbours' closed ranges, and a precise
    /// zero-tolerance seek to `sentence[i].startTime` lands exactly on it — so the
    /// binary search could return `sentence[i-1]` (the bubble ABOVE the tapped
    /// one). Tapping a group's first sentence looked correct only because a
    /// speaker change leaves a silent gap before it, breaking the boundary tie.
    /// `endTime <= time` makes each boundary instant belong solely to the next
    /// sentence, so a seek to a startTime always resolves to that sentence.
    /// Gap fallback unchanged: a `time` inside a real silence still returns the
    /// last sentence whose `startTime <= time` (`hi`).
    static func locateSentence(in sentences: [PodcastSentence], at time: TimeInterval) -> PodcastSentence? {
        guard !sentences.isEmpty else { return nil }
        var lo = 0, hi = sentences.count - 1
        while lo <= hi {
            let mid = (lo + hi) / 2
            if sentences[mid].endTime <= time {
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
            guard let prev = currentGroup.last else { continue }
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
        guard let first = cues.first, let last = cues.last else {
            // Defensive: callers already guard non-empty, but keep the function
            // self-contained so future refactors can't crash here.
            return PodcastSentence(
                id: id, speaker: "", text: "",
                startTime: 0, endTime: 0, words: cues
            )
        }
        let text = cues.map(\.word).joined(separator: " ")
        return PodcastSentence(
            id: id, speaker: first.speaker, text: text,
            startTime: first.startTime, endTime: last.endTime, words: cues
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
