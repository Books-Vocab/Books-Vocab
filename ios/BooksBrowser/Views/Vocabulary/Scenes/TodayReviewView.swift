import SwiftUI
import SwiftData

struct TodayReviewSession: Identifiable {
    let id = UUID()
    let entries: [VocabularyEntry]
}

enum TodayReviewRevealStage: Int {
    case front
    case back
    case details

    var showsAnswer: Bool {
        self != .front
    }

    var showsDetails: Bool {
        self == .details
    }

    mutating func advance() {
        switch self {
        case .front:
            self = .back
        case .back, .details:
            self = .details
        }
    }

    mutating func retract() {
        switch self {
        case .front: break
        case .back: self = .front
        case .details: self = .back
        }
    }
}

struct TodayReviewView: View {
    @Environment(\.modelContext) private var modelContext
    @Query private var allEntries: [VocabularyEntry]

    @State private var queue: [VocabularyEntry]
    @State private var currentIndex = 0
    @State private var revealStage: TodayReviewRevealStage = .front
    @State private var isAdvancing = false
    @State private var linkedCardStack: [VocabularyEntry] = []
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

    private var presenterState: TodayReviewPresenterState {
        TodayReviewPresenterState(
            progressText: progressText,
            currentCard: currentCardState,
            revealStage: revealStage,
            canShuffle: queue.count > 1,
            canGoPrevious: currentIndex > 0,
            canGoNext: currentIndex < queue.count - 1,
            rememberedFeedbackTrigger: rememberedFeedbackTrigger,
            forgotFeedbackTrigger: forgotFeedbackTrigger,
            persistenceFailureTrigger: persistenceFailureTrigger,
            persistenceErrorMessage: persistenceErrorMessage,
            isAdvancing: isAdvancing
        )
    }

    private var currentCardState: TodayReviewPresenterState.CurrentCard? {
        guard let current = currentEntry else { return nil }
        let card = current.cardPresentation
        let fullGroups = card.linkGroups
        let compactGroups = fullGroups.map { fullGroup in
            let limitedGroup = fullGroup.limited(to: 2)
            return TodayReviewPresenterState.LinkGroup(
                id: fullGroup.id,
                label: fullGroup.label,
                items: limitedGroup.items,
                overflowCount: limitedGroup.overflowed(relativeToFullGroup: fullGroup)
            )
        }

        return .init(
            card: card,
            linkGroups: compactGroups
        )
    }

    private var currentEntry: VocabularyEntry? {
        guard currentIndex < queue.count else { return nil }
        return queue[currentIndex]
    }

    private var progressText: String {
        "\(min(currentIndex + 1, queue.count)) / \(queue.count)"
    }

    private func handleLinkTap(_ link: KGCardLinkSummary) {
        guard let target = allEntries.first(where: { $0.kgCardId == link.cardId }) else { return }
        linkedCardStack.append(target)
    }

    private func advanceReveal() {
        guard !isAdvancing else { return }
        withAnimation(AppMotion.reviewRevealSpring) {
            revealStage.advance()
        }
    }

    private func retractReveal() {
        guard !isAdvancing else { return }
        withAnimation(AppMotion.reviewRevealSpring) {
            revealStage.retract()
        }
    }

    private func shuffleQueue() {
        guard queue.count > 1, !isAdvancing else { return }
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

    private func submit(_ feedback: ReviewFeedback) {
        guard let current = currentEntry, !isAdvancing else { return }
        isAdvancing = true
        pendingSaveTask?.cancel()
        persistenceErrorMessage = nil

        current.applyReviewFeedback(feedback)
        switch feedback {
        case .remembered:
            rememberedFeedbackTrigger += 1
        case .forgot:
            forgotFeedbackTrigger += 1
        }

        withAnimation(AppMotion.reviewCardSwapSpring) {
            revealStage = .front
            currentIndex += 1
        }
        if currentIndex >= queue.count {
            ReviewSessionStore.clear()
        }

        pendingSaveTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(220))
            do {
                try modelContext.save()
            } catch {
                withAnimation(AppMotion.phaseChange) {
                    persistenceErrorMessage = L10n.format("複習結果尚未寫入本機：%@", error.localizedDescription)
                }
                persistenceFailureTrigger += 1
            }
            isAdvancing = false
        }
    }
}
