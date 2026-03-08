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

    let onClose: () -> Void

    init(entries: [VocabularyEntry], onClose: @escaping () -> Void) {
        _queue = State(initialValue: entries)
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
            canGoNext: currentIndex < queue.count - 1
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
        withAnimation(.spring(response: 0.42, dampingFraction: 0.88)) {
            revealStage.advance()
        }
    }

    private func retractReveal() {
        guard !isAdvancing else { return }
        withAnimation(.spring(response: 0.42, dampingFraction: 0.88)) {
            revealStage.retract()
        }
    }

    private func shuffleQueue() {
        guard queue.count > 1, !isAdvancing else { return }
        withAnimation(.spring(response: 0.32, dampingFraction: 0.9)) {
            queue.shuffle()
            currentIndex = 0
            revealStage = .front
        }
    }

    private func goPrevious() {
        guard currentIndex > 0 else { return }
        withAnimation(.spring(response: 0.3, dampingFraction: 0.86)) {
            revealStage = .front
            currentIndex -= 1
        }
    }

    private func goNext() {
        guard currentIndex < queue.count - 1 else { return }
        withAnimation(.spring(response: 0.3, dampingFraction: 0.86)) {
            revealStage = .front
            currentIndex += 1
        }
    }

    private func submit(_ feedback: ReviewFeedback) {
        guard let current = currentEntry, !isAdvancing else { return }
        isAdvancing = true

        current.applyReviewFeedback(feedback)

        withAnimation(.spring(response: 0.32, dampingFraction: 0.86)) {
            revealStage = .front
            currentIndex += 1
        }

        Task { @MainActor in
            try? modelContext.save()
            isAdvancing = false
        }
    }
}
