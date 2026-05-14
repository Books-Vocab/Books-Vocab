#if os(iOS)
import SwiftUI
import UIKit

/// Chat-style transcript: sentences laid out as left/right bubbles by speaker.
///
/// Design principles:
///   • flat — no shadow, no scale lift, no blur
///   • follow-by-default: auto-scrolls with the current sentence; user drag
///     disables follow and surfaces a "追隨當前" pill that, when tapped,
///     re-enables follow and scrolls back to center.
///   • alignment distinguishes speakers (host[0] → left, host[1] → right);
///     the speaker label is shown only when it changes from the previous row.
///   • layout transitions are explicitly animated (bubble bg, underline,
///     label show/hide) to avoid the snap-change jank of dt→0 shifts.
struct PodcastSentenceLevelView: View {
    private struct SentenceSelectionState: Equatable {
        let sentenceId: Int
        let initialRange: NSRange?
    }

    let sentences: [PodcastSentence]
    let renderState: SubtitleRenderState?
    let highlightedWordIndex: Int
    let hostNames: [String]
    let subtitleSize: PodcastSubtitleSize
    let onSentenceTap: (PodcastSentence) -> Void
    let onWordTap: (String, String) -> Void
    let onPhraseTap: (String, String) -> Void
    let onExplainTap: (String, String) -> Void
    @Environment(\.vocabSkin) private var skin
    @AppStorage("podcast.wordFollowEnabled") private var wordFollowEnabled: Bool = true

    @State private var isFollowing = true
    @State private var didInitialScroll = false
    @State private var selectionState: SentenceSelectionState?

    private var currentId: Int? { renderState?.sentenceId }

