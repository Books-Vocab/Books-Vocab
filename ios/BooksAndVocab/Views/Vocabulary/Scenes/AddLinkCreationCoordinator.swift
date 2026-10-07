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

/// Injectable time and identity sources for the creation flow.
///
/// Production uses `.live`; tests inject a recording sleeper (no real 500 ms
/// waits) and a deterministic key factory so idempotency-key policy is
/// observable.
struct AddLinkCreationEnvironment: Sendable {
    var pollIntervalNanoseconds: UInt64 = 500_000_000
    var sleep: @Sendable (UInt64) async throws -> Void = { try await Task.sleep(nanoseconds: $0) }
    var makeIdempotencyKey: @Sendable () -> String = { UUID().uuidString.lowercased() }

    static let live = AddLinkCreationEnvironment()
}

/// What a retry of a failed/interrupted creation must send.
///
/// The backend dedupes on `(user_id, idempotency_key)` and a failed operation
/// is terminal, so reusing a key after a terminal failure would only replay the
/// old failure. The key is reused only when the POST never got an answer
/// (network-layer resend); an operation whose polling merely lost transport is
/// resumed by id instead of being re-created.
enum AddLinkCreationRetryPlan: Equatable {
    /// POST again with a brand-new key (business retry after terminal failure).
    case fresh
    /// POST again with the same key (the first POST was never acknowledged).
    case resendWithSameKey(String)
    /// Keep polling the existing operation (it is not known to be terminal).
    case resumePolling(operationId: String)

    static func make(
        operationId: String?,
        operationTerminal: Bool,
        idempotencyKey: String
    ) -> AddLinkCreationRetryPlan {
        guard let operationId else { return .resendWithSameKey(idempotencyKey) }
        return operationTerminal ? .fresh : .resumePolling(operationId: operationId)
    }
}

/// Collaborators needed to (re)launch a creation outside the sheet that began it.
struct AddLinkCreationServices {
    let operationService: any AddLinkOperationServing
    let syncService: any VocabularySyncServing
    let container: ModelContainer
}

/// Everything a long-lived owner needs to retry or resume a job.
struct AddLinkCreationContext {
    let services: AddLinkCreationServices
    let sourceEntry: VocabularyEntry
}

/// Immutable snapshot of a coordinator's durable-relevant state.
struct AddLinkCreationJobState: Equatable {
    var jobKey: String
    var word: String
    var sourceCardID: String
    var notebookId: String
    var idempotencyKey: String
    var operationId: String?
    var operationTerminal: Bool
    var phase: AddLinkCreationPhase
    var message: String?
}

@MainActor
protocol AddLinkCreationObserving: AnyObject {
    /// Called when phase, operation identity, or message changes (not per
    /// progress tick; observers read `steps`/`fraction` from the coordinator).
    func creationDidChange(_ coordinator: AddLinkCreationCoordinator)
    /// True when another coordinator already runs this job; a second start would
    /// race the first one for the same card.
    func creationIsActive(jobKey: String, excluding coordinator: AddLinkCreationCoordinator) -> Bool
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
    private(set) var idempotencyKey: String = ""
    private(set) var operationTerminal = false
    private(set) var context: AddLinkCreationContext?
    private(set) var jobKey: String?
    private(set) var targetWord: String = ""

    @ObservationIgnored weak var observer: (any AddLinkCreationObserving)?
    private let environment: AddLinkCreationEnvironment
    private var generation = 0
    private var lastSequence = -1
    private var pollingTask: Task<Void, Never>?

    init(
        environment: AddLinkCreationEnvironment = .live,
        observer: (any AddLinkCreationObserving)? = nil
    ) {
        self.environment = environment
        self.observer = observer
    }

    var jobState: AddLinkCreationJobState? {
        guard let jobKey, let context, let sourceCardID = context.sourceEntry.kgCardId else { return nil }
        return AddLinkCreationJobState(
            jobKey: jobKey,
            word: targetWord,
            sourceCardID: sourceCardID,
            notebookId: context.sourceEntry.notebookId,
            idempotencyKey: idempotencyKey,
            operationId: operationId,
            operationTerminal: operationTerminal,
            phase: phase,
            message: message
        )
    }

    /// Stable identity of "this source card gains a link to this word".
    nonisolated static func jobKey(sourceCardID: String, word: String) -> String {
        "\(sourceCardID)|\(normalizeWord(word))"
    }

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

