#if os(iOS)
import SwiftUI
import UIKit

/// The transcript column, hosted in a native `ScrollView` + `LazyVStack` so only
/// on-screen bubbles are realized. The column body is CHEAP — it builds one
/// `PodcastBubbleCell` value struct per realized row; each is wrapped in
/// `.equatable()`, so when `currentId` changes SwiftUI re-bodies only the cells
/// whose Equatable inputs actually changed (the leaving + gaining cell, ~2),
/// short-circuiting all the others — they never re-lay-out their `UITextView`.
///
/// The column itself is intentionally NOT `Equatable`: a column-level wrapper
/// whose `==` included `currentId` returned false on every advance and forced the
/// whole column body to rebuild all realized rows (the measured per-advance hitch).
/// Dropping it and gating at per-cell granularity is the fix. The column body re-
/// runs on parent renders, but that is cheap now (only value structs are built;
/// the token trees live behind the per-cell Equatable boundary).
struct PodcastTranscriptColumn: View {
    let sentences: [PodcastSentence]
    let renderState: SubtitleRenderState?
    let currentId: Int?
    /// Lead-target sentence id (VM `scrollLeadSentenceId`, seek-pinned). Drives the
    /// EARLY pre-active highlight only — not `currentId`/underline. Mirrors the prop
    /// on the host view so the column can light the upcoming bubble ahead of audio.
    let scrollLeadId: Int?
    let lookedUpWords: Set<String>
    let highlightPreferences: VocabHighlightPreferences
    let selectionState: PodcastSentenceSelection?
    let subtitleSize: PodcastSubtitleSize
    let wordFollowEnabled: Bool
    let isPlaying: Bool
    let duration: TimeInterval
    let liveAnchor: PodcastLiveAnchor
    let speakerSlots: [String: Int]
    let skin: AppSkin
    let colorScheme: ColorScheme
    let onSentenceTap: (PodcastSentence) -> Void
    let onWordTap: (String, String) -> Void
    let onPhraseTap: (String, String) -> Void
    let onExplainTap: (String, String) -> Void
    let onEnterSelection: (PodcastSentenceSelection) -> Void
    let onClearSelection: () -> Void

