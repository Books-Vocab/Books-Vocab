import SwiftUI
import SwiftData
import Inject

private enum ReviewTiming {
    static let shortcutHintDismissDelay: Duration = .seconds(3)
}

enum ReviewIntent {
    case reveal
    case collapse
    case forgot
    case remembered
    case previous
    case next
    case shuffle
    case showDetail
    case toggleAutoplay
    case toggleAutoplayPause
    case changeAutoplaySpeed
    case toggleAutoplaySound
    case close
    case showHelp
}

struct TodayReviewSession: Identifiable, Equatable {
    static func == (lhs: TodayReviewSession, rhs: TodayReviewSession) -> Bool { lhs.id == rhs.id }
    let id = UUID()
    let entries: [VocabularyEntry]
}

enum TodayReviewRevealStage: Int {
    case front
    case back

    var showsAnswer: Bool { self == .back }

    mutating func advance() {
        switch self {
        case .front: self = .back
        case .back: break
        }
    }

    mutating func retract() {
        switch self {
        case .front: break
        case .back: self = .front
        }
    }
}

struct CollocationExplainItem: Identifiable {
    let id = UUID()
    let collocation: String
    let context: String
    let existingExplanation: String?
}

struct TodayReviewView: View {
    @ObserveInjection private var inject
    @Environment(\.modelContext) private var modelContext
    @Environment(\.reviewSettingsStore) private var reviewSettingsStore
    @Environment(\.toastCoordinator) private var toastCoordinator

    @State private var state: TodayReviewState

    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager

    @State private var isHelpPresented = false
    @State private var showAddLink = false
    @State private var explainSheetItem: CollocationExplainItem? = nil
    @State private var currentCollocationExplanations: [String: String] = [:]
    #if targetEnvironment(macCatalyst)
    @State private var hasConsumedShortcutHint = false
    @AppStorage("kg_mac_review_shortcut_hint_shown") private var hasShownShortcutHint = false
    @State private var shortcutHintTask: Task<Void, Never>?
    #endif

    private let allEntries: [VocabularyEntry]
    let onClose: () -> Void

    init(
        entries: [VocabularyEntry],
        allEntries: [VocabularyEntry],
        currentUserID: String?,
        onClose: @escaping () -> Void
    ) {
        _state = State(initialValue: TodayReviewState(
            entries: entries,
            allEntries: allEntries,
            currentUserID: currentUserID
        ))
        self.allEntries = allEntries
        self.onClose = onClose
    }

