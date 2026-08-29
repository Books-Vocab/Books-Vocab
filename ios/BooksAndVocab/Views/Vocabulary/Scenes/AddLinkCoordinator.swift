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

enum AddLinkDetailMaterializationState: Equatable {
    case ready(senseCount: Int)
    case missingExample(senseCount: Int)
    case providerDecodeError
    case recovered(senseCount: Int)

    var accessibilityValue: String {
        switch self {
        case .ready(let senseCount):
            return "ready-senses-\(senseCount)"
        case .missingExample(let senseCount):
            return "missing-example-senses-\(senseCount)"
        case .providerDecodeError:
            return "provider-decode-error-retryable"
        case .recovered(let senseCount):
            return "recovered-senses-\(senseCount)"
        }
    }
}

struct AddLinkDetailProjection: Equatable {
    struct Sense: Equatable {
        let id: String
        let partOfSpeech: String?
        let definition: String
        let translation: String?
        let examples: [String]
    }

    struct Provenance: Equatable {
        let provider: String?
        let source: String
        let chapter: String?
        let context: String
    }

    let word: String
    let translation: String
    let senses: [Sense]
    let forms: [String]
    let provenance: Provenance
    let state: AddLinkDetailMaterializationState

    var hasMissingExample: Bool {
        senses.contains { $0.examples.isEmpty }
    }
}

private struct AddLinkDetailPayload: Decodable {
    let provider: String?
    let senses: [AddLinkDetailPayloadSense]
    let forms: [String]?
}

private struct AddLinkDetailPayloadSense: Decodable {
    let id: String?
    let partOfSpeech: String?
    let definition: String
    let translation: String?
    let examples: [String]?
}

private enum AddLinkDetailPayloadDecode {
    case plain
    case decoded(AddLinkDetailPayload)
    case malformed
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

    nonisolated static func lookupEvidence(
        for entry: VocabularyEntry,
        recoveringProviderError: Bool = false
    ) -> String {
        func normalized(_ value: String?) -> String {
            guard let value else { return "" }
            return value.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
        }

        let detail = dictionaryDetailProjection(
            for: entry,
            recoveringProviderError: recoveringProviderError
        )
        let primarySense = detail.senses.first?.definition
        let primaryExample = detail.senses.first?.examples.first
        var evidence = [
            "word=\(normalized(entry.word))",
            "translation=\(normalized(entry.translation))",
            "sense=\(normalized(primarySense))",
            "example=\(normalized(primaryExample))",
            "source=\(normalized(entry.bookTitle))",
            "chapter=\(normalized(entry.chapterTitle))",
            "detail.state=\(detail.state.accessibilityValue)",
            "detail.senses=\(detail.senses.count)"
        ]

        for (senseIndex, sense) in detail.senses.enumerated() {
            evidence.append("detail.sense[\(senseIndex + 1)]=\(normalized(sense.definition))")
            evidence.append(
                "detail.sense[\(senseIndex + 1)].partOfSpeech=\(normalized(sense.partOfSpeech))"
            )
            evidence.append(
                "detail.sense[\(senseIndex + 1)].translation=\(normalized(sense.translation))"
            )
            for (exampleIndex, example) in sense.examples.enumerated() {
                evidence.append(
                    "detail.example[\(senseIndex + 1),\(exampleIndex + 1)]=\(normalized(example))"
                )
            }
        }

        evidence.append("detail.missing-example=\(detail.hasMissingExample ? "true" : "false")")
        evidence.append("detail.forms=\(detail.forms.map(normalized).joined(separator: ", "))")
        evidence.append("detail.provenance.provider=\(normalized(detail.provenance.provider))")
        evidence.append("detail.provenance.source=\(normalized(detail.provenance.source))")
        evidence.append("detail.provenance.chapter=\(normalized(detail.provenance.chapter))")
        evidence.append("detail.provenance.context=\(normalized(detail.provenance.context))")
        if case .providerDecodeError = detail.state {
            evidence.append("detail.recovery=retryable")
        }
        return evidence.joined(separator: " | ")
    }

    nonisolated static func dictionaryDetailProjection(
        for entry: VocabularyEntry,
        recoveringProviderError: Bool = false
    ) -> AddLinkDetailProjection {
        switch decodeDetailPayload(entry.explanation) {
        case .plain:
            return legacyDetailProjection(for: entry, state: nil)
        case .decoded(let payload):
            return payloadDetailProjection(payload, for: entry)
        case .malformed:
            if recoveringProviderError {
                return legacyDetailProjection(
                    for: entry,
                    state: .recovered(senseCount: 1),
                    useExplanation: false
                )
            }
            return AddLinkDetailProjection(
                word: entry.word,
                translation: entry.translation,
                senses: [],
                forms: formValues(for: entry, payloadForms: nil),
                provenance: provenance(for: entry, provider: nil),
                state: .providerDecodeError
            )
        }
    }

    nonisolated static func detailIdentifier(for entry: VocabularyEntry) -> String {
        "addLink.local.result.\(entry.kgCardId ?? entry.id.uuidString)"
    }

    nonisolated static func detailStateIdentifier(for entry: VocabularyEntry) -> String {
        "\(detailIdentifier(for: entry)).state"
    }

