#if os(iOS)
import SwiftUI

struct PodcastTranscriptViewport: View {
    @ObserveInjection private var inject

    let sentences: [PodcastSentence]
    let renderState: SubtitleRenderState?
    let liveAnchor: PodcastLiveAnchor
    let duration: TimeInterval
    let isPlaying: Bool
    let hostNames: [String]
    let subtitleSize: PodcastSubtitleSize
    let initialScrollPositionResolved: Bool
    let scrollLeadId: Int?
    let lookedUpWords: Set<String>
    let highlightPreferences: VocabHighlightPreferences
    let speakerSlots: [String: Int]
    let onSentenceTap: (PodcastSentence) -> Void
    let onWordTap: (String, String) -> Void
    let onPhraseTap: (String, String) -> Void
    let onExplainTap: (String, String) -> Void

    @Environment(\.appSkin) private var skin
    @Environment(\.colorScheme) private var colorScheme
    @AppStorage("podcast.wordFollowEnabled") private var wordFollowEnabled: Bool = true

    @State private var isFollowing = true
    @State private var selectionState: PodcastSentenceSelection?
    @State private var scrollAnimationTask: Task<Void, Never>?
    @State private var didApplyInitialScrollPosition = false

    private var currentId: Int? { renderState?.sentenceId }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                transcriptColumn
                    .background(selectionDismissCatcher)
            }
            .scrollIndicators(.hidden)
            .overlay(alignment: .bottom) {
                if shouldShowFollowControl {
                    followPill()
                        .padding(.bottom, skin.spacing.sectionGap)
                        .transition(.readerPanelReveal)
                }
            }
            #if DEBUG
            .onChange(of: currentId) { old, id in
                logBoundary(from: old, to: id)
            }
            #endif
            .onChange(of: scrollLeadId) { _, id in
                followScroll(to: id, proxy: proxy)
            }
            .onChange(of: isFollowing) { _, following in
                guard following else { return }
                followScroll(to: currentId, proxy: proxy)
            }
            .onChange(of: PodcastTranscriptIdentity(sentences: sentences)) { _, _ in
                didApplyInitialScrollPosition = false
                applyInitialScrollPositionIfNeeded(proxy: proxy)
                if didApplyInitialScrollPosition == false {
                    followScroll(to: currentId, proxy: proxy)
                }
            }
            .onChange(of: initialScrollPositionResolved) { _, _ in
                applyInitialScrollPositionIfNeeded(proxy: proxy)
            }
            .task {
                applyInitialScrollPositionIfNeeded(proxy: proxy)
            }
            .onAppear {
                PerfLog.scroll.startFrameSampler("podcast.display")
            }
            .onDisappear {
                PerfLog.scroll.stopFrameSampler("podcast.display")
                PerfLog.scroll.stopFrameSampler("podcast.follow")
            }
            .simultaneousGesture(
                DragGesture(minimumDistance: 8).onChanged { _ in
                    if PodcastTranscriptScrollPolicy.shouldDisengageFollowOnManualDrag(isFollowing: isFollowing) {
                        isFollowing = false
                    }
                }
            )
            .animation(AppMotion.contentFade, value: isFollowing)
        }
        .enableInjection()
    }

    private var transcriptColumn: some View {
        PodcastTranscriptColumn(
            sentences: sentences,
            renderState: renderState,
            currentId: currentId,
            scrollLeadId: scrollLeadId,
            lookedUpWords: lookedUpWords,
            highlightPreferences: highlightPreferences,
            selectionState: selectionState,
            subtitleSize: subtitleSize,
            wordFollowEnabled: wordFollowEnabled,
            isPlaying: isPlaying,
            duration: duration,
            liveAnchor: liveAnchor,
            speakerSlots: speakerSlots,
            skin: skin,
            colorScheme: colorScheme,
            onSentenceTap: { sentence in
                if !isFollowing {
                    withAnimation(AppMotion.standardSpring) { isFollowing = true }
                }
                onSentenceTap(sentence)
            },
            onWordTap: onWordTap,
            onPhraseTap: { phrase, context in
                selectionState = nil
                onPhraseTap(phrase, context)
            },
            onExplainTap: { text, context in
                selectionState = nil
                onExplainTap(text, context)
            },
            onEnterSelection: { selection in
                isFollowing = false
                selectionState = selection
            },
            onClearSelection: { selectionState = nil }
        )
    }

    @ViewBuilder
    private var selectionDismissCatcher: some View {
        if selectionState != nil {
            Color.clear
                .contentShape(Rectangle())
                .onTapGesture { selectionState = nil }
                .accessibilityHidden(true)
        }
    }

    private func followScroll(to id: Int?, proxy: ScrollViewProxy) {
        guard let id = PodcastTranscriptScrollPolicy.followTarget(
            isFollowing: isFollowing,
            didApplyInitialScrollPosition: didApplyInitialScrollPosition,
            targetId: id
        ) else { return }
        scrollAnimationTask?.cancel()
        scrollAnimationTask = Task {
            try? await Task.sleep(for: .milliseconds(50))
            guard !Task.isCancelled else { return }
            PerfLog.scroll.startFrameSampler("podcast.follow")
            PerfLog.scroll.mark("followScroll.begin", "id=\(id)")
            PerfLog.scroll.measure("scrollTo", "id=\(id)") {
                withAnimation(AppMotion.podcastFollowScroll) {
                    proxy.scrollTo(id, anchor: .center)
                }
            }
            try? await Task.sleep(for: .milliseconds(900))
            PerfLog.scroll.stopFrameSampler("podcast.follow")
        }
    }

    private func applyInitialScrollPositionIfNeeded(proxy: ScrollViewProxy) {
        let decision = PodcastTranscriptScrollPolicy.initialDecision(
            initialScrollPositionResolved: initialScrollPositionResolved,
            didApplyInitialScrollPosition: didApplyInitialScrollPosition,
            currentId: currentId
        )
        guard decision != .none else { return }
        didApplyInitialScrollPosition = true
        guard case let .scrollTo(id) = decision else { return }
        scrollAnimationTask?.cancel()
        scrollAnimationTask = Task {
            await Task.yield()
            guard !Task.isCancelled else { return }
            proxy.scrollTo(id, anchor: .center)
        }
    }

    #if DEBUG
    private func logBoundary(from oldId: Int?, to newId: Int?) {
        func f(_ v: TimeInterval) -> String { String(format: "%.3f", v) }
        let projT = PodcastPlaybackClock.projectedTime(
            anchor: liveAnchor.value,
            now: Date().timeIntervalSinceReferenceDate,
            duration: duration
        )
        guard let newId, let to = sentences.first(where: { $0.id == newId }) else {
            PerfLog.underline.mark("boundary", "clear from=\(oldId.map(String.init) ?? "nil") projT=\(f(projT))")
            return
        }
        guard let oldId, let from = sentences.first(where: { $0.id == oldId }),
              let lw = from.words.last, let fw = to.words.first else {
            PerfLog.underline.mark("boundary", "init to=\(newId) mStart=\(f(to.startTime)) projT=\(f(projT))")
            return
        }
        let gap = to.startTime - from.endTime
        PerfLog.underline.mark(
            "boundary",
            "\(oldId)->\(newId) projT=\(f(projT)) nEnd=\(f(from.endTime)) mStart=\(f(to.startTime)) "
                + "gap=\(f(gap)) lastW=\(f(lw.startTime))..\(f(lw.endTime)) firstW=\(f(fw.startTime))..\(f(fw.endTime))"
        )
    }
    #endif

    private var shouldShowFollowControl: Bool {
        #if targetEnvironment(macCatalyst)
        let isCatalyst = true
        #else
        let isCatalyst = false
        #endif
        return PodcastFollowControlVisibility.shouldShow(
            isFollowing: isFollowing,
            hasActiveSelection: selectionState != nil,
            isCatalyst: isCatalyst
        )
    }

    @ViewBuilder
    private func followPill() -> some View {
        if isFollowing {
            pillCapsule {
                isFollowing = false
            } content: {
                Image(systemName: "pause.fill")
                    .font(skin.typography.iconTiny)
                    .foregroundStyle(skin.palette.secondaryText)
                Text(L10n.string("停止跟隨"))
                    .font(skin.typography.caption)
                    .foregroundStyle(skin.palette.primaryText)
            }
        } else {
            pillCapsule {
                withAnimation(AppMotion.standardSpring) {
                    isFollowing = true
                }
            } content: {
                if let speaker = renderState?.speaker {
                    let idx = hostNames.firstIndex(of: speaker)
                    Circle()
                        .fill(PodcastSpeakerTint.color(for: idx, skin: skin))
                        .frame(width: 6, height: 6)
                }
                Text(L10n.string("追隨當前"))
                    .font(skin.typography.caption)
                    .foregroundStyle(skin.palette.primaryText)
                Image(systemName: "arrow.down")
                    .font(skin.typography.iconTiny)
                    .foregroundStyle(skin.palette.secondaryText)
            }
        }
    }

    @ViewBuilder
    private func pillCapsule<Content: View>(
        action: @escaping () -> Void,
        @ViewBuilder content: () -> Content
    ) -> some View {
        Button(action: action) {
            HStack(spacing: 6) { content() }
                .padding(.horizontal, AppSkin.baseSpacing.controlHorizontalPadding)
                .padding(.vertical, AppSpacing.s2)
                .background(
                    AppRoundedRect(roundness: AppRoundness.pill)
                        .fill(skin.palette.cardBackground.opacity(0.96))
                        .overlay(AppRoundedRect(roundness: AppRoundness.pill).stroke(skin.palette.cardBorder, lineWidth: 1))
                )
        }
        .buttonStyle(.plain)
    }
}
#endif
