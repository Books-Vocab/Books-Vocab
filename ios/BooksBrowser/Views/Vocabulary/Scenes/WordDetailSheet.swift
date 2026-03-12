import SwiftUI
import SwiftData

struct WordDetailSheet: View {
    @Environment(\.dismiss) private var dismiss
    @State private var localLinkedCardStack: [VocabularyEntry] = []
    @State private var isEditing = false

    @Bindable var entry: VocabularyEntry
    let allEntries: [VocabularyEntry]
    private let wrapInNavigation: Bool
    private let externalLinkedCardStack: Binding<[VocabularyEntry]>?

    init(
        entry: VocabularyEntry,
        allEntries: [VocabularyEntry] = [],
        wrapInNavigation: Bool = true,
        linkedCardStack: Binding<[VocabularyEntry]>? = nil
    ) {
        self.entry = entry
        self.allEntries = allEntries
        self.wrapInNavigation = wrapInNavigation
        self.externalLinkedCardStack = linkedCardStack
    }

    var body: some View {
        WordDetailPresenter(
            state: presenterState,
            wrapInNavigation: wrapInNavigation,
            onClose: wrapInNavigation ? { dismiss() } : nil,
            onEdit: wrapInNavigation ? { isEditing = true } : nil,
            onLinkTapped: handleLinkTap
        )
        .overlay {
            if wrapInNavigation {
                LinkedCardOverlayStack(stack: linkedCardStack, allEntries: allEntries)
            }
        }
        .sheet(isPresented: $isEditing) {
            WordEditSheet(entry: entry)
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