    var body: some View {
        PerfLog.render.mark("column.body", "id=\(currentId ?? -1) n=\(sentences.count)")
        let hasActiveSelection = selectionState != nil
        // 每次 render 算一次:把詞庫詞集正規化（撇號折疊 + 小寫 + 去標點），供各 cell 的
        // highlightedIndices 比對共用,避免 per-cell 重建整個詞庫集合。刻意不 @State 快取:
        // column render 為 parent 級（currentId 句界 / 選取 / size 變動,非每幀——每幀的是
        // cell 內 underline TimelineView),數百短字串 normalize 成本微秒級,不值 @State + task
        // 的時序複雜度與一拍延遲。
        let normalizedLookedUp = Set(lookedUpWords.map(PodcastVocabHighlightResolver.normalize))
        // 單一高亮真相：捲動領先 scrollLeadSec 點亮「即將播」的句子，但任一時刻只有
        // 一格亮（接力，非重疊）。先前 active = isCurrent || isPreActive 會在切換前的
        // scrollLeadSec 窗口同時點亮 current 與 next 兩格 → 兩個都亮。
        let highlightId = PodcastHighlightResolver.highlightId(
            currentId: currentId, scrollLeadId: scrollLeadId
        )
        return LazyVStack(spacing: skin.spacing.inlineGap) {
            ForEach(Array(sentences.enumerated()), id: \.element.id) { index, sentence in
                let slot = speakerSlots[sentence.speaker] ?? 0
                let isSelectingThis = selectionState?.sentenceId == sentence.id
                let prevSpeaker = index > 0 ? sentences[index - 1].speaker : nil
                // Cross-sentence relay wiring: the cell after `currentId` is the
                // entering bubble; its handoff window opens at its predecessor's
                // last word (gap-free SRT). `hasNext` lets the leaving cell slide
                // off rather than hold on the final sentence.
                let isNext = currentId.map { sentence.id == $0 + 1 } ?? false
                // 高亮領先音訊 scrollLeadSec，但只有 `highlightId` 這一格亮（接力）。
                // `highlightId` 已 clamp 到 current+1，所以即使短句讓 scrollLeadId 跳到
                // current+2，點亮的仍是 current+1（== `isNext`，已掛載 underline
                // machinery + `headEnter` priming），不會點亮無 underline overlay 的遠格。
                let isHighlighted = sentence.id == highlightId
                let hasNext = index < sentences.count - 1
                let entryFromTime = index > 0 ? sentences[index - 1].words.last?.startTime : nil
                let vocabHits = PodcastVocabHighlightResolver.highlightedIndices(
                    words: sentence.words.map(\.word), normalizedLookedUp: normalizedLookedUp
                )
                PodcastBubbleCell(
                    sentenceId: sentence.id,
                    contentHash: {
                        var hasher = Hasher()
                        hasher.combine(sentence.startTime)
                        hasher.combine(sentence.endTime)
                        hasher.combine(sentence.words.count)
                        hasher.combine(sentence.speaker)
                        return hasher.finalize()
                    }(),
                    isCurrent: sentence.id == currentId,
                    isNext: isNext,
                    isHighlighted: isHighlighted,
                    vocabHighlightIndices: vocabHits,
                    highlightPreferences: highlightPreferences,
                    isSelecting: isSelectingThis,
                    initialSelectionRange: isSelectingThis ? selectionState?.initialRange : nil,
                    hasActiveSelection: hasActiveSelection,
                    subtitleSize: subtitleSize,
                    wordFollowEnabled: wordFollowEnabled,
                    isPlaying: isPlaying,
                    alignRight: slot % 2 == 1,
                    showSpeaker: sentence.speaker != prevSpeaker,
                    speaker: sentence.speaker,
                    words: sentence.words,
                    fullText: sentence.text,
                    skin: PodcastBubbleSkin(skin: skin, slot: slot),
                    colorScheme: colorScheme,
                    liveAnchor: liveAnchor,
                    duration: duration,
                    hasNext: hasNext,
                    entryFromTime: entryFromTime,
                    onSentenceTap: {
                        if hasActiveSelection {
                            onClearSelection()
                        } else {
                            // Always seek to this sentence's start — tapping the
                            // already-current bubble re-seeks to its head too.
                            onSentenceTap(sentence)
                        }
                    },
                    onWordTap: onWordTap,
                    onPhraseTap: onPhraseTap,
                    onExplainTap: onExplainTap,
                    onEnterSelection: { wordIndex in
                        onEnterSelection(
                            PodcastSentenceSelection(
                                sentenceId: sentence.id,
                                initialRange: selectionRange(for: sentence, wordIndex: wordIndex)
                            )
                        )
                    },
                    onClearSelection: onClearSelection
                )
                .equatable()
                .id(sentence.id)
            }
        }
        .padding(.vertical, skin.spacing.sectionGap)
        .padding(.horizontal, skin.spacing.cardPadding)
    }

    /// Maps a word index to its `NSRange` within the sentence text, to seed the
    /// selectable text view's initial selection. Kept on the column (not the cell)
    /// so the cell stays a pure value — the cell calls back with just the word index.
    private func selectionRange(for sentence: PodcastSentence, wordIndex: Int) -> NSRange? {
        PodcastSentenceSelectionRange.range(
            in: sentence.text,
            words: sentence.words,
            wordIndex: wordIndex
        )
    }
}

/// Cheap Equatable skin token for a bubble. Compared ONLY by `paletteBase`
/// (`AppTheme.Palette`, the single source of truth every color derives from — so a
/// theme/colorScheme change flips it) + `slot` (the speaker tint depends on it).
/// The resolved colors/metrics are CARRIED for the body but NOT compared: with the
/// same `paletteBase` + `slot` they are deterministically identical, so comparing
/// them (Color `==` is unreliable) would be both wrong and wasteful.
struct PodcastBubbleSkin: Equatable {
    let paletteBase: AppTheme.Palette
    let slot: Int
    // Carried, not compared:
    let tint: Color
    let primaryText: Color
    let secondaryText: Color
    let cornerRadius: CGFloat
    init(skin: AppSkin, slot: Int) {
        self.paletteBase = skin.palette.base
        self.slot = slot
        self.tint = PodcastSpeakerTint.color(for: slot, skin: skin)
        self.primaryText = skin.palette.primaryText
        self.secondaryText = skin.palette.secondaryText
        self.cornerRadius = skin.radii.card
    }

    static func == (l: PodcastBubbleSkin, r: PodcastBubbleSkin) -> Bool {
        l.paletteBase == r.paletteBase && l.slot == r.slot
    }
}

