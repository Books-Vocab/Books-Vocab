import Foundation
import Observation
import SwiftData

enum AddLinkActionError: Equatable {
    case missingSourceCard
    case missingTargetCard
    case duplicateLink
    case missingLink
    case invalidLink
    case existingLinkRefreshFailed
    case existingLinkFailed
}

enum AddLinkActionPhase: Equatable {
    case idle
    case linking
    case succeeded
    case cancelled
    case failed
}

@Observable @MainActor
final class AddLinkCoordinator {
    private(set) var actionPhase: AddLinkActionPhase = .idle
    private(set) var actionError: AddLinkActionError?

    private var actionGeneration = 0
    private var actionTask: Task<Void, Never>?

    nonisolated static func localCandidates(
        query: String,
        sourceEntry: VocabularyEntry,
        allEntries: [VocabularyEntry]
    ) -> [VocabularyEntry] {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return [] }
        let linkedIDs = Set(sourceEntry.graphLinksByKind.values.flatMap { $0 }.map(\.cardId))
        let folded = trimmed.folding(
            options: [.caseInsensitive, .diacriticInsensitive],
            locale: .current
        )
        return Array(allEntries.lazy.filter { entry in
            entry.id != sourceEntry.id
                && entry.notebookId == sourceEntry.notebookId
                && entry.kgCardId?.isEmpty == false
                && entry.syncAction != .delete
                && !entry.isArchived
                && !(entry.kgCardId.map(linkedIDs.contains) ?? false)
                && (
                    entry.word.folding(
                        options: [.caseInsensitive, .diacriticInsensitive],
                        locale: .current
                    ).contains(folded)
                    || entry.translation.folding(
                        options: [.caseInsensitive, .diacriticInsensitive],
                        locale: .current
                    ).contains(folded)
                )
        }.prefix(20))
    }

    func linkExisting(
        target: VocabularyEntry,
        sourceEntry: VocabularyEntry,
        using service: any GraphServing
    ) async {
        let generation = beginAction()
        guard sourceEntry.modelContext != nil,
              let sourceCardID = sourceEntry.kgCardId,
              !sourceCardID.isEmpty else {
            failAction(.missingSourceCard, generation: generation)
            return
        }
        guard let targetCardID = target.kgCardId, !targetCardID.isEmpty else {
            failAction(.missingTargetCard, generation: generation)
            return
        }
        let alreadyLinked = sourceEntry.graphLinksByKind.values
            .flatMap { $0 }
            .contains { $0.cardId == targetCardID }
        guard !alreadyLinked else {
            actionPhase = .succeeded
            actionError = nil
            return
        }
        guard let pending = VocabularyGraphLinkMutation.beginManualLink(
            from: sourceEntry,
            to: target
        ) else {
            failAction(.existingLinkFailed, generation: generation)
            return
        }

        do {
            let link = try await service.createManualLink(
                fromId: sourceCardID,
                toId: pending.targetCardId,
                notebookId: sourceEntry.notebookId
            )
            try Task.checkCancellation()
            guard isCurrentAction(generation) else {
                VocabularyGraphLinkMutation.rollbackManualLink(pending, on: sourceEntry)
                return
            }
            guard !link.id.isEmpty else {
                VocabularyGraphLinkMutation.rollbackManualLink(pending, on: sourceEntry)
                failAction(.missingLink, generation: generation)
                return
            }
            guard link.fromId == sourceCardID, link.toId == targetCardID else {
                VocabularyGraphLinkMutation.rollbackManualLink(pending, on: sourceEntry)
                failAction(.invalidLink, generation: generation)
                return
            }
            VocabularyGraphLinkMutation.commitManualLink(pending, result: link, on: sourceEntry)
            actionPhase = .succeeded
            actionError = nil
        } catch is CancellationError {
            VocabularyGraphLinkMutation.rollbackManualLink(pending, on: sourceEntry)
            cancelCurrentAction(generation)
        } catch let error as KGError where Self.isConflict(error) {
            do {
                let links = try await service.pullGraphLinks(notebookId: sourceEntry.notebookId)
                try Task.checkCancellation()
                guard isCurrentAction(generation) else {
                    VocabularyGraphLinkMutation.rollbackManualLink(pending, on: sourceEntry)
                    return
                }
                guard let existingLink = links.first(where: {
                    $0.fromId == sourceCardID && $0.toId == targetCardID
                }) else {
                    throw KGError.serverError("Graph link refresh returned no matching link")
                }
                guard !existingLink.id.isEmpty else {
                    throw KGError.serverError("Graph link refresh returned an empty link id")
                }
                VocabularyGraphLinkMutation.commitManualLink(
                    pending,
                    result: existingLink,
                    on: sourceEntry
                )
                actionPhase = .succeeded
                actionError = nil
            } catch is CancellationError {
                VocabularyGraphLinkMutation.rollbackManualLink(pending, on: sourceEntry)
                cancelCurrentAction(generation)
            } catch {
                VocabularyGraphLinkMutation.rollbackManualLink(pending, on: sourceEntry)
                failAction(.existingLinkRefreshFailed, generation: generation)
            }
        } catch {
            VocabularyGraphLinkMutation.rollbackManualLink(pending, on: sourceEntry)
            failAction(.existingLinkFailed, generation: generation)
        }
    }

    func startLinkExisting(
        target: VocabularyEntry,
        sourceEntry: VocabularyEntry,
        using service: any GraphServing
    ) {
        cancelAction()
        actionTask = Task { @MainActor [weak self] in
            guard let self else { return }
            await self.linkExisting(
                target: target,
                sourceEntry: sourceEntry,
                using: service
            )
            self.actionTask = nil
        }
    }

    func cancelAction() {
        let wasRunning = actionPhase == .linking
        actionGeneration += 1
        actionTask?.cancel()
        actionTask = nil
        guard wasRunning else { return }
        actionPhase = .cancelled
        actionError = nil
    }

    func cancel() {
        cancelAction()
    }

    private func beginAction() -> Int {
        actionGeneration += 1
        actionPhase = .linking
        actionError = nil
        return actionGeneration
    }

    private func isCurrentAction(_ generation: Int) -> Bool {
        generation == actionGeneration && !Task.isCancelled
    }

    private func cancelCurrentAction(_ generation: Int) {
        guard generation == actionGeneration else { return }
        actionPhase = .cancelled
        actionError = nil
    }

    private func failAction(_ error: AddLinkActionError, generation: Int) {
        guard generation == actionGeneration else { return }
        actionPhase = .failed
        actionError = error
    }

    private static func isConflict(_ error: KGError) -> Bool {
        guard case .httpError(let statusCode, _) = error else { return false }
        return statusCode == 409
    }
}