    var body: some View {
        let _ = PerfLog.review.mark("treview.held", "inst=#\(state.instanceSeq) viewBody")
        return TodayReviewPresenter(
            state: state.presenterState,
            isHelpPresented: isHelpPresented,
            showFirstRunHint: shouldShowFirstRunHint,
            onClose: { perform(.close) },
            onAdvanceReveal: {
                perform(.reveal)
            },
            onCollapseReveal: {
                perform(.collapse)
            },
            onShuffle: { perform(.shuffle) },
            onPrevious: { perform(.previous) },
            onNext: { perform(.next) },
            onForgot: {
                perform(.forgot)
            },
            onRemembered: {
                perform(.remembered)
            },
            onLinkTap: state.handleLinkTap,
            onAddLink: { showAddLink = true },
            onToggleAutoPlay: { perform(.toggleAutoplay) },
            onToggleAutoPlayPause: { perform(.toggleAutoplayPause) },
            onChangeAutoPlaySpeed: { perform(.changeAutoplaySpeed) },
            onToggleAutoPlaySound: { perform(.toggleAutoplaySound) },
            onDetailTap: { perform(.showDetail) },
            onToggleHelp: { perform(.showHelp) },
            onExplainCollocation: { collocation in
                guard let entry = state.currentEntry else { return }
                explainSheetItem = CollocationExplainItem(
                    collocation: collocation,
                    context: entry.context,
                    existingExplanation: nil
                )
            },
            onViewCollocationExplanation: { collocation in
                guard let entry = state.currentEntry else { return }
                explainSheetItem = CollocationExplainItem(
                    collocation: collocation,
                    context: entry.context,
                    existingExplanation: entry.collocationExplanations[collocation]
                )
            },
            onDeleteCollocationExplanation: { collocation in
                updateCollocationExplanation(nil, for: collocation)
            },
            collocationExplanations: currentCollocationExplanations
        )
        .toastOverlay()
        .task {
            refreshCurrentCollocationExplanations()
            // A restored session may hold answers whose background DB flush
            // failed last run (flushed=false). Re-flush them so the card
            // schedule catches up; idempotent, so a clean restore is a no-op.
            let toast = toastCoordinator
            state.reflushUnflushedRestoredAnswers(
                container: modelContext.container,
                reviewSettings: reviewSettingsStore.settings,
                onSaveFailure: { toast.error(L10n.string("todayReview.saveFailure")) }
            )
        }
        .overlay {
            LinkedCardOverlayStack(stack: $state.linkedCardStack, allEntries: allEntries)
        }
        .toastSheet(item: $state.tappedLink) { link in
            LinkReasonSheet(
                link: link,
                onNavigate: { state.navigateToLinkedCard(link: link) },
                onHide: {
                    guard let entry = state.currentEntry else { return }
                    let notebookId = entry.notebookId
                    let peer = state.linkedEntryLookup[link.cardId]
                    state.hideLink(link)
                    Task {
                        do {
                            try await kgService.hideLink(linkId: link.id, notebookId: notebookId)
                        } catch {
                            entry.mutateLink(id: link.id) { $0.withHidden(false) }
                            peer?.mutateLink(id: link.id) { $0.withHidden(false) }
                            state.rebuildCacheForEntry(entry)
                        }
                    }
                }
            )
            .appSheet(.medium)
        }
        .toastSheet(isPresented: $showAddLink) {
            if let entry = state.currentEntry {
                AddLinkSheet(
                    sourceEntry: entry,
                    allEntries: allEntries,
                    onSelect: { target in handleAddLink(target, for: entry) }
                )
            }
        }
        .toastSheet(item: $explainSheetItem) { item in
            CollocationExplainSheet(
                collocation: item.collocation,
                context: item.context,
                existingExplanation: item.existingExplanation,
                onSave: { explanation in
                    updateCollocationExplanation(explanation, for: item.collocation)
                },
                onDelete: {
                    updateCollocationExplanation(nil, for: item.collocation)
                }
            )
            .appSheet(.medium)
        }
        .onChange(of: state.currentEntry?.id) { _, _ in
            refreshCurrentCollocationExplanations()
        }
        .onDisappear {
            // Stop autoplay on dismiss — this onDisappear runs on every target
            // (it sits outside the macCatalyst #if below), so it is the single
            // teardown point for the 4s autoplay loop. Without this the loop
            // keeps mutating currentIndex/revealStage in the background and
            // retains the state object. stopAutoPlay() is idempotent.
            state.stopAutoPlay()
            // Cancel the init-time background cache build too, so an early
            // dismiss does not run it to completion and mutate torn-down state.
            state.cancelBackgroundWork()

            let completed = state.currentIndex >= state.queue.count
            if !completed {
                let durationMs = Int(Date().timeIntervalSince(state.sessionStartTime) * 1000)
                AppAnalytics.track(.reviewSessionEnded(
                    remembered: state.rememberedCount,
                    forgot: state.forgotCount,
                    completed: false,
                    durationMs: durationMs
                ))
            }

            // Single persistence point. The per-flip submit path is store-free (a
            // per-card SwiftData save merged into the main context and froze the
            // next-card render); all deferred answers flush here in ONE batched save.
            // Finalize the crash-recovery snapshot and push to backend ONLY after the
            // store confirms — a failed flush keeps the snapshot so restore retries.
            // The flush is a detached background-context save, so this is NOT the
            // synchronous main-context onDisappear save that trips the teardown trap.
            let loggedIn = authManager.isLoggedIn && !authManager.isDemoMode
            let container = modelContext.container
            let toast = toastCoordinator
            state.flushPendingAnswers(
                container: container,
                reviewSettings: reviewSettingsStore.settings,
                onFinalize: {
                    if completed { state.clearSnapshot() } else { state.persistSnapshot() }
                    guard loggedIn else { return }
                    Task { await kgService.pushReviewQuietly(container: container) }
                },
                onFailure: { toast.error(L10n.string("todayReview.saveFailure")) }
            )
        }
        #if targetEnvironment(macCatalyst)
        .focusable()
        .onKeyPress { press in
            handleCatalystKey(press) ? .handled : .ignored
        }
        .onAppear {
            guard !hasShownShortcutHint else { return }
            shortcutHintTask?.cancel()
            shortcutHintTask = Task { @MainActor in
                try? await Task.sleep(for: ReviewTiming.shortcutHintDismissDelay)
                guard !Task.isCancelled else { return }
                hasConsumedShortcutHint = true
                hasShownShortcutHint = true
            }
        }
        .onDisappear {
            shortcutHintTask?.cancel()
            shortcutHintTask = nil
        }
        // 複習快捷鍵說明(View menu)— review session active 時才 publish → menu 自動 disable。
        .focusedSceneValue(\.showReviewHelp, ShowReviewHelpAction { isHelpPresented = true })
        #endif
        .enableInjection()
    }