    nonisolated static func detailSenseIdentifier(for entry: VocabularyEntry, index: Int) -> String {
        "\(detailIdentifier(for: entry)).sense.\(index + 1)"
    }

    nonisolated static func detailExampleIdentifier(
        for entry: VocabularyEntry,
        senseIndex: Int,
        exampleIndex: Int
    ) -> String {
        "\(detailIdentifier(for: entry)).sense.\(senseIndex + 1).example.\(exampleIndex + 1)"
    }

    nonisolated static func detailMissingExampleIdentifier(
        for entry: VocabularyEntry,
        senseIndex: Int
    ) -> String {
        "\(detailIdentifier(for: entry)).sense.\(senseIndex + 1).example.missing"
    }

    nonisolated static func detailFormsIdentifier(for entry: VocabularyEntry) -> String {
        "\(detailIdentifier(for: entry)).forms"
    }

    nonisolated static func detailProvenanceIdentifier(for entry: VocabularyEntry) -> String {
        "\(detailIdentifier(for: entry)).provenance"
    }

    nonisolated static func detailRetryIdentifier(for entry: VocabularyEntry) -> String {
        "\(detailIdentifier(for: entry)).provider.retry"
    }

    private static let detailPayloadPrefix = "kg.dictionary.detail.v1:"

    private nonisolated static func decodeDetailPayload(
        _ explanation: String?
    ) -> AddLinkDetailPayloadDecode {
        guard let explanation,
              explanation.hasPrefix(detailPayloadPrefix) else {
            return .plain
        }
        let rawPayload = String(explanation.dropFirst(detailPayloadPrefix.count))
        guard let data = rawPayload.data(using: .utf8),
              let payload = try? JSONDecoder().decode(AddLinkDetailPayload.self, from: data),
              !payload.senses.isEmpty,
              payload.senses.allSatisfy({ !$0.definition.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) else {
            return .malformed
        }
        return .decoded(payload)
    }

    private nonisolated static func payloadDetailProjection(
        _ payload: AddLinkDetailPayload,
        for entry: VocabularyEntry
    ) -> AddLinkDetailProjection {
        let senses = payload.senses.enumerated().map { index, value in
            AddLinkDetailProjection.Sense(
                id: cleaned(value.id) ?? "sense-\(index + 1)",
                partOfSpeech: cleaned(value.partOfSpeech) ?? cleaned(entry.partOfSpeech),
                definition: value.definition,
                translation: cleaned(value.translation) ?? cleaned(entry.translation),
                examples: cleanedValues(value.examples ?? [])
            )
        }
        let state: AddLinkDetailMaterializationState = senses.contains { $0.examples.isEmpty }
            ? .missingExample(senseCount: senses.count)
            : .ready(senseCount: senses.count)
        return AddLinkDetailProjection(
            word: entry.word,
            translation: entry.translation,
            senses: senses,
            forms: formValues(for: entry, payloadForms: payload.forms),
            provenance: provenance(for: entry, provider: cleaned(payload.provider)),
            state: state
        )
    }

    private nonisolated static func legacyDetailProjection(
        for entry: VocabularyEntry,
        state: AddLinkDetailMaterializationState?,
        useExplanation: Bool = true
    ) -> AddLinkDetailProjection {
        let definition = (useExplanation ? cleaned(entry.explanation) : nil)
            ?? cleaned(entry.translation)
            ?? entry.word
        let senses = [
            AddLinkDetailProjection.Sense(
                id: "sense-1",
                partOfSpeech: cleaned(entry.partOfSpeech),
                definition: definition,
                translation: cleaned(entry.translation),
                examples: cleanedValues(entry.reviewExamples)
            )
        ]
        let resolvedState = state ?? (senses[0].examples.isEmpty
            ? .missingExample(senseCount: 1)
            : .ready(senseCount: 1))
        return AddLinkDetailProjection(
            word: entry.word,
            translation: entry.translation,
            senses: senses,
            forms: formValues(for: entry, payloadForms: nil),
            provenance: provenance(for: entry, provider: nil),
            state: resolvedState
        )
    }

    private nonisolated static func formValues(
        for entry: VocabularyEntry,
        payloadForms: [String]?
    ) -> [String] {
        var values = payloadForms ?? []
        if let rootForm = entry.rootForm { values.append(rootForm) }
        values.append(contentsOf: entry.inflections)
        return cleanedValues(values)
    }

    private nonisolated static func provenance(
        for entry: VocabularyEntry,
        provider: String?
    ) -> AddLinkDetailProjection.Provenance {
        AddLinkDetailProjection.Provenance(
            provider: provider,
            source: entry.bookTitle,
            chapter: cleaned(entry.chapterTitle),
            context: entry.context
        )
    }

    private nonisolated static func cleaned(_ value: String?) -> String? {
        guard let value else { return nil }
        let result = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return result.isEmpty ? nil : result
    }

    private nonisolated static func cleanedValues(_ values: [String]) -> [String] {
        var result: [String] = []
        for value in values {
            guard let value = cleaned(value), !result.contains(value) else { continue }
            result.append(value)
        }
        return result
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