    var body: some View {
        ScrollViewReader { proxy in
            ZStack(alignment: .bottom) {
                ScrollView {
                    LazyVStack(spacing: skin.spacing.inlineGap) {
                        ForEach(Array(sentences.enumerated()), id: \.element.id) { index, sentence in
                            let prevSpeaker = index > 0 ? sentences[index - 1].speaker : nil
                            let showSpeaker = sentence.speaker != prevSpeaker
                            bubbleRow(sentence, showSpeaker: showSpeaker)
                                .id(sentence.id)
                        }
                    }
                    .padding(.vertical, skin.spacing.sectionGap)
                    .padding(.horizontal, skin.spacing.cardPadding)
                }
                // User drag disables follow mode. `minimumDistance: 24` avoids
                // cancelling follow on a finger-tremor tap (10pt contact +
                // small slide during release). Genuine scroll easily clears it.
                .simultaneousGesture(
                    DragGesture(minimumDistance: 24)
                        .onChanged { _ in
                            if isFollowing { isFollowing = false }
                        }
                )

                if !isFollowing && selectionState == nil {
                    followPill {
                        isFollowing = true
                        if let id = currentId {
                            withAnimation(AppMotion.standardSpring) {
                                proxy.scrollTo(id, anchor: .center)
                            }
                        }
                    }
                    .padding(.bottom, skin.spacing.sectionGap)
                    .transition(.opacity.combined(with: .move(edge: .bottom)))
                }
            }
            .onAppear {
                // If currentId is already known at appear, do the one-shot scroll.
                // Otherwise the .onChange below will handle it when the first
                // sentence resolves after restoreProgress / first time-tick.
                if !didInitialScroll, let id = currentId {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                        proxy.scrollTo(id, anchor: .center)
                        didInitialScroll = true
                    }
                }
            }
            .onChange(of: currentId) { _, newId in
                guard let newId else { return }
                // First non-nil currentId → one-shot initial scroll without animation
                // so restored positions appear immediately.
                if !didInitialScroll {
                    proxy.scrollTo(newId, anchor: .center)
                    didInitialScroll = true
                    return
                }
                // Auto-follow: smoothly recenter when the sentence advances.
                guard isFollowing else { return }
                withAnimation(AppMotion.standardSpring) {
                    proxy.scrollTo(newId, anchor: .center)
                }
            }
            .animation(AppMotion.contentFade, value: isFollowing)
        }
    }

    // MARK: - Bubble row

    @ViewBuilder
    private func bubbleRow(_ sentence: PodcastSentence, showSpeaker: Bool) -> some View {
        let idx = hostNames.firstIndex(of: sentence.speaker)
        let alignRight = (idx == 1)
        let isCurrent = sentence.id == currentId
        let isSelecting = selectionState?.sentenceId == sentence.id
        HStack(alignment: .bottom, spacing: 0) {
            if alignRight { Spacer(minLength: 48) }
            VStack(alignment: alignRight ? .trailing : .leading, spacing: 3) {
                if showSpeaker {
                    Text(sentence.speaker)
                        .font(subtitleSize.speakerFont)
                        .foregroundStyle(tint(for: idx).opacity(isCurrent || isSelecting ? 0.88 : 0.58))
                        .transition(.opacity)
                }
                bubbleContent(sentence: sentence, idx: idx, isCurrent: isCurrent, isSelecting: isSelecting)
            }
            if !alignRight { Spacer(minLength: 48) }
        }
        .contentShape(Rectangle())
        .onTapGesture {
            if !isSelecting {
                handleSentenceTap(sentence, isCurrent: isCurrent)
            }
        }
    }

    @ViewBuilder
    private func bubbleContent(
        sentence: PodcastSentence,
        idx: Int?,
        isCurrent: Bool,
        isSelecting: Bool
    ) -> some View {
        let bubbleTint = tint(for: idx)
        let bg: Color = isCurrent || isSelecting
            ? bubbleTint.opacity(0.16)
            : skin.palette.mutedFill.opacity(0.72)
        let fg: Color = isCurrent || isSelecting ? skin.palette.primaryText : skin.palette.secondaryText

        Group {
            if isSelecting {
                PodcastSelectableSentenceTextView(
                    text: sentence.text,
                    font: subtitleSize.uiSubtitleFont,
                    textColor: UIColor(fg),
                    tintColor: UIColor(bubbleTint),
                    initialSelectionRange: selectionState?.initialRange
                ) { phrase, context in
                    selectionState = nil
                    onPhraseTap(phrase, context)
                } onExplainSelection: { text, context in
                    selectionState = nil
                    onExplainTap(text, context)
                }
            } else {
                // All bubbles use CachedFlowLayout of per-word tokens — same layout
                // algorithm whether current or not. This guarantees line breaks don't
                // shift when a sentence becomes current (the prior design mixed a
                // single wrapping Text with an overlay FlowLayout whose wrapping
                // disagreed, producing visible misalignment + jank).
                wordFlow(for: sentence, isCurrent: isCurrent, textColor: fg, tint: bubbleTint)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(bg, in: RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous)
                .stroke(
                    bubbleTint.opacity(isCurrent || isSelecting ? 0.22 : 0.08),
                    lineWidth: isCurrent || isSelecting ? 1 : 0.8
                )
        }
        .animation(AppMotion.contentFade, value: isCurrent)
        .animation(AppMotion.contentFade, value: isSelecting)
    }

    @ViewBuilder
    private func wordFlow(
        for sentence: PodcastSentence,
        isCurrent: Bool,
        textColor: Color,
        tint: Color
    ) -> some View {
        // When the sentence is current AND we have renderState for it, use the
        // per-cue words so the active-word underline and word-tap map 1:1 to
        // the audio. Otherwise derive stable tokens from sentence.text.
        if isCurrent, let rs = renderState, rs.sentenceId == sentence.id {
            CachedFlowLayout(spacing: skin.spacing.wordRowVerticalGap) {
                ForEach(Array(rs.words.enumerated()), id: \.element.id) { index, word in
                    let isActive = word.id == highlightedWordIndex
                    let showsActiveUnderline = wordFollowEnabled && isActive
                    Text(word.text)
                        .font(subtitleSize.subtitleFont)
                        .foregroundStyle(textColor)
                        .overlay(alignment: .bottom) {
                            if showsActiveUnderline {
                                Rectangle()
                                    .fill(tint)
                                    .frame(height: 1.5)
                                    .offset(y: 3)
                                    .transition(.opacity)
                            }
                        }
                        .onTapGesture {
                            onWordTap(word.text, rs.sentenceText)
                        }
                        .onLongPressGesture(minimumDuration: 0.35) {
                            enterSelectionMode(for: sentence, wordIndex: index)
                        }
                }
            }
            .animation(AppMotion.standardSpring, value: highlightedWordIndex)
        } else {
            CachedFlowLayout(spacing: skin.spacing.wordRowVerticalGap) {
                // Use sentence.words (same source the current-branch uses) so
                // token count and line-wrapping stay identical when the sentence
                // becomes current — avoids any jump in bubble height.
                ForEach(Array(sentence.words.enumerated()), id: \.offset) { index, cue in
                    Text(cue.word)
                        .font(subtitleSize.subtitleFont)
                        .foregroundStyle(textColor)
                        .onTapGesture {
                            onWordTap(cue.word, sentence.text)
                        }
                        .onLongPressGesture(minimumDuration: 0.35) {
                            enterSelectionMode(for: sentence, wordIndex: index)
                        }
                }
            }
        }
    }

    // MARK: - Follow pill

    @ViewBuilder
    private func followPill(_ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 6) {
                if let speaker = renderState?.speaker {
                    let idx = hostNames.firstIndex(of: speaker)
                    Circle()
                        .fill(tint(for: idx))
                        .frame(width: 6, height: 6)
                }
                Text("追隨當前")
                    .font(skin.typography.caption)
                    .foregroundStyle(skin.palette.primaryText)
                Image(systemName: "arrow.down")
                    .font(skin.typography.iconTiny)
                    .foregroundStyle(skin.palette.secondaryText)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background(
                Capsule()
                    .fill(skin.palette.cardBackground.opacity(0.96))
                    .overlay(Capsule().stroke(skin.palette.cardBorder, lineWidth: 1))
            )
        }
        .buttonStyle(.plain)
    }

    // MARK: - Helpers

    private func tint(for idx: Int?) -> Color {
        switch idx {
        case 0: return skin.palette.accent
        case 1: return skin.palette.success
        default: return skin.palette.tertiaryText
        }
    }

    private func handleSentenceTap(_ sentence: PodcastSentence, isCurrent: Bool) {
        if selectionState != nil {
            selectionState = nil
            return
        }
        if !isCurrent { onSentenceTap(sentence) }
    }

    private func enterSelectionMode(for sentence: PodcastSentence, wordIndex: Int) {
        isFollowing = false
        selectionState = SentenceSelectionState(
            sentenceId: sentence.id,
            initialRange: selectionRange(for: sentence, wordIndex: wordIndex)
        )
    }

    private func selectionRange(for sentence: PodcastSentence, wordIndex: Int) -> NSRange? {
        let nsText = sentence.text as NSString
        var searchStart = 0

        for (index, cue) in sentence.words.enumerated() {
            let searchRange = NSRange(
                location: searchStart,
                length: max(0, nsText.length - searchStart)
            )
            let foundRange = nsText.range(of: cue.word, options: [], range: searchRange)
            guard foundRange.location != NSNotFound else { continue }
            if index == wordIndex { return foundRange }
            searchStart = foundRange.location + foundRange.length
        }

        return nil
    }
}