    private func refreshCurrentCollocationExplanations() {
        currentCollocationExplanations = state.currentEntry?.collocationExplanations ?? [:]
    }

    private func updateCollocationExplanation(_ explanation: String?, for collocation: String) {
        var updated = currentCollocationExplanations
        if let explanation {
            updated[collocation] = explanation
        } else {
            updated.removeValue(forKey: collocation)
        }
        currentCollocationExplanations = updated
        state.currentEntry?.collocationExplanations = updated
        modelContext.safeSave()
    }

    private var shouldShowFirstRunHint: Bool {
        #if targetEnvironment(macCatalyst)
        return !hasShownShortcutHint && !hasConsumedShortcutHint && !state.isAutoPlaying && state.currentIndex < min(state.queue.count, 3)
        #else
        return false
        #endif
    }

    #if targetEnvironment(macCatalyst)
    /// Hardware-keyboard shortcuts on Mac Catalyst (replaces the old AppKit
    /// macKeyResponder path). Requires the view to hold keyboard focus.
    private func handleCatalystKey(_ press: KeyPress) -> Bool {
        guard state.linkedCardStack.isEmpty else { return false }
        switch press.key {
        case .space:
            return perform(state.revealStage == .front ? .reveal : .collapse)
        case .leftArrow:
            return perform(state.isAutoPlaying ? .previous : .forgot)
        case .rightArrow:
            return perform(state.isAutoPlaying ? .next : .remembered)
        case .upArrow:
            return perform(.previous)
        case .downArrow:
            return perform(.next)
        case .escape:
            if isHelpPresented {
                isHelpPresented = false
                return true
            }
            return perform(.close)
        default:
            switch press.characters.lowercased() {
            case "d": return perform(.showDetail)
            case "s": return perform(.shuffle)
            case "p": return perform(state.isAutoPlaying ? .toggleAutoplayPause : .toggleAutoplay)
            case "?", "/": return perform(.showHelp)
            default: return false
            }
        }
    }
    #endif

    private func handleAddLink(_ target: VocabularyEntry, for entry: VocabularyEntry) {
        guard let fromId = entry.kgCardId, let toId = target.kgCardId else { return }
        let allLinks = entry.graphLinksByKind.values.flatMap { $0 }
        guard !allLinks.contains(where: { $0.cardId == toId }) else { return }
        let notebookId = entry.notebookId

        // Optimistic insert — placeholder
        let placeholderId = "pending-\(UUID().uuidString)"
        let placeholder = KGCardLinkSummary.pending(id: placeholderId, cardId: toId, word: target.word)
        var current = entry.graphLinksByKind
        current[placeholder.kind, default: []].append(placeholder)
        entry.graphLinksByKind = current
        state.rebuildCacheForEntry(entry)

        // Backend call — replace placeholder on success, rollback on failure
        Task {
            do {
                let link = try await kgService.createManualLink(fromId: fromId, toId: toId, notebookId: notebookId)
                let summary = KGCardLinkSummary(
                    id: link.id, cardId: toId, word: target.word,
                    kind: link.kind,
                    label: link.kind == "contrasts_with" ? "對比" : "相關",
                    confidence: link.confidence, reason: link.reason, hidden: false
                )
                var updated = entry.graphLinksByKind
                updated[placeholder.kind]?.removeAll { $0.id == placeholderId }
                if updated[placeholder.kind]?.isEmpty == true { updated.removeValue(forKey: placeholder.kind) }
                updated[link.kind, default: []].append(summary)
                entry.graphLinksByKind = updated
                state.rebuildCacheForEntry(entry)
            } catch {
                var rollback = entry.graphLinksByKind
                rollback[placeholder.kind]?.removeAll { $0.id == placeholderId }
                if rollback[placeholder.kind]?.isEmpty == true { rollback.removeValue(forKey: placeholder.kind) }
                entry.graphLinksByKind = rollback
                state.rebuildCacheForEntry(entry)
            }
        }
    }

