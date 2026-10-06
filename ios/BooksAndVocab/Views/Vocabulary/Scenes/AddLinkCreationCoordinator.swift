import Foundation
import Observation
import SwiftData

enum AddLinkCreationPhase: Equatable {
    case idle
    case running
    case succeeded
    case succeededWithWarnings
    case failed
    case blocked
    case cancelled

    var isRunning: Bool { self == .running }
}

enum AddLinkLocalTargetState: Equatable {
    case missing
    case pending
    case failed
    case archived
    case active
    case source
}

/// Coordinates the client half of missing-target Add Link.
///
/// It never creates a local VocabularyEntry. The server operation is
/// authoritative; after the link commits, the existing serialized pull
/// projects the canonical card and graph state into SwiftData.
@Observable @MainActor
final class AddLinkCreationCoordinator {
    private(set) var phase: AddLinkCreationPhase = .idle
    private(set) var steps: [PipelineStep] = []
    private(set) var fraction: Double = 0
    private(set) var operationId: String?
    private(set) var message: String?

    private var generation = 0
    private var lastSequence = -1
    private var pollingTask: Task<Void, Never>?

    nonisolated static func localTargetState(
        query: String,
        sourceEntry: VocabularyEntry,
        allEntries: [VocabularyEntry]
    ) -> AddLinkLocalTargetState {
        let normalizedQuery = normalizeWord(query)
        guard !normalizedQuery.isEmpty else { return .missing }
        if normalizeWord(sourceEntry.word) == normalizedQuery { return .source }

        guard let target = allEntries.first(where: {
            $0.id != sourceEntry.id
                && $0.notebookId == sourceEntry.notebookId
                && normalizeWord($0.word) == normalizedQuery
                && $0.syncAction != .delete
        }) else { return .missing }

        if target.isArchived { return .archived }
        if target.isFailedAdd || target.syncState == .failed { return .failed }
        if target.isPendingAdd || target.kgCardId == nil { return .pending }
        return .active
    }

    nonisolated private static func normalizeWord(_ word: String) -> String {
        word.trimmingCharacters(in: .whitespacesAndNewlines)
            .folding(options: [.caseInsensitive, .diacriticInsensitive], locale: .current)
    }

    func start(
        word: String,
        sourceEntry: VocabularyEntry,
        allEntries: [VocabularyEntry],
        operationService: any AddLinkOperationServing,
        syncService: any VocabularySyncServing,
        container: ModelContainer
    ) {
        cancel()
        let trimmedWord = word.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedWord.isEmpty else {
            phase = .blocked
            message = L10n.string("找不到符合的單字")
            return
        }

        switch Self.localTargetState(query: trimmedWord, sourceEntry: sourceEntry, allEntries: allEntries) {
        case .missing:
            break
        case .pending, .failed:
            phase = .blocked
            message = L10n.string("此單字尚未同步，無法建立連結")
            return
        case .archived:
            phase = .blocked
            message = L10n.string("封存")
            return
        case .active:
            phase = .blocked
            message = L10n.string("已建立")
            return
        case .source:
            phase = .blocked
            message = L10n.string("新增連結失敗")
            return
        }

        guard let sourceCardID = sourceEntry.kgCardId, !sourceCardID.isEmpty else {
            phase = .blocked
            message = L10n.string("此單字尚未同步，無法建立連結")
            return
        }

        generation += 1
        let currentGeneration = generation
        operationId = nil
        lastSequence = -1
        message = nil
        steps = Self.initialSteps()
        fraction = 0
        phase = .running

        let request = KGAddLinkOperationRequest(
            fromId: sourceCardID,
            targetWord: trimmedWord,
            translation: nil,
            context: sourceEntry.context,
            source: Self.source(for: sourceEntry),
            sourceLang: sourceEntry.sourceLang,
            targetLang: sourceEntry.targetLang
        )
        let idempotencyKey = UUID().uuidString.lowercased()

        pollingTask = Task { @MainActor [weak self] in
            guard let self else { return }
            await self.run(
                request: request,
                notebookId: sourceEntry.notebookId,
                idempotencyKey: idempotencyKey,
                operationService: operationService,
                syncService: syncService,
                container: container,
                generation: currentGeneration
            )
            if self.generation == currentGeneration { self.pollingTask = nil }
        }
    }