/// One transcript bubble as an `Equatable` value view. Wrapped in `.equatable()`
/// inside the column's `ForEach`, so SwiftUI skips its `body` whenever its inputs
/// are unchanged — a sentence advance flips `isCurrent` on only the leaving +
/// gaining cells, so only those ~2 re-body (the rest short-circuit and never
/// re-lay-out their `UITextView`). This is what makes a sentence change
/// O(2 rows) instead of O(all realized rows).
///
/// EXCLUDED from `==`: `liveAnchor` (a reference, read live per frame by the
/// underline's own `TimelineView`), `duration`, and all closures (stable per
/// parent render). `words` / `fullText` / `speaker` are excluded too — they are
/// fully determined by `sentenceId` + `contentHash`, so comparing the scalar keys
/// is enough and avoids an O(n·words) array compare.
struct PodcastBubbleCell: View, Equatable {
    let sentenceId: Int
    let contentHash: Int
    let isCurrent: Bool
    /// The sentence immediately after `currentId`. Cross-sentence underline relay
    /// (Option B) needs the entering bubble's underline machinery present BEFORE the
    /// `currentId` flip (which lags audio ~one tick / ~55 ms, device-measured), so
    /// the entering head can already be sliding in. Compared in `==` so the cell
    /// gains/loses its machinery as it enters/leaves the "next" slot.
    let isNext: Bool
    /// 此格是否為唯一高亮目標（`highlightId`，捲動領先 scrollLeadSec、clamp 到
    /// current+1）。驅動 `active` 高亮 only — NOT `currentId`、NOT underline。任一時刻
    /// 只有一格為 true（接力，非重疊）。Compared in `==` 以隨高亮接力 light / dim。
    let isHighlighted: Bool
    /// 此句中命中詞庫（含變形）的 word index 集合，驅動常駐詞庫螢光筆底色。由 column
    /// 經 `PodcastVocabHighlightResolver` 算出。與 playback 無關、所有句子常駐。
    /// Compared in `==` 以隨加 / 刪詞庫（`lookedUpWords` 變動）重繪。
    let vocabHighlightIndices: Set<Int>
    let highlightPreferences: VocabHighlightPreferences
    let isSelecting: Bool
    let initialSelectionRange: NSRange?
    let hasActiveSelection: Bool
    let subtitleSize: PodcastSubtitleSize
    let wordFollowEnabled: Bool
    let isPlaying: Bool
    let alignRight: Bool
    let showSpeaker: Bool
    let speaker: String
    let words: [PodcastSubtitleCue]
    let fullText: String
    let skin: PodcastBubbleSkin
    let colorScheme: ColorScheme
    // Per-frame channel + stable closures — EXCLUDED from == (determined by
    // `sentenceId` or read live per frame):
    let liveAnchor: PodcastLiveAnchor
    let duration: TimeInterval
    /// Is there a successor sentence (so the leaving handoff should slide off the
    /// edge rather than hold). Determined by `sentenceId` → not compared.
    let hasNext: Bool
    /// Start time of THIS sentence's predecessor's last word — the instant the
    /// entering relay window opens. It equals my `startTime` minus that last word's
    /// duration (gap-free SRT ⇒ predecessor's last-word END == my first-word START),
    /// which is exactly why the leaving tail's fraction and this head's fraction
    /// stay in lock-step. nil for the first sentence. Determined by `sentenceId` →
    /// not compared.
    let entryFromTime: TimeInterval?
    let onSentenceTap: () -> Void
    let onWordTap: (String, String) -> Void
    let onPhraseTap: (String, String) -> Void
    let onExplainTap: (String, String) -> Void
    let onEnterSelection: (Int) -> Void
    let onClearSelection: () -> Void

    /// Per-word rects published by the unified `UITextView`'s TextKit layout (once
    /// per layout pass, cache-guarded). The continuous underline reads these instead
    /// of the old SwiftUI anchor preferences. Internal `@State` — excluded from `==`
    /// (it's an output of layout, not an identity input); when it updates only THIS
    /// cell re-bodies, feeding the new rects to the per-frame underline.
    @State private var wordRects: [Int: CGRect] = [:]

