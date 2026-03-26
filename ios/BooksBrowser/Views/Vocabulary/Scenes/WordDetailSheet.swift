import SwiftUI
import SwiftData

struct WordDetailSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.kgService) private var kgService
    @State private var localLinkedCardStack: [VocabularyEntry] = []
    @State private var isEditing = false
    @State private var showAddLink = false
    @State private var presenterState: WordDetailPresenter.State?

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
        Group {
            if let presenterState {
                WordDetailPresenter(
                    state: presenterState,
                    wrapInNavigation: wrapInNavigation,
                    onClose: wrapInNavigation ? { dismiss() } : nil,
                    onEdit: wrapInNavigation ? { isEditing = true } : nil,
                    onLinkTapped: handleLinkTap,
                    onToggleExcludeFromReader: { entry.isExcludedFromReader.toggle() },
                    onAddLink: { showAddLink = true },
                    onDeleteLink: handleDeleteLink
                )
            } else {
                ProgressView()
            }
        }
        .task(id: "\(entry.id)|\(entry.graphLinksJSON.hashValue)") {
            let lookup = VocabularyEntry.buildCardIdLookup(from: allEntries)
            presenterState = WordDetailPresentation.state(for: entry, in: allEntries, lookup: lookup)
        }
        .overlay {
            if wrapInNavigation {
                LinkedCardOverlayStack(stack: linkedCardStack, allEntries: allEntries)
            }
        }
        .sheet(isPresented: $isEditing) {
            WordEditSheet(entry: entry)
        }
        .sheet(isPresented: $showAddLink) {
            AddLinkSheet(
                sourceEntry: entry,
                allEntries: allEntries,
                onSelect: handleAddLink
            )
        }
    }

    private var linkedCardStack: Binding<[VocabularyEntry]> {
        externalLinkedCardStack ?? $localLinkedCardStack
    }

    private func handleLinkTap(_ link: KGCardLinkSummary) {
        let lookup = VocabularyEntry.buildCardIdLookup(from: allEntries)
        guard let target = entry.linkedEntry(for: link, lookup: lookup) else { return }
        linkedCardStack.wrappedValue.append(target)
    }

    private func handleAddLink(_ target: VocabularyEntry) {
        guard let fromId = entry.kgCardId, let toId = target.kgCardId else { return }
        let notebookId = entry.notebookId
        Task {
            do {
                let link = try await kgService.createManualLink(
                    fromId: fromId, toId: toId, notebookId: notebookId
                )
                var current = entry.graphLinksByKind
                let summary = KGCardLinkSummary(
                    id: link.id,
                    cardId: toId,
                    word: target.word,
                    kind: link.kind,
                    label: link.kind == "contrasts_with" ? "對比" : "相關",
                    confidence: link.confidence,
                    reason: link.reason
                )
                current[link.kind, default: []].append(summary)
                entry.graphLinksByKind = current
            } catch {
                // sync will reconcile
            }
        }
    }

    private func handleDeleteLink(_ link: KGCardLinkSummary) {
        let notebookId = entry.notebookId
        Task {
            do {
                try await kgService.deleteLink(linkId: link.id, notebookId: notebookId)
                var current = entry.graphLinksByKind
                current[link.kind]?.removeAll { $0.id == link.id }
                if current[link.kind]?.isEmpty == true {
                    current.removeValue(forKey: link.kind)
                }
                entry.graphLinksByKind = current
            } catch {
                // sync will reconcile
            }
        }
    }
}