    nonisolated static func normalizeWord(_ word: String) -> String {
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
        // Capture the retry plan of the attempt being replaced before cancel()
        // can touch its state.
        let previousPlan = pendingRetryPlan(for: sourceEntry, word: word)
        cancel()
        let trimmedWord = word.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedWord.isEmpty else {
            block(message: L10n.string("找不到符合的單字"))
            return
        }

        switch Self.localTargetState(query: trimmedWord, sourceEntry: sourceEntry, allEntries: allEntries) {
        case .missing:
            break
        case .pending, .failed:
            block(message: L10n.string("此單字尚未同步，無法建立連結"))
            return
        case .archived:
            block(message: L10n.string("封存"))
            return
        case .active:
            block(message: L10n.string("已建立"))
            return
        case .source:
            block(message: L10n.string("新增連結失敗"))
            return
        }

        launch(
            word: trimmedWord,
            sourceEntry: sourceEntry,
            services: AddLinkCreationServices(
                operationService: operationService,
                syncService: syncService,
                container: container
            ),
            plan: previousPlan
        )
    }

    /// Relaunches a job outside the sheet that began it (retry from the card, or
    /// resume after an app kill). Skips the local-target guard: the caller
    /// already knows this word is a known job, and the server resolves an
    /// already-existing card idempotently.
    func relaunch(
        word: String,
        sourceEntry: VocabularyEntry,
        services: AddLinkCreationServices,
        plan: AddLinkCreationRetryPlan,
        idempotencyKey: String? = nil
    ) {
        cancel()
        launch(
            word: word.trimmingCharacters(in: .whitespacesAndNewlines),
            sourceEntry: sourceEntry,
            services: services,
            plan: plan,
            forcedKey: idempotencyKey
        )
    }

    func cancel() {
        generation += 1
        pollingTask?.cancel()
        pollingTask = nil
        if phase == .running {
            transition(.cancelled, message: nil)
        }
    }

    private func block(message: String) {
        transition(.blocked, message: message)
    }

    /// Plan for a retry of the attempt this coordinator last ran for the same
    /// job. Anything else (first attempt, different word, previous attempt
    /// succeeded) starts clean with a new key.
    private func pendingRetryPlan(for sourceEntry: VocabularyEntry, word: String) -> AddLinkCreationRetryPlan {
        guard phase == .failed,
              let sourceCardID = sourceEntry.kgCardId,
              jobKey == Self.jobKey(sourceCardID: sourceCardID, word: word)
        else { return .fresh }
        return AddLinkCreationRetryPlan.make(
            operationId: operationId,
            operationTerminal: operationTerminal,
            idempotencyKey: idempotencyKey
        )
    }

    private func launch(
        word: String,
        sourceEntry: VocabularyEntry,
        services: AddLinkCreationServices,
        plan: AddLinkCreationRetryPlan,
        forcedKey: String? = nil
    ) {
        guard let sourceCardID = sourceEntry.kgCardId, !sourceCardID.isEmpty else {
            block(message: L10n.string("此單字尚未同步，無法建立連結"))
            return
        }
        let key = Self.jobKey(sourceCardID: sourceCardID, word: word)
        if observer?.creationIsActive(jobKey: key, excluding: self) == true {
            block(message: L10n.string("addLink.creation.alreadyRunning"))
            return
        }

        generation += 1
        let currentGeneration = generation
        jobKey = key
        targetWord = word
        context = AddLinkCreationContext(services: services, sourceEntry: sourceEntry)
        lastSequence = -1
        steps = Self.initialSteps()
        fraction = 0
        operationTerminal = false

        let sendPlan: SendPlan
        switch plan {
        case .fresh:
            let fresh = environment.makeIdempotencyKey()
            idempotencyKey = fresh
            operationId = nil
            sendPlan = .post(key: fresh)
        case .resendWithSameKey(let sameKey):
            idempotencyKey = sameKey
            operationId = nil
            sendPlan = .post(key: sameKey)
        case .resumePolling(let existingOperationId):
            idempotencyKey = forcedKey ?? idempotencyKey
            operationId = existingOperationId
            sendPlan = .poll(operationId: existingOperationId)
        }
        transition(.running, message: nil)

        let request = KGAddLinkOperationRequest(
            fromId: sourceCardID,
            targetWord: word,
            translation: nil,
            context: sourceEntry.context,
            source: Self.source(for: sourceEntry),
            sourceLang: sourceEntry.sourceLang,
            targetLang: sourceEntry.targetLang
        )

        pollingTask = Task { @MainActor [weak self] in
            guard let self else { return }
            await self.run(
                request: request,
                notebookId: sourceEntry.notebookId,
                sendPlan: sendPlan,
                services: services,
                generation: currentGeneration
            )
            if self.generation == currentGeneration { self.pollingTask = nil }
        }
    }

