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

    let onClose: () -> Void

    init(entries: [VocabularyEntry], allEntries: [VocabularyEntry], onClose: @escaping () -> Void) {
        _state = State(initialValue: TodayReviewState(entries: entries, allEntries: allEntries))
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
            onForgot: { state.submit(.forgot, modelContext: modelContext, reviewSettings: reviewSettingsStore.settings) },
            onRemembered: { state.submit(.remembered, modelContext: modelContext, reviewSettings: reviewSettingsStore.settings) },
            onLinkTap: state.handleLinkTap,
            onToggleAutoPlay: state.toggleAutoPlay,
            onToggleAutoPlayPause: state.toggleAutoPlayPause,
            onDetailTap: state.handleDetailTap
        )
        .overlay {
            LinkedCardOverlayStack(stack: $state.linkedCardStack)
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
            }
            guard authManager.isLoggedIn, !authManager.isDemoMode else { return }
            Task {
                await kgService.pushReviewQuietly(container: modelContext.container)
            }
        }
    }
}
