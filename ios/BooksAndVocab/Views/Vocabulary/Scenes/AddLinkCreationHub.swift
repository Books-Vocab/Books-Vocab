import Foundation
import Observation
import SwiftData

/// Long-lived owner of missing-target Add Link jobs.
///
/// The sheet only *starts* a creation; the hub keeps the coordinator alive after
/// the sheet closes, mirrors every job into a durable record (so an app kill
/// can be resumed) and into `PendingLinkProjection` (so the source card shows a
/// "creating" link immediately). A job leaves the hub only when it succeeds,
/// the user dismisses a failure, or its source card no longer exists.
@Observable @MainActor
final class AddLinkCreationHub: AddLinkCreationObserving {
    static let shared = AddLinkCreationHub()

    struct Job {
        var record: PendingLinkCreationRecord
        /// Nil for jobs restored from disk that have not been relaunched yet.
        var coordinator: AddLinkCreationCoordinator?
        var context: AddLinkCreationContext?
    }

    private(set) var jobs: [String: Job] = [:]
    /// Bumps whenever a job appears, changes visible state, or disappears.
    private(set) var revision = 0

    @ObservationIgnored private var dirtySourceCardIDs: Set<String> = []
    @ObservationIgnored private let store: any PendingLinkCreationStoring
    @ObservationIgnored private let projection: PendingLinkProjection
    @ObservationIgnored private let environment: AddLinkCreationEnvironment

    init(
        store: any PendingLinkCreationStoring = PendingLinkCreationStores.makeDefault(),
        projection: PendingLinkProjection = .shared,
        environment: AddLinkCreationEnvironment = .live
    ) {
        self.store = store
        self.projection = projection
        self.environment = environment
        for record in store.load() {
            jobs[record.jobKey] = Job(record: record, coordinator: nil, context: nil)
        }
        publishProjection()
    }

    func makeCoordinator() -> AddLinkCreationCoordinator {
        AddLinkCreationCoordinator(environment: environment, observer: self)
    }

    func job(forJobKey jobKey: String) -> Job? { jobs[jobKey] }

    /// Source card ids whose cached card must be rebuilt because their pending
    /// links changed. Consumed by the review screen that owns the card cache.
    func takeDirtySourceCardIDs() -> Set<String> {
        defer { dirtySourceCardIDs.removeAll() }
        return dirtySourceCardIDs
    }

    // MARK: - AddLinkCreationObserving

    func creationDidChange(_ coordinator: AddLinkCreationCoordinator) {
        guard let state = coordinator.jobState else { return }
        switch state.phase {
        case .running:
            upsert(from: state, coordinator: coordinator, recordState: .creating)
        case .failed:
            upsert(from: state, coordinator: coordinator, recordState: .failed)
        case .succeeded, .succeededWithWarnings:
            guard owns(coordinator, jobKey: state.jobKey) else { return }
            remove(jobKey: state.jobKey)
        case .cancelled:
            // A restart cancels first; only the coordinator that owns the job may
            // retire it, otherwise a stale sheet could erase a live retry.
            guard owns(coordinator, jobKey: state.jobKey) else { return }
            remove(jobKey: state.jobKey)
        case .blocked, .idle:
            break
        }
    }

    func creationIsActive(jobKey: String, excluding coordinator: AddLinkCreationCoordinator) -> Bool {
        guard let live = jobs[jobKey]?.coordinator else { return false }
        return live !== coordinator && live.phase == .running
    }

    // MARK: - User actions on a pending item

    /// Retries a failed job with the key policy of `AddLinkCreationRetryPlan`.
    @discardableResult
    func retry(jobKey: String) -> Bool {
        guard let job = jobs[jobKey], job.record.state == .failed,
              let context = job.context else { return false }
        let coordinator = makeCoordinator()
        let plan = job.record.retryPlan
        coordinator.relaunch(
            word: job.record.word,
            sourceEntry: context.sourceEntry,
            services: context.services,
            plan: plan,
            idempotencyKey: job.record.idempotencyKey
        )
        return true
    }

