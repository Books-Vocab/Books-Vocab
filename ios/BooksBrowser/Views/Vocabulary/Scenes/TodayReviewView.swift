import SwiftUI
import SwiftData

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
    @Query private var allEntries: [VocabularyEntry]

    @State private var queue: [VocabularyEntry]
    @State private var currentIndex = 0
    @State private var revealStage: TodayReviewRevealStage = .front
    @State private var linkedCardStack: [VocabularyEntry] = []
    @State private var forgotCount = 0
    @State private var rememberedCount = 0
    @State private var rememberedFeedbackTrigger = 0
    @State private var forgotFeedbackTrigger = 0
    @State private var persistenceFailureTrigger = 0
    @State private var persistenceErrorMessage: String?
    @State private var pendingSaveTask: Task<Void, Never>?

    let onClose: () -> Void

    init(entries: [VocabularyEntry], onClose: @escaping () -> Void) {
        let ordered = ReviewSessionStore.loadOrder(availableEntries: entries) ?? entries
        _queue = State(initialValue: ordered)
        self.onClose = onClose
    }

    var body: some View {
        TodayReviewPresenter(
            state: presenterState,
            onClose: onClose,
            onAdvanceReveal: advanceReveal,
            onCollapseReveal: retractReveal,
            onShuffle: shuffleQueue,
            onPrevious: goPrevious,
            onNext: goNext,
            onForgot: { submit(.forgot) },
            onRemembered: { submit(.remembered) },
            onLinkTap: handleLinkTap
        )
        .overlay {
            LinkedCardOverlayStack(stack: $linkedCardStack)
        }
    }

    // MARK: - State Projection

    private var presenterState: TodayReviewPresenterState {
        TodayReviewPresenterState(
            progressText: progressText,
            currentCard: currentCardState,
            nextCard: nextCardState,
            revealStage: revealStage,
            canShuffle: queue.count > 1,
            canGoPrevious: currentIndex > 0,
            canGoNext: currentIndex < queue.count - 1,
            remainingCount: max(queue.count - currentIndex - 1, 0),
            forgotCount: forgotCount,
            rememberedCount: rememberedCount,
            rememberedFeedbackTrigger: rememberedFeedbackTrigger,
            forgotFeedbackTrigger: forgotFeedbackTrigger,
            persistenceFailureTrigger: persistenceFailureTrigger,
            persistenceErrorMessage: persistenceErrorMessage
        )
    }

    private var nextCardState: TodayReviewPresenterState.CurrentCard? {
        let nextIndex = currentIndex + 1
        guard nextIndex < queue.count else { return nil }
        return .init(card: queue[nextIndex].cardPresentation, linkGroups: [])
    }

    private var currentCardState: TodayReviewPresenterState.CurrentCard? {
        guard let current = currentEntry else { return nil }
        let card = current.cardPresentation
        let compactGroups = card.linkGroups.map { fullGroup in
            let limited = fullGroup.limited(to: 2)
            return TodayReviewPresenterState.LinkGroup(
                id: fullGroup.id,
                label: fullGroup.label,
                items: limited.items,
                overflowCount: limited.overflowed(relativeToFullGroup: fullGroup)
            )
        }
        return .init(card: card, linkGroups: compactGroups)
    }

    private var currentEntry: VocabularyEntry? {
        guard currentIndex < queue.count else { return nil }
        return queue[currentIndex]
    }

    private var progressText: String {
        "\(min(currentIndex + 1, queue.count)) / \(queue.count)"
    }

    // MARK: - Actions

    private func handleLinkTap(_ link: KGCardLinkSummary) {
        guard let target = allEntries.first(where: { $0.kgCardId == link.cardId }) else { return }
        linkedCardStack.append(target)
    }

    private func advanceReveal() {
        withAnimation(AppMotion.reviewRevealSpring) {
            revealStage.advance()
        }
    }

    private func retractReveal() {
        withAnimation(AppMotion.reviewRevealSpring) {
            revealStage.retract()
        }
    }

    private func shuffleQueue() {
        guard queue.count > 1 else { return }
        withAnimation(AppMotion.reviewNavigationSpring) {
            queue.shuffle()
            currentIndex = 0
            revealStage = .front
        }
        ReviewSessionStore.saveOrder(queue.map(\.id))
    }

    private func goPrevious() {
        guard currentIndex > 0 else { return }
        withAnimation(AppMotion.reviewNavigationSpring) {
            revealStage = .front
            currentIndex -= 1
        }
    }

    private func goNext() {
        guard currentIndex < queue.count - 1 else { return }
        withAnimation(AppMotion.reviewNavigationSpring) {
            revealStage = .front
            currentIndex += 1
        }
    }

    /// 歸類卡片：記錄回饋 → 推進 index → 延後寫入
    /// 所有動畫由 Presenter 的 flingCard 控制，此處不包 withAnimation
    private func submit(_ feedback: ReviewFeedback) {
        guard let current = currentEntry else { return }
        pendingSaveTask?.cancel()
        persistenceErrorMessage = nil

        current.applyReviewFeedback(feedback)

        switch feedback {
        case .remembered:
            rememberedFeedbackTrigger += 1
            rememberedCount += 1
        case .forgot:
            forgotFeedbackTrigger += 1
            forgotCount += 1
        }

        revealStage = .front
        currentIndex += 1

        if currentIndex >= queue.count {
            ReviewSessionStore.clear()
        }

        // 延後 save — 避免 @Query 重算在升頂動畫期間觸發 re-render
        pendingSaveTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(500))
            do {
                try modelContext.save()
            } catch {
                withAnimation(AppMotion.phaseChange) {
                    persistenceErrorMessage = L10n.format("複習結果尚未寫入本機：%@", error.localizedDescription)
                }
                persistenceFailureTrigger += 1
            }
        }
    }
}