    func cancel() {
        generation += 1
        pollingTask?.cancel()
        pollingTask = nil
        if phase == .running {
            phase = .cancelled
            message = nil
        }
    }

    private func run(
        request: KGAddLinkOperationRequest,
        notebookId: String,
        idempotencyKey: String,
        operationService: any AddLinkOperationServing,
        syncService: any VocabularySyncServing,
        container: ModelContainer,
        generation: Int
    ) async {
        do {
            let first = try await operationService.startAddLinkOperation(
                request: request, notebookId: notebookId, idempotencyKey: idempotencyKey
            )
            guard isCurrent(generation) else { return }
            operationId = first.operationId
            apply(first, generation: generation)

            var current = first
            while !current.isTerminal {
                try await Task.sleep(nanoseconds: 500_000_000)
                try Task.checkCancellation()
                current = try await operationService.fetchAddLinkOperation(operationId: first.operationId)
                guard isCurrent(generation) else { return }
                apply(current, generation: generation)
            }

            guard isCurrent(generation) else { return }
            switch current.status {
            case "succeeded", "succeeded_with_warnings":
                await projectLocally(
                    status: current, syncService: syncService, container: container,
                    notebookId: notebookId, generation: generation
                )
            case "failed", "interrupted":
                finishBackendFailure(current, generation: generation)
            default:
                fail(generation: generation, message: L10n.string("建立失敗"))
            }
        } catch is CancellationError {
            guard self.generation == generation else { return }
            phase = .cancelled
            message = nil
        } catch {
            fail(generation: generation, message: Self.userMessage(for: error))
        }
    }

    private func projectLocally(
        status: KGAddLinkOperationStatus,
        syncService: any VocabularySyncServing,
        container: ModelContainer,
        notebookId: String,
        generation: Int
    ) async {
        guard isCurrent(generation) else { return }
        mutateStep("local_projection") { step in
            step.status = .running
            step.current = 0
            step.total = 0
            step.detail = L10n.string("同步中…")
        }

        do {
            let outcome = try await syncService.pullCardsToLocal(
                container: container,
                progress: { [weak self] detail, current, total in
                    Task { @MainActor [weak self] in
                        guard let self, self.isCurrent(generation) else { return }
                        self.mutateStep("local_projection") { step in
                            step.status = .running
                            step.current = current
                            step.total = total
                            if !detail.isEmpty { step.detail = detail }
                        }
                    }
                },
                notebookId: notebookId
            )
            guard isCurrent(generation) else { return }
            mutateStep("local_projection") { step in
                step.status = .done
                step.current = 1
                step.total = 1
                step.detail = outcome.hasChanges
                    ? L10n.format("同步 %@ 筆", String(outcome.changedEntryCount))
                    : L10n.string("已是最新")
            }
            phase = status.completedWithWarnings ? .succeededWithWarnings : .succeeded
            message = status.completedWithWarnings
                ? L10n.string("部分項目未成功同步，可直接再次重試。")
                : L10n.string("同步完成")
            recomputeFraction(forceTerminal: true)
        } catch is CancellationError {
            guard self.generation == generation else { return }
            phase = .cancelled
            message = nil
        } catch {
            guard isCurrent(generation) else { return }
            mutateStep("local_projection") { step in
                step.status = .error
                step.detail = L10n.string("同步失敗")
            }
            phase = .succeededWithWarnings
            message = L10n.string("部分項目未成功同步，可直接再次重試。")
            recomputeFraction(forceTerminal: true)
        }
    }

    private func apply(_ status: KGAddLinkOperationStatus, generation: Int) {
        guard isCurrent(generation), status.sequence >= lastSequence else { return }
        lastSequence = status.sequence
        operationId = status.operationId
        for remoteStep in status.steps where remoteStep.id != "local_projection" {
            mutateStep(remoteStep.id) { step in
                step.status = Self.stepStatus(for: remoteStep.status)
                step.current = max(0, remoteStep.current)
                step.total = max(0, remoteStep.total)
                step.detail = Self.detail(for: remoteStep)
            }
        }
        recomputeFraction()
    }

