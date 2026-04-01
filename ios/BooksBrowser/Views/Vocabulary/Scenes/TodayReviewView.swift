import SwiftUI
import SwiftData
import os

struct TodayReviewSession: Identifiable {
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
            onClose: onClose,
            onAdvanceReveal: {
                withAnimation(AppMotion.reviewRevealSpring) {
                    state.advanceReveal()
                }
            },
            onCollapseReveal: {
                withAnimation(AppMotion.reviewRevealSpring) {
                    state.retractReveal()
                }
            },
            onShuffle: state.shuffleQueue,
            onPrevious: state.goPrevious,
            onNext: state.goNext,
            onForgot: {
                state.submit(.forgot, container: modelContext.container, reviewSettings: reviewSettingsStore.settings)
            },
            onRemembered: {
                state.submit(.remembered, container: modelContext.container, reviewSettings: reviewSettingsStore.settings)
            },
            onLinkTap: state.handleLinkTap,
            onToggleAutoPlay: state.toggleAutoPlay,
            onToggleAutoPlayPause: state.toggleAutoPlayPause,
            onDetailTap: state.handleDetailTap
        )
        .toastOverlay()
        .overlay {
            LinkedCardOverlayStack(stack: $state.linkedCardStack, allEntries: allEntries)
        }
        .sheet(item: $state.tappedLink) { link in
            LinkReasonSheet(link: link, onNavigate: { state.navigateToLinkedCard(link: link) })
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
