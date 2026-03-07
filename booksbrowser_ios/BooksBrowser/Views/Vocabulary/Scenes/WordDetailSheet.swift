import SwiftUI
import SwiftData

struct WordDetailSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Query private var allEntries: [VocabularyEntry]
    @State private var localLinkedCardStack: [VocabularyEntry] = []

    let entry: VocabularyEntry
    private let wrapInNavigation: Bool
    private let externalLinkedCardStack: Binding<[VocabularyEntry]>?

    init(
        entry: VocabularyEntry,
        wrapInNavigation: Bool = true,
        linkedCardStack: Binding<[VocabularyEntry]>? = nil
    ) {
        self.entry = entry
        self.wrapInNavigation = wrapInNavigation
        self.externalLinkedCardStack = linkedCardStack
    }

    var body: some View {
        WordDetailPresenter(
            state: presenterState,
            wrapInNavigation: wrapInNavigation,
            onClose: wrapInNavigation ? { dismiss() } : nil,
            onLinkTapped: handleLinkTap
        )
        .overlay {
            if wrapInNavigation {
                LinkedCardOverlayStack(stack: linkedCardStack)
            }
        }
    }

    private var linkedCardStack: Binding<[VocabularyEntry]> {
        externalLinkedCardStack ?? $localLinkedCardStack
    }

    private var presenterState: WordDetailPresenter.State {
        WordDetailPresentation.state(for: entry, in: allEntries)
    }

    private func handleLinkTap(_ link: KGCardLinkSummary) {
        guard let target = entry.linkedEntry(for: link, in: allEntries) else { return }
        linkedCardStack.wrappedValue.append(target)
    }
}