#Preview("Podcast Subtitle XL") {
    let cues1 = [
        PodcastSubtitleCue(id: 1, startTime: 0, endTime: 0.4, speaker: "Maya", word: "OK"),
        PodcastSubtitleCue(id: 2, startTime: 0.4, endTime: 0.8, speaker: "Maya", word: "so"),
        PodcastSubtitleCue(id: 3, startTime: 0.8, endTime: 1.2, speaker: "Maya", word: "here's"),
        PodcastSubtitleCue(id: 4, startTime: 1.2, endTime: 1.6, speaker: "Maya", word: "a"),
        PodcastSubtitleCue(id: 5, startTime: 1.6, endTime: 2.2, speaker: "Maya", word: "question."),
    ]
    let cues2 = [
        PodcastSubtitleCue(id: 6, startTime: 2.2, endTime: 2.7, speaker: "Kai", word: "We"),
        PodcastSubtitleCue(id: 7, startTime: 2.7, endTime: 3.0, speaker: "Kai", word: "live"),
        PodcastSubtitleCue(id: 8, startTime: 3.0, endTime: 3.2, speaker: "Kai", word: "in"),
        PodcastSubtitleCue(id: 9, startTime: 3.2, endTime: 3.5, speaker: "Kai", word: "the"),
        PodcastSubtitleCue(id: 10, startTime: 3.5, endTime: 4.0, speaker: "Kai", word: "most"),
        PodcastSubtitleCue(id: 11, startTime: 4.0, endTime: 4.7, speaker: "Kai", word: "comfortable"),
        PodcastSubtitleCue(id: 12, startTime: 4.7, endTime: 5.2, speaker: "Kai", word: "era."),
    ]
    let s1 = PodcastSentence(id: 0, speaker: "Maya", text: "OK so here's a question.", startTime: 0, endTime: 2.2, words: cues1)
    let s2 = PodcastSentence(id: 1, speaker: "Kai", text: "We live in the most comfortable era.", startTime: 2.2, endTime: 5.2, words: cues2)

    return AppThemeContainer {
        PodcastSentenceLevelView(
            sentences: [s1, s2],
            renderState: SubtitleRenderState(from: s2, hostNames: ["Maya", "Kai"]),
            highlightedWordIndex: 4,
            hostNames: ["Maya", "Kai"],
            subtitleSize: .xLarge,
            onSentenceTap: { _ in },
            onWordTap: { _, _ in },
            onPhraseTap: { _, _ in },
            onExplainTap: { _, _ in }
        )
    }
}
#endif