    static func == (l: PodcastBubbleCell, r: PodcastBubbleCell) -> Bool {
        l.sentenceId == r.sentenceId
            && l.contentHash == r.contentHash
            && l.isCurrent == r.isCurrent
            && l.isNext == r.isNext
            && l.isHighlighted == r.isHighlighted
            && l.vocabHighlightIndices == r.vocabHighlightIndices
            && l.highlightPreferences == r.highlightPreferences
            && l.isSelecting == r.isSelecting
            && l.initialSelectionRange == r.initialSelectionRange
            && l.hasActiveSelection == r.hasActiveSelection
            && l.subtitleSize == r.subtitleSize
            && l.wordFollowEnabled == r.wordFollowEnabled
            && l.isPlaying == r.isPlaying
            && l.alignRight == r.alignRight
            && l.showSpeaker == r.showSpeaker
            && l.skin == r.skin
            && l.colorScheme == r.colorScheme
    }

    var body: some View {
        let _ = PerfLog.render.tick("cell.body", isCurrent ? "cur" : "non")
        return HStack(alignment: .bottom, spacing: 0) {
            if alignRight { Spacer(minLength: 48) }
            VStack(alignment: alignRight ? .trailing : .leading, spacing: AppSpacing.tinyGap) {
                if showSpeaker {
                    Text(speaker)
                        .font(subtitleSize.speakerFont)
                        .foregroundStyle(skin.tint.opacity(isHighlighted || isSelecting ? 0.88 : 0.58))
                        .transition(.overlayFade)
                }
                bubbleContent
                    // tap-to-seek 命中區限定在氣泡本身：contentShape + onTapGesture 綁在
                    // bubbleContent，**不**綁含 Spacer(minLength:48) 的外層 HStack，否則整列
                    // （含氣泡旁空白）都會觸發 seek。a11y 仍在 row 層（下方 modifiers）。
                    .contentShape(Rectangle())
                    .onTapGesture {
                        if !isSelecting { onSentenceTap() }
                    }
            }
            if !alignRight { Spacer(minLength: 48) }
        }
        // VoiceOver: collapse the per-word `Text` tokens into ONE sentence element
        // (otherwise AT reads word-by-word and the tap-seek / long-press-select
        // gestures are invisible). While selecting, defer to `.contain` so the
        // UITextView's native selection a11y surfaces instead of being flattened.
        .accessibilityElement(children: isSelecting ? .contain : .ignore)
        .accessibilityLabel(isSelecting ? Text(verbatim: "") : Text(a11ySentenceLabel))
        .accessibilityAddTraits(isSelecting ? [] : .isButton)
        .accessibilityHint(isSelecting ? Text(verbatim: "") : Text(L10n.string("podcast.transcript.seekHint")))
        // `.onTapGesture` is invisible to VoiceOver — expose seek as the default
        // action so a double-tap jumps playback to this sentence.
        .accessibilityAction(.default) { if !isSelecting { onSentenceTap() } }
        .accessibilityAction(named: Text(L10n.string("podcast.transcript.translateAction"))) {
            if !isSelecting { onPhraseTap(fullText, fullText) }
        }
        .accessibilityAction(named: Text(L10n.string("podcast.transcript.selectAction"))) {
            if !isSelecting { onEnterSelection(0) }
        }
    }

    /// VoiceOver label: the sentence text, prefixed with the speaker (even when the
    /// visual label is hidden for repeated speakers) so AT users keep the dialog
    /// attribution that sighted users get from bubble alignment + tint.
    private var a11ySentenceLabel: String {
        speaker.isEmpty ? fullText : "\(speaker): \(fullText)"
    }

