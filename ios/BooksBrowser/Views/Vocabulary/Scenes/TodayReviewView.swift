import SwiftUI
import SwiftData
import os

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

struct TodayReviewView: View {
    @Environment(\.modelContext) private var modelContext
    @Environment(\.reviewSettingsStore) private var reviewSettingsStore

    @State private var state: TodayReviewState

    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager

    @State private var isHelpPresented = false
    @State private var hasConsumedShortcutHint = false
    @AppStorage("kg_mac_review_shortcut_hint_shown") private var hasShownShortcutHint = false

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
        TodayReviewPresenter(
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
            onToggleAutoPlay: { perform(.toggleAutoplay) },
            onToggleAutoPlayPause: { perform(.toggleAutoplayPause) },
            onDetailTap: { perform(.showDetail) },
            onToggleHelp: { perform(.showHelp) }
        )
        .toastOverlay()
        .overlay {
            LinkedCardOverlayStack(stack: $state.linkedCardStack, allEntries: allEntries)
        }
        .toastSheet(item: $state.tappedLink) { link in
            LinkReasonSheet(
                link: link,
                onNavigate: { state.navigateToLinkedCard(link: link) },
                onHide: {
                    let notebookId = state.currentEntry?.notebookId ?? "default"
                    state.hideLink(link)
                    Task {
                        do {
                            try await kgService.hideLink(linkId: link.id, notebookId: notebookId)
                        } catch {
                            state.unhideLink(link)
                        }
                    }
                }
            )
            .appSheet(.medium)
        }
        .onDisappear {
            if state.currentIndex < state.queue.count {
                let durationMs = Int(Date().timeIntervalSince(state.sessionStartTime) * 1000)
                AppAnalytics.track(.reviewSessionEnded(
                    remembered: state.rememberedCount,
                    forgot: state.forgotCount,
                    completed: false,
                    durationMs: durationMs
                ))
                state.persistSnapshot()
            } else {
                state.clearSnapshot()
            }

            guard authManager.isLoggedIn, !authManager.isDemoMode else { return }
            Task {
                await kgService.pushReviewQuietly(container: modelContext.container)
            }
        }
        #if os(macOS)
        .macKeyResponder(active: state.linkedCardStack.isEmpty) { key in
            handleMacKeyPress(key)
        }
        .onAppear {
            guard !hasShownShortcutHint else { return }
            DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
                hasConsumedShortcutHint = true
                hasShownShortcutHint = true
            }
        }
        #endif
    }

    private var shouldShowFirstRunHint: Bool {
        #if os(macOS)
        return !hasShownShortcutHint && !hasConsumedShortcutHint && !state.isAutoPlaying && state.currentIndex < min(state.queue.count, 3)
        #else
        return false
        #endif
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
            state.submit(.forgot, container: modelContext.container, reviewSettings: reviewSettingsStore.settings)
            return true

        case .remembered:
            guard !state.isAutoPlaying, state.currentEntry != nil else { return false }
            state.submit(.remembered, container: modelContext.container, reviewSettings: reviewSettingsStore.settings)
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

        case .close:
            onClose()
            return true

        case .showHelp:
            isHelpPresented.toggle()
            return true
        }
    }

    #if os(macOS)
    private func handleMacKeyPress(_ key: MacKeyPress) -> Bool {
        guard state.linkedCardStack.isEmpty else { return false }

        switch key {
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
        case .character(let chars):
            switch chars {
            case "d":
                return perform(.showDetail)
            case "s":
                return perform(.shuffle)
            case "p":
                return perform(state.isAutoPlaying ? .toggleAutoplayPause : .toggleAutoplay)
            case "?", "/":
                return perform(.showHelp)
            default:
                return false
            }
        }
    }
    #endif
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
