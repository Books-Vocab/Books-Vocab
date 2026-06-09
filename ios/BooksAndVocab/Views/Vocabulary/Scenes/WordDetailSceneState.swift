import Foundation
import Observation

@Observable @MainActor
final class WordDetailSceneState {
    var presenterState: WordDetailPresenter.State?
    var linkError: String?

    func refreshPresentation(
        for entry: VocabularyEntry,
        in allEntries: [VocabularyEntry]
    ) {
        let lookup = VocabularyEntry.buildCardIdLookup(from: allEntries)
        presenterState = WordDetailPresentation.state(
            for: entry,
            in: allEntries,
            lookup: lookup
        )
    }

    func dismissLinkError() {
        linkError = nil
    }

    func linkedEntry(
        for link: KGCardLinkSummary,
        from entry: VocabularyEntry,
        in allEntries: [VocabularyEntry]
    ) -> VocabularyEntry? {
        let lookup = VocabularyEntry.buildCardIdLookup(from: allEntries)
        return entry.linkedEntry(for: link, lookup: lookup)
    }

    func addLink(
        target: VocabularyEntry,
        to entry: VocabularyEntry,
        kgService: any KGServing
    ) {
        guard let fromId = entry.kgCardId else { return }
        guard let pending = VocabularyGraphLinkMutation.beginManualLink(from: entry, to: target) else { return }
        let notebookId = entry.notebookId

        Task { @MainActor in
            do {
                let link = try await kgService.createManualLink(
                    fromId: fromId,
                    toId: pending.targetCardId,
                    notebookId: notebookId
                )
                VocabularyGraphLinkMutation.commitManualLink(pending, result: link, on: entry)
            } catch {
                VocabularyGraphLinkMutation.rollbackManualLink(pending, on: entry)
                linkError = "新增連結失敗".localized
            }
        }
    }

    func deleteLink(
        _ link: KGCardLinkSummary,
        from entry: VocabularyEntry,
        allEntries: [VocabularyEntry],
        kgService: any KGServing
    ) {
        let notebookId = entry.notebookId
        let peer = linkedEntry(for: link, from: entry, in: allEntries)
        let removed = VocabularyGraphLinkMutation.removeLink(link, from: entry, peer: peer)

        Task { @MainActor in
            do {
                try await kgService.deleteLink(linkId: link.id, notebookId: notebookId)
            } catch {
                VocabularyGraphLinkMutation.rollbackLinkRemoval(removed, source: entry, peer: peer)
                linkError = "刪除連結失敗".localized
            }
        }
    }

    func hideLink(
        _ link: KGCardLinkSummary,
        from entry: VocabularyEntry,
        allEntries: [VocabularyEntry],
        kgService: any KGServing
    ) {
        setLinkHidden(true, link: link, entry: entry, allEntries: allEntries, kgService: kgService)
    }

    func unhideLink(
        _ link: KGCardLinkSummary,
        from entry: VocabularyEntry,
        allEntries: [VocabularyEntry],
        kgService: any KGServing
    ) {
        setLinkHidden(false, link: link, entry: entry, allEntries: allEntries, kgService: kgService)
    }

    private func setLinkHidden(
        _ hidden: Bool,
        link: KGCardLinkSummary,
        entry: VocabularyEntry,
        allEntries: [VocabularyEntry],
        kgService: any KGServing
    ) {
        let notebookId = entry.notebookId
        let peer = linkedEntry(for: link, from: entry, in: allEntries)
        VocabularyGraphLinkMutation.setHidden(hidden, for: link, source: entry, peer: peer)

        Task { @MainActor in
            do {
                if hidden {
                    try await kgService.hideLink(linkId: link.id, notebookId: notebookId)
                } else {
                    try await kgService.unhideLink(linkId: link.id, notebookId: notebookId)
                }
            } catch {
                VocabularyGraphLinkMutation.setHidden(!hidden, for: link, source: entry, peer: peer)
                linkError = hidden ? "隱藏連結失敗".localized : "恢復連結失敗".localized
            }
        }
    }
}
