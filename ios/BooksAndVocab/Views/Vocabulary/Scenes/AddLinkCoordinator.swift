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

enum AddLinkLookupState: Equatable {
    case idle
    case results(count: Int)
    case empty
    case loading(attempt: Int)
    case error(attempt: Int)
    case retry(attempt: Int)

    var accessibilityValue: String {
        switch self {
        case .idle:
            return "idle"
        case .results(let count):
            return "results-\(count)"
        case .empty:
            return "empty"
        case .loading(let attempt):
            return "loading-attempt-\(attempt)"
        case .error(let attempt):
            return "error-attempt-\(attempt)"
        case .retry(let attempt):
            return "retry-attempt-\(attempt)"
        }
    }
}

@Observable @MainActor
final class AddLinkCoordinator {
    private(set) var actionPhase: AddLinkActionPhase = .idle
    private(set) var actionError: AddLinkActionError?

    private var actionGeneration = 0
    private var actionTask: Task<Void, Never>?
    private var actionTaskToken = 0

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
            Self.isEligibleTarget(entry, for: sourceEntry)
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

    nonisolated static func lookupState(
        query: String,
        candidateCount: Int,
        creationPhase: AddLinkCreationPhase,
        creationAttempt: Int
    ) -> AddLinkLookupState {
        let trimmedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedQuery.isEmpty else { return .idle }

        let attempt = max(creationAttempt, 1)
        switch creationPhase {
        case .running:
            return creationAttempt > 1
                ? .retry(attempt: attempt)
                : .loading(attempt: attempt)
        case .failed:
            return .error(attempt: attempt)
        default:
            return candidateCount > 0 ? .results(count: candidateCount) : .empty
        }
    }

    nonisolated static func lookupEvidence(for entry: VocabularyEntry) -> String {
        func normalized(_ value: String?) -> String {
            guard let value else { return "" }
            return value.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
        }

        return [
            "word=\(normalized(entry.word))",
            "translation=\(normalized(entry.translation))",
            "sense=\(normalized(entry.explanation))",
            "example=\(normalized(entry.primaryReviewExample))",
            "source=\(normalized(entry.bookTitle))",
            "chapter=\(normalized(entry.chapterTitle))"
        ].joined(separator: " | ")
    }

    func linkExisting(
        target: VocabularyEntry,
        sourceEntry: VocabularyEntry,
        using service: any GraphServing
    ) async {
        guard !Task.isCancelled else { return }
        let generation = beginAction()
        guard sourceEntry.modelContext != nil,
              let sourceCardID = sourceEntry.kgCardId,
              Self.hasUsableCardID(sourceCardID) else {
            failAction(.missingSourceCard, generation: generation)
            return
        }
        guard let targetCardID = target.kgCardId,
              Self.hasUsableCardID(targetCardID) else {
            failAction(.missingTargetCard, generation: generation)
            return
        }
        guard Self.isEligibleTarget(target, for: sourceEntry) else {
            failAction(.existingLinkFailed, generation: generation)
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
        actionPhase = .linking
        actionError = nil
        actionTaskToken += 1
        let taskToken = actionTaskToken
        actionTask = Task { @MainActor [weak self] in
            guard let self else { return }
            await self.linkExisting(
                target: target,
                sourceEntry: sourceEntry,
                using: service
            )
            self.clearActionTask(taskToken: taskToken)
        }
    }

    func cancelAction() {
        let wasRunning = actionPhase == .linking
        actionTaskToken += 1
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

    private func clearActionTask(taskToken: Int) {
        guard actionTaskToken == taskToken else { return }
        actionTask = nil
    }

    private nonisolated static func hasUsableCardID(_ cardID: String?) -> Bool {
        guard let cardID else { return false }
        return !cardID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private nonisolated static func isEligibleTarget(
        _ target: VocabularyEntry,
        for sourceEntry: VocabularyEntry
    ) -> Bool {
        target.id != sourceEntry.id
            && target.notebookId == sourceEntry.notebookId
            && target.kgCardId != sourceEntry.kgCardId
            && !target.isArchived
            && target.syncAction != .delete
            && hasUsableCardID(target.kgCardId)
    }

    private static func isConflict(_ error: KGError) -> Bool {
        guard case .httpError(let statusCode, _) = error else { return false }
        return statusCode == 409
    }
}
