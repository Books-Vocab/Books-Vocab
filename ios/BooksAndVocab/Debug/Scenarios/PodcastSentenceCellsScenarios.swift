#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the two private leaf views inside
/// `PodcastSentenceLevelView`:
/// - `PodcastTranscriptColumn` — the `LazyVStack` transcript column that builds one
///   `PodcastBubbleCell` per sentence.
/// - `PodcastBubbleCell` — a single transcript bubble (Equatable value view).
///
/// Both views consume only plain value inputs EXCEPT `PodcastLiveAnchor`, which is
/// `@MainActor`. So every cell/column is constructed inside a `@MainActor`-free
/// `XScene: View` body (the body runs on the main actor) rather than directly in the
/// nonisolated `Scenario` closure. Inputs are deterministic synthetic
/// `PodcastSentence` fixtures; no audio/network/view-model is touched.
enum PodcastSentenceCellsScenarios {
    static func register(in playbook: Playbook) {
        // MARK: Transcript column
        playbook.addScenarios(of: "Podcast · Transcript Column") {
            Scenario("Two speakers (current: 1)", layout: .compressed) {
                TranscriptColumnScene(currentId: 1, subtitleSize: .large)
            }
            Scenario("Highlighted vocab", layout: .compressed) {
                TranscriptColumnScene(
                    currentId: 0,
                    subtitleSize: .large,
                    lookedUpWords: ["comfortable", "question"]
                )
            }
            Scenario("Pre-roll (no current)", layout: .compressed) {
                TranscriptColumnScene(currentId: nil, subtitleSize: .medium)
            }
            Scenario("Large size (XXL)", layout: .compressed) {
                TranscriptColumnScene(currentId: 2, subtitleSize: .xxLarge)
            }
        }

        // MARK: Single bubble cell
        playbook.addScenarios(of: "Podcast · Bubble Cell") {
            Scenario("Idle (non-current)", layout: .compressed) {
                BubbleCellScene(isCurrent: false, isHighlighted: false)
            }
            Scenario("Highlighted (active)", layout: .compressed) {
                BubbleCellScene(isCurrent: true, isHighlighted: true)
            }
            Scenario("Vocab highlighted", layout: .compressed) {
                BubbleCellScene(isCurrent: false, isHighlighted: false, vocabIndices: [0, 2])
            }
            Scenario("Right-aligned speaker", layout: .compressed) {
                BubbleCellScene(isCurrent: false, isHighlighted: false, alignRight: true)
            }
        }
    }
}

// MARK: - Fixtures

private enum PodcastSentenceCellsFixtures {
    /// Builds a gap-free compact-SRT sentence: one cue per word, end == next start.
    static func sentence(id: Int, speaker: String, text: String, startTime: TimeInterval) -> PodcastSentence {
        let tokens = text.split(separator: " ").map(String.init)
        let per = 0.42
        var cues: [PodcastSubtitleCue] = []
        var t = startTime
        for (i, token) in tokens.enumerated() {
            cues.append(
                PodcastSubtitleCue(
                    id: id * 100 + i,
                    startTime: t,
                    endTime: t + per,
                    speaker: speaker,
                    word: token
                )
            )
            t += per
        }
        return PodcastSentence(
            id: id,
            speaker: speaker,
            text: text,
            startTime: startTime,
            endTime: t,
            words: cues
        )
    }

    static var sentences: [PodcastSentence] {
        [
            sentence(id: 0, speaker: "Alex", text: "Are you comfortable with the question I asked?", startTime: 0),
            sentence(id: 1, speaker: "Jordan", text: "I think it is a fair question to raise.", startTime: 3.0),
            sentence(id: 2, speaker: "Alex", text: "Then let us explore it together slowly.", startTime: 6.4),
            sentence(id: 3, speaker: "Jordan", text: "That sounds good to me.", startTime: 9.1),
        ]
    }

    static var speakerSlots: [String: Int] { ["Alex": 0, "Jordan": 1] }
}

// MARK: - Transcript column scene (@MainActor body builds PodcastLiveAnchor)

private struct TranscriptColumnScene: View {
    let currentId: Int?
    let subtitleSize: PodcastSubtitleSize
    var lookedUpWords: Set<String> = []

    var body: some View {
        let skin = AppSkin.previewNeutral
        let anchor = PodcastLiveAnchor(
            value: PlaybackAnchor(mediaTime: 0, wallClock: 0, rate: 0)
        )
        return AppThemeContainer {
            ScrollView {
                PodcastTranscriptColumn(
                    sentences: PodcastSentenceCellsFixtures.sentences,
                    renderState: nil,
                    currentId: currentId,
                    scrollLeadId: currentId,
                    lookedUpWords: lookedUpWords,
                    highlightPreferences: .default,
                    selectionState: nil,
                    subtitleSize: subtitleSize,
                    wordFollowEnabled: false,
                    isPlaying: false,
                    duration: 12,
                    liveAnchor: anchor,
                    speakerSlots: PodcastSentenceCellsFixtures.speakerSlots,
                    skin: skin,
                    colorScheme: .light,
                    onSentenceTap: { _ in },
                    onWordTap: { _, _ in },
                    onPhraseTap: { _, _ in },
                    onExplainTap: { _, _ in },
                    onEnterSelection: { _ in },
                    onClearSelection: {}
                )
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

// MARK: - Single bubble cell scene

private struct BubbleCellScene: View {
    let isCurrent: Bool
    let isHighlighted: Bool
    var vocabIndices: Set<Int> = []
    var alignRight: Bool = false

    var body: some View {
        let skin = AppSkin.previewNeutral
        let slot = alignRight ? 1 : 0
        let sentence = PodcastSentenceCellsFixtures.sentence(
            id: 0,
            speaker: alignRight ? "Jordan" : "Alex",
            text: "Are you comfortable with the question I asked?",
            startTime: 0
        )
        let anchor = PodcastLiveAnchor(
            value: PlaybackAnchor(mediaTime: 0, wallClock: 0, rate: 0)
        )
        return AppThemeContainer {
            PodcastBubbleCell(
                sentenceId: sentence.id,
                contentHash: sentence.words.count,
                isCurrent: isCurrent,
                isNext: false,
                isHighlighted: isHighlighted,
                vocabHighlightIndices: vocabIndices,
                highlightPreferences: .default,
                isSelecting: false,
                initialSelectionRange: nil,
                hasActiveSelection: false,
                subtitleSize: .large,
                wordFollowEnabled: false,
                isPlaying: false,
                alignRight: alignRight,
                showSpeaker: true,
                speaker: sentence.speaker,
                words: sentence.words,
                fullText: sentence.text,
                skin: PodcastBubbleSkin(skin: skin, slot: slot),
                colorScheme: .light,
                liveAnchor: anchor,
                duration: 12,
                hasNext: false,
                entryFromTime: nil,
                onSentenceTap: {},
                onWordTap: { _, _ in },
                onPhraseTap: { _, _ in },
                onExplainTap: { _, _ in },
                onEnterSelection: { _ in },
                onClearSelection: {}
            )
            .padding(AppSpacing.s4)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