    @ViewBuilder
    private var bubbleContent: some View {
        // 高亮領先音訊 scrollLeadSec 點亮即將播的句子，但只有 `isHighlighted` 這一格亮
        // （接力，非重疊）。underline overlay 仍鍵在 `isCurrent || isNext` + 精確
        // `liveAnchor`，所以被提前點亮的下一句（== isNext）其 underline 已從 head 滑入
        // priming，不會出現 dead-lit gap。
        let active = isHighlighted || isSelecting
        let bg: Color = active ? skin.tint.opacity(0.18) : skin.tint.opacity(0.08)
        let fg: Color = active ? skin.primaryText : skin.secondaryText
        // ONE unified `UITextView` for BOTH display + selection — only `isSelectable`
        // flips. A single instance (NOT an if/else between two views) keeps the TextKit
        // layout byte-identical across the long-press swap → zero reflow (the "選取時
        // 排版跳版" fix). The continuous underline is a SwiftUI `.overlay` ON this view,
        // so its coordinate space == the resolved rects' (text-view origin), and it is
        // applied BEFORE the bubble padding (★B2) so the rects need no inset shift. It
        // shows only in display mode on the current / entering ("next") cell.
        PodcastSelectableSentenceTextView(
            text: fullText,
            font: subtitleSize.uiSubtitleFont,
            textColor: UIColor(fg),
            tintColor: UIColor(skin.tint),
            isSelectable: isSelecting,
            initialSelectionRange: isSelecting ? initialSelectionRange : nil,
            words: words.map(\.word),
            onResolveWordRects: { wordRects = $0 },
            onLongPressWord: { onEnterSelection($0) },
            onWordSelection: { word, context in onWordTap(word, context) },
            onTranslateSelection: { phrase, context in onPhraseTap(phrase, context) },
            onExplainSelection: { text, context in onExplainTap(text, context) }
        )
        .background {
            vocabHighlightLayer(rects: wordRects)
                .zIndex(PodcastTranscriptMarkLayer.vocabHighlight.zIndex)
        }
        .overlay {
            if !isSelecting, isCurrent || isNext {
                continuousUnderline(rects: wordRects)
                    .zIndex(PodcastTranscriptMarkLayer.playbackUnderline.zIndex)
            }
        }
        .padding(.horizontal, AppSpacing.s3)
        .padding(.vertical, AppSkin.baseSpacing.compactRowVerticalPadding)
        // Bubble fill + border live in their OWN shape-only layer so the active↔
        // inactive skin crossfade animates on `active` WITHOUT dragging the underline
        // overlay's insert/remove (display↔select) into the same transaction. Scoping
        // `.animation(value: active)` to this token-free shape layer keeps the bg /
        // border glide smooth while the unified text view itself never reflows (same
        // instance → no structural swap to animate). (Earlier the whole block was left
        // un-animated to dodge a hitch, which made the bubble color hard-cut.)
        .background {
            RoundedRectangle(cornerRadius: skin.cornerRadius, style: .continuous)
                .fill(bg)
                .overlay {
                    RoundedRectangle(cornerRadius: skin.cornerRadius, style: .continuous)
                        .stroke(
                            skin.tint.opacity(active ? 0.22 : 0.08),
                            lineWidth: active ? 1 : 0.8
                        )
                }
                .animation(AppMotion.contentFade, value: active)
        }
        .animation(AppMotion.contentFade, value: isSelecting)
    }

    /// 常駐詞庫螢光筆:把命中詞庫的詞（`vocabHighlightIndices`）用其 word rect 畫一條字底
    /// 色帶，並明確放在文字背景層。播放底線是另一個 overlay 層，永遠在其上方。
    @ViewBuilder
    private func vocabHighlightLayer(rects: [Int: CGRect]) -> some View {
        if !vocabHighlightIndices.isEmpty {
            ForEach(vocabHighlightIndices.sorted(), id: \.self) { index in
                if let rect = rects[index] {
                    let bandHeight = rect.height * highlightPreferences.bandFraction
                    RoundedRectangle(cornerRadius: AppRadius.xs, style: .continuous)
                        .fill(
                            highlightPreferences.colorPreset
                                .swiftUIColor(for: colorScheme)
                                .opacity(highlightPreferences.opacity)
                        )
                        // +4:螢光筆刻意比字寬 4pt（左右各 2）包住字邊，更像實體螢光筆；逐詞
                        // 底線無此 padding 故不共用同一 rect 尺寸。高度只取字底 32% 色帶
                        // （position y 貼齊 `rect.maxY`），呈底線式螢光筆。
                        .frame(width: rect.width + 4, height: bandHeight)
                        .position(x: rect.midX, y: rect.maxY - bandHeight / 2)
                        .allowsHitTesting(false)
                }
            }
        }
    }