    private enum SendPlan {
        case post(key: String)
        case poll(operationId: String)
    }

    private func run(
        request: KGAddLinkOperationRequest,
        notebookId: String,
        sendPlan: SendPlan,
        services: AddLinkCreationServices,
        generation: Int
    ) async {
        let operationService = services.operationService
        do {
            let first: KGAddLinkOperationStatus
            switch sendPlan {
            case .post(let key):
                first = try await operationService.startAddLinkOperation(
                    request: request, notebookId: notebookId, idempotencyKey: key
                )
            case .poll(let existingOperationId):
                first = try await operationService.fetchAddLinkOperation(operationId: existingOperationId)
            }
            guard isCurrent(generation) else { return }
            // The server acknowledged: from here on `operationId` identifies the
            // job, and the key must never be reused for a business retry.
            operationId = first.operationId
            publish()
            apply(first, generation: generation)

            var current = first
            while !current.isTerminal {
                try await environment.sleep(environment.pollIntervalNanoseconds)
                try Task.checkCancellation()
                current = try await operationService.fetchAddLinkOperation(operationId: first.operationId)
                guard isCurrent(generation) else { return }
                apply(current, generation: generation)
            }

            guard isCurrent(generation) else { return }
            switch current.status {
            case "succeeded", "succeeded_with_warnings":
                await projectLocally(
                    status: current, syncService: services.syncService, container: services.container,
                    notebookId: notebookId, generation: generation
                )
            case "failed", "interrupted":
                operationTerminal = true
                finishBackendFailure(current, generation: generation)
            default:
                operationTerminal = true
                fail(generation: generation, message: L10n.string("建立失敗"))
            }
        } catch is CancellationError {
            guard self.generation == generation else { return }
            transition(.cancelled, message: nil)
        } catch {
            fail(generation: generation, message: Self.userMessage(for: error))
        }
    }

    /// Single place that moves the phase, so observers (the durable hub) never
    /// miss a transition.
    private func transition(_ newPhase: AddLinkCreationPhase, message newMessage: String?) {
        phase = newPhase
        message = newMessage
        publish()
    }

    private func publish() {
        observer?.creationDidChange(self)
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
            recomputeFraction(forceTerminal: true)
            transition(
                status.completedWithWarnings ? .succeededWithWarnings : .succeeded,
                message: status.completedWithWarnings
                    ? L10n.string("部分項目未成功同步，可直接再次重試。")
                    : L10n.string("同步完成")
            )
        } catch is CancellationError {
            guard self.generation == generation else { return }
            transition(.cancelled, message: nil)
        } catch {
            guard isCurrent(generation) else { return }
            mutateStep("local_projection") { step in
                step.status = .error
                step.detail = L10n.string("同步失敗")
            }
            recomputeFraction(forceTerminal: true)
            transition(.succeededWithWarnings, message: L10n.string("部分項目未成功同步，可直接再次重試。"))
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
        transition(.failed, message: message)
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
            PipelineStep(id: AddLinkStep.resolveTarget.rawValue, label: AddLinkStep.resolveTarget.label, weight: 1),
            PipelineStep(id: AddLinkStep.translate.rawValue, label: AddLinkStep.translate.label, weight: 1),
            PipelineStep(id: AddLinkStep.createCard.rawValue, label: AddLinkStep.createCard.label, weight: 2),
            PipelineStep(id: AddLinkStep.enrich.rawValue, label: AddLinkStep.enrich.label, weight: 3),
            PipelineStep(id: AddLinkStep.createLink.rawValue, label: AddLinkStep.createLink.label, weight: 1),
            PipelineStep(id: AddLinkStep.localProjection.rawValue, label: AddLinkStep.localProjection.label, weight: 2),
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