    @discardableResult
    private func perform(_ intent: ReviewIntent) -> Bool {
        switch intent {
        case .reveal:
            guard state.revealStage == .front, state.currentEntry != nil else { return false }
            withAnimation(AppMotion.reviewRevealSpring) {
                state.advanceReveal()
            }
            return true

        case .collapse:
            guard state.revealStage == .back, state.currentEntry != nil else { return false }
            withAnimation(AppMotion.reviewRevealSpring) {
                state.retractReveal()
            }
            return true

        case .forgot:
            guard !state.isAutoPlaying, state.currentEntry != nil else { return false }
            state.submit(
                .forgot,
                container: modelContext.container,
                reviewSettings: reviewSettingsStore.settings
            )
            return true

        case .remembered:
            guard !state.isAutoPlaying, state.currentEntry != nil else { return false }
            state.submit(
                .remembered,
                container: modelContext.container,
                reviewSettings: reviewSettingsStore.settings
            )
            return true

        case .previous:
            guard state.currentIndex > 0 else { return false }
            state.goPrevious()
            return true

        case .next:
            guard state.currentIndex < state.queue.count - 1 else { return false }
            state.goNext()
            return true

        case .shuffle:
            guard !state.isAutoPlaying, state.queue.count - state.currentIndex > 1 else { return false }
            state.shuffleQueue()
            return true

        case .showDetail:
            guard state.currentEntry != nil else { return false }
            state.handleDetailTap()
            return true

        case .toggleAutoplay:
            state.toggleAutoPlay()
            return true

        case .toggleAutoplayPause:
            guard state.isAutoPlaying else { return false }
            state.toggleAutoPlayPause()
            return true

        case .changeAutoplaySpeed:
            state.changeAutoplaySpeed(to: state.autoplaySpeed.next)
            return true

        case .toggleAutoplaySound:
            state.toggleAutoplaySound()
            return true

        case .close:
            onClose()
            return true

        case .showHelp:
            isHelpPresented.toggle()
            return true
        }
    }

}

// MARK: - Preview

#Preview("TodayReview / Session") {
    AppThemeContainer {
        TodayReviewView(
            entries: TodayReviewViewPreviewData.sampleEntries,
            allEntries: TodayReviewViewPreviewData.sampleEntries,
            currentUserID: "preview-user",
            onClose: {}
        )
        .modelContainer(for: [VocabularyEntry.self, ReviewRecord.self, Notebook.self], inMemory: true)
    }
    .environmentObject(AppAppearanceStore.preview)
}

private enum TodayReviewViewPreviewData {
    static let sampleEntries: [VocabularyEntry] = {
        let e1 = VocabularyEntry(
            word: "meticulous",
            translation: "一絲不苟的",
            context: "The editor was meticulous about every detail.",
            explanation: "做事非常細心、注意細節。",
            partOfSpeech: "adj.",
            bookTitle: "Designing Interfaces",
            chapterTitle: "Writing Tone"
        )
        e1.syncState = .synced
        e1.reviewMode = .recognition

        let e2 = VocabularyEntry(
            word: "ephemeral",
            translation: "短暫的",
            context: "Social media posts are ephemeral by nature.",
            explanation: "形容事物存在時間極短。",
            partOfSpeech: "adj.",
            bookTitle: "Designing Interfaces",
            chapterTitle: "Writing Tone"
        )
        e2.syncState = .synced
        e2.reviewMode = .recognition

        return [e1, e2]
    }()
}