    private func finishBackendFailure(_ status: KGAddLinkOperationStatus, generation: Int) {
        guard isCurrent(generation) else { return }
        mutateStep("local_projection") { step in
            step.status = .skipped
            step.detail = L10n.string("已略過")
        }
        fail(generation: generation, message: Self.userMessage(for: status.errorCode))
        recomputeFraction(forceTerminal: true)
    }

    private func fail(generation: Int, message: String) {
        guard isCurrent(generation) else { return }
        phase = .failed
        self.message = message
    }

    private func mutateStep(_ id: String, _ mutation: (inout PipelineStep) -> Void) {
        guard let index = steps.firstIndex(where: { $0.id == id }) else { return }
        mutation(&steps[index])
        recomputeFraction()
    }

    private func recomputeFraction(forceTerminal: Bool = false) {
        let totalWeight = steps.reduce(0) { $0 + $1.weight }
        guard totalWeight > 0 else { return }
        let earned = steps.reduce(0.0) { partial, step in
            let completion: Double
            switch step.status {
            case .done, .skipped, .error: completion = 1
            case .waiting: completion = 0
            case .running, .retry:
                guard step.total > 0 else { return partial + step.weight * 0.15 }
                completion = max(0.15, min(1, Double(step.current) / Double(step.total)))
            }
            return partial + step.weight * completion
        }
        fraction = max(fraction, min(1, earned / totalWeight))
        if forceTerminal { fraction = 1 }
    }

    private static func initialSteps() -> [PipelineStep] {
        [
            PipelineStep(id: "resolve_target", label: L10n.string("找不到符合的單字"), weight: 1),
            PipelineStep(id: "translate", label: L10n.string("翻譯"), weight: 1),
            PipelineStep(id: "create_card", label: L10n.string("建立"), weight: 2),
            PipelineStep(id: "enrich", label: L10n.string("同步"), weight: 3),
            PipelineStep(id: "create_link", label: L10n.string("新增連結"), weight: 1),
            PipelineStep(id: "local_projection", label: L10n.string("下載單字卡"), weight: 2),
        ]
    }

    private static func source(for entry: VocabularyEntry) -> KGVocabSource? {
        let title = entry.bookTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty else { return nil }
        let chapter = entry.chapterTitle?.trimmingCharacters(in: .whitespacesAndNewlines)
        return .book(title: title, chapter: chapter?.isEmpty == false ? chapter : nil)
    }

    private static func stepStatus(for raw: String) -> PipelineStep.StepStatus {
        switch raw {
        case "running": return .running
        case "retry": return .retry
        case "done": return .done
        case "skipped": return .skipped
        case "warning", "error": return .error
        default: return .waiting
        }
    }

    private static func detail(for step: KGAddLinkOperationStep) -> String {
        switch step.detailCode {
        case "completed", "created": return L10n.string("已完成")
        case "existing_card": return L10n.string("已同步")
        case "provided": return L10n.string("已建立")
        case "retryable": return L10n.format("正在重試 (%@/%@)...", String(step.current), String(step.total))
        case "progress": return L10n.format("同步 %@ 筆", String(step.current))
        case "target_missing": return L10n.string("待同步")
        case "client_projection": return L10n.string("同步中…")
        default:
            switch step.status {
            case "error", "warning": return L10n.string("建立失敗")
            case "skipped": return L10n.string("已略過")
            default: return ""
            }
        }
    }

    private static func userMessage(for error: Error) -> String {
        if let kgError = error as? KGError {
            switch kgError {
            case .notAuthenticated, .unauthorized: return L10n.string("您的登入已過期，請重新登入")
            case .offline, .networkError: return L10n.string("請確認網路連線後重試")
            default: return L10n.string("addLink.error.linkFailed")
            }
        }
        return L10n.string("addLink.error.linkFailed")
    }

    private static func userMessage(for errorCode: String?) -> String {
        switch errorCode {
        case "quota_exhausted": return L10n.string("每日 AI 額度")
        case "translation_failed": return L10n.string("翻譯暫時失敗")
        case "enrichment_failed": return L10n.string("部分同步完成")
        default: return L10n.string("addLink.error.linkFailed")
        }
    }

    private func isCurrent(_ expectedGeneration: Int) -> Bool {
        generation == expectedGeneration && !Task.isCancelled
    }
}
