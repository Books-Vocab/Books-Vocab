import SwiftUI
import SwiftData

struct WordDetailSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.kgService) private var kgService
    @State private var localLinkedCardStack: [VocabularyEntry] = []
    @State private var isEditing = false
    @State private var showAddLink = false
    @State private var presenterState: WordDetailPresenter.State?
    @State private var linkError: String?

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
                .overlay(alignment: .top) {
                    if let linkError {
                        AppBanner(
                            message: linkError,
                            systemImage: "exclamationmark.triangle",
                            onDismiss: { self.linkError = nil }
                        )
                        .padding(.top, 4)
                    }
                }
            } else {
                VocabStateMessageCard(
                    title: "載入中".localized,
                    systemImage: "doc.text"
                ) {
                    ProgressView()
                        .controlSize(.small)
                }
                .padding()
            }
        }
        .task(id: "\(entry.id)|\(entry.graphLinksJSON.hashValue)") {
            // Yield once so SwiftUI can render the loading placeholder before
            // we run the (lightweight but synchronous) presentation computation.
            await Task.yield()
            let lookup = VocabularyEntry.buildCardIdLookup(from: allEntries)
            let state = WordDetailPresentation.state(for: entry, in: allEntries, lookup: lookup)
            presenterState = state
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
        // Guard against duplicate add (pending or already linked)
        let allLinks = entry.graphLinksByKind.values.flatMap { $0 }
        guard !allLinks.contains(where: { $0.cardId == toId }) else { return }
        let notebookId = entry.notebookId

        // 1. Optimistic insert — placeholder appears immediately
        let placeholderId = "pending-\(UUID().uuidString)"
        let placeholder = KGCardLinkSummary.pending(id: placeholderId, cardId: toId, word: target.word)
        var current = entry.graphLinksByKind
        current[placeholder.kind, default: []].append(placeholder)
        entry.graphLinksByKind = current

        // 2. Backend call — replace placeholder on success, rollback on failure
        Task {
            do {
                let link = try await kgService.createManualLink(
                    fromId: fromId, toId: toId, notebookId: notebookId
                )
                let summary = KGCardLinkSummary(
                    id: link.id,
                    cardId: toId,
                    word: target.word,
                    kind: link.kind,
                    label: link.kind == "contrasts_with" ? "對比" : "相關",
                    confidence: link.confidence,
                    reason: link.reason
                )
                var updated = entry.graphLinksByKind
                // Remove placeholder from its temporary group
                updated[placeholder.kind]?.removeAll { $0.id == placeholderId }
                if updated[placeholder.kind]?.isEmpty == true {
                    updated.removeValue(forKey: placeholder.kind)
                }
                // Insert real link under correct kind
                updated[link.kind, default: []].append(summary)
                entry.graphLinksByKind = updated
            } catch {
                // Rollback — remove placeholder
                var rollback = entry.graphLinksByKind
                rollback[placeholder.kind]?.removeAll { $0.id == placeholderId }
                if rollback[placeholder.kind]?.isEmpty == true {
                    rollback.removeValue(forKey: placeholder.kind)
                }
                entry.graphLinksByKind = rollback
                linkError = "新增連結失敗".localized
            }
        }
    }

    private func handleDeleteLink(_ link: KGCardLinkSummary) {
        let notebookId = entry.notebookId

        // 1. Optimistic remove
        var current = entry.graphLinksByKind
        current[link.kind]?.removeAll { $0.id == link.id }
        if current[link.kind]?.isEmpty == true {
            current.removeValue(forKey: link.kind)
        }
        entry.graphLinksByKind = current

        // 2. Backend call — rollback on failure (re-insert single link, not full snapshot)
        Task {
            do {
                try await kgService.deleteLink(linkId: link.id, notebookId: notebookId)
            } catch {
                var rollback = entry.graphLinksByKind
                rollback[link.kind, default: []].append(link)
                entry.graphLinksByKind = rollback
                linkError = "刪除連結失敗".localized
            }
        }
    }
}