    /// The user gives up on a failed job; it must never disappear on its own.
    func dismiss(jobKey: String) {
        guard let job = jobs[jobKey], job.record.state == .failed else { return }
        remove(jobKey: jobKey)
    }

    // MARK: - Resume after relaunch

    /// Re-attaches every durable job that has no live coordinator. A job that
    /// was still creating is relaunched (resume polling by operation id, or
    /// resend with the same key when the POST never answered); a failed one only
    /// regains the context its retry button needs. Jobs whose source card is
    /// gone (account switch, deletion) are dropped.
    func resume(services: AddLinkCreationServices) {
        let context = services.container.mainContext
        for (jobKey, job) in jobs where job.coordinator == nil {
            guard let source = Self.sourceEntry(cardID: job.record.sourceCardID, in: context) else {
                remove(jobKey: jobKey)
                continue
            }
            let restored = AddLinkCreationContext(services: services, sourceEntry: source)
            jobs[jobKey]?.context = restored
            guard job.record.state == .creating else { continue }
            let coordinator = makeCoordinator()
            coordinator.relaunch(
                word: job.record.word,
                sourceEntry: source,
                services: services,
                plan: job.record.retryPlan,
                idempotencyKey: job.record.idempotencyKey
            )
        }
    }

    // MARK: - Internals

    private func owns(_ coordinator: AddLinkCreationCoordinator, jobKey: String) -> Bool {
        guard let live = jobs[jobKey]?.coordinator else { return false }
        return live === coordinator
    }

    private func upsert(
        from state: AddLinkCreationJobState,
        coordinator: AddLinkCreationCoordinator,
        recordState: PendingLinkCreationRecord.State
    ) {
        let existing = jobs[state.jobKey]
        let record = PendingLinkCreationRecord(
            jobKey: state.jobKey,
            word: state.word,
            sourceCardID: state.sourceCardID,
            notebookId: state.notebookId,
            idempotencyKey: state.idempotencyKey,
            operationId: state.operationId,
            operationTerminal: state.operationTerminal,
            state: recordState,
            message: recordState == .failed ? state.message : nil,
            createdAt: existing?.record.createdAt ?? Date()
        )
        let visibleChange = existing?.record.state != recordState
            || existing?.record.word != record.word
        let recordChanged = existing?.record != record

        jobs[state.jobKey] = Job(record: record, coordinator: coordinator, context: coordinator.context)
        if recordChanged { persist() }
        if visibleChange {
            publishProjection()
            markChanged(sourceCardID: state.sourceCardID)
        }
    }

    private func remove(jobKey: String) {
        guard let job = jobs.removeValue(forKey: jobKey) else { return }
        persist()
        publishProjection()
        markChanged(sourceCardID: job.record.sourceCardID)
    }

    private func markChanged(sourceCardID: String) {
        dirtySourceCardIDs.insert(sourceCardID)
        revision += 1
    }

    private func persist() {
        store.save(jobs.values.map(\.record).sorted { $0.createdAt < $1.createdAt })
    }

    private func publishProjection() {
        var links: [String: [KGCardLinkSummary]] = [:]
        for job in jobs.values.sorted(by: { $0.record.createdAt < $1.record.createdAt }) {
            let state: KGCardLinkSummary.CreationState = job.record.state == .failed ? .failed : .creating
            links[job.record.sourceCardID, default: []].append(
                .pendingCreation(jobKey: job.record.jobKey, word: job.record.word, state: state)
            )
        }
        projection.replaceAll(with: links)
    }

    private static func sourceEntry(cardID: String, in context: ModelContext) -> VocabularyEntry? {
        let target: String? = cardID
        var descriptor = FetchDescriptor<VocabularyEntry>(
            predicate: #Predicate { $0.kgCardId == target }
        )
        descriptor.fetchLimit = 1
        return try? context.fetch(descriptor).first
    }
}