    /// Continuous word underline for the current / entering ("next") cell. Word rects
    /// come from the unified `UITextView`'s TextKit layout
    /// (`PodcastTextKitWordRects.resolve`, run once per layout pass and cache-guarded),
    /// passed in as `rects` in the TEXT VIEW's own coordinate space. Because this
    /// overlay is hung ON that text view (★B2), no `GeometryReader` translation is
    /// needed. The inner `TimelineView` re-evaluates per display frame and reads the
    /// LIVE playhead via `liveAnchor.value` (the reference defeats the stale-anchor
    /// trap). Across a line break it renders a portal (two capsules) — see
    /// `PodcastUnderlineGeometry.segments`.
    private func continuousUnderline(rects: [Int: CGRect]) -> some View {
        TimelineView(.animation(paused: !isPlaying)) { ctx in
            // Current cell logs `ul.frame`; the entering ("next") cell logs `ul.next`
            // so the second per-frame engine is separable in the trace.
            let _ = PerfLog.underline.tick(isCurrent ? "ul.frame" : "ul.next")
            if wordFollowEnabled {
                let t = PodcastPlaybackClock.projectedTime(
                    anchor: liveAnchor.value,
                    now: ctx.date.timeIntervalSinceReferenceDate,
                    duration: duration
                )
                // Geometry recomputed per frame → motion is continuous with NO
                // animation modifier (a spring chasing a moving target visually
                // skips words). `relayBars` picks the regime: intra-sentence portal,
                // leaving tail-exit, or entering head-enter.
                let bars = relayBars(t: t, rects: rects)
                ForEach(Array(bars.enumerated()), id: \.offset) { _, bar in
                    Capsule()
                        .fill(skin.tint)
                        .frame(width: bar.width, height: 3)
                        // bottomY (word bottom) + 3pt offset + half the 3pt height.
                        .position(x: bar.minX + bar.width / 2, y: bar.bottomY + 4.5)
                }
            }
        }
    }

    /// Picks this cell's underline bars for playhead `t`. Three regimes:
    ///   • CURRENT, mid-sentence → the gliding portal (`segments`, incl. the
    ///     line-break two-capsule handoff).
    ///   • CURRENT, on the last word, with a successor → leaving relay: slide the
    ///     bar off the trailing edge (`tailExit`). Once `fraction` hits 1 (the
    ///     ~55 ms pre-flip window) it has vanished → nothing.
    ///   • NEXT (machinery present, not yet current) → entering relay: before my
    ///     first word, grow the head in from my leading edge (`headEnter`) over the
    ///     predecessor's last-word window; once my first word actually plays (the
    ///     pre-flip seam) draw it normally so becoming current is seamless. Outside
    ///     that window the head is absent (zero/negative fraction → nil).
    private func relayBars(
        t: TimeInterval, rects: [Int: CGRect]
    ) -> [PodcastUnderlineGeometry.Bar] {
        let loc = PodcastWordProgress.locate(time: t, words: words)
        if isCurrent {
            let lastIndex = words.count - 1
            if hasNext, lastIndex >= 0, let lw = rects[lastIndex], loc.index == lastIndex {
                // Exit toward the RIGHT EDGE OF THE LAST WORD'S OWN ROW, not the
                // bubble's full content width: a short last row ("it.", "cleverness.")
                // is far narrower than the widest row, so using content width slides
                // the bar off into the empty space beside the text (a detached
                // floating underline). With the row edge, when the last word is the
                // rightmost on its row (the usual case) the bar retracts rightward to
                // nothing while staying under the text.
                let rowRight = rects.values
                    .filter { abs($0.minY - lw.minY) < lw.height * 0.5 }
                    .map(\.maxX).max() ?? lw.maxX
                return PodcastUnderlineGeometry.tailExit(
                    lastWord: lw, rowRightEdge: rowRight, fraction: loc.fraction
                ).map { [$0] } ?? []
            }
            return PodcastUnderlineGeometry.segments(
                wordRects: rects, activeIndex: loc.index, fraction: loc.fraction
            )
        }
        // isNext: machinery present ahead of the flip so the entering head can lead.
        guard let fw = rects[0], let first = words.first else { return [] }
        if let entry = entryFromTime, t < first.startTime {
            let f = (t - entry) / max(0.0001, first.startTime - entry)
            return PodcastUnderlineGeometry.headEnter(
                firstWord: fw, rowLeftEdge: fw.minX, fraction: f
            ).map { [$0] } ?? []
        }
        // Pre-flip seam: my own words are genuinely playing (not the playhead
        // seeked far past me). The upper bound stops a non-sequential seek from
        // flashing a stale bar on this still-"next" cell in the ~1 tick before
        // `currentId` catches up.
        if t >= first.startTime, t <= (words.last?.endTime ?? first.startTime) {
            return PodcastUnderlineGeometry.segments(
                wordRects: rects, activeIndex: loc.index, fraction: loc.fraction
            )
        }
        return []
    }
}
#endif
