import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

struct NotebookSettingsSyncTests {
    @Test func remoteGroupsApplyIndependentlyAndResetKeepsTimestamp() {
        let projection = NotebookSettingsProjection(notebookId: "nb-1")
        let policy = ReviewPolicy.default
        let layout = ReviewCardLayoutProfile(recognition: .compact, production: .standard)
        projection.applyRemote(KGNotebookSettings(
            reviewPolicy: KGNotebookSettingsGroup(
                value: KGNotebookReviewPolicy(policy), updatedAt: 10
            ),
            cardLayout: KGNotebookSettingsGroup(
                value: KGNotebookCardLayout(layout), updatedAt: 10
            )
        ))
        #expect(projection.reviewPolicyOverride == policy)
        #expect(projection.cardLayoutOverride == layout)

        projection.applyRemote(KGNotebookSettings(
            reviewPolicy: KGNotebookSettingsGroup<KGNotebookReviewPolicy>(
                value: nil, updatedAt: 11
            ),
            cardLayout: KGNotebookSettingsGroup(
                value: KGNotebookCardLayout(layout), updatedAt: 10
            )
        ))
        #expect(projection.reviewPolicyOverride == nil)
        #expect(projection.reviewPolicyUpdatedAt == 11)
        #expect(projection.cardLayoutOverride == layout)
    }

    @Test func staleRemoteGroupCannotResurrectClearedPolicy() {
        let projection = NotebookSettingsProjection(notebookId: "nb-1")
        projection.applyRemote(KGNotebookSettings(
            reviewPolicy: KGNotebookSettingsGroup(
                value: nil, updatedAt: 20
            ),
            cardLayout: KGNotebookSettingsGroup<KGNotebookCardLayout>(
                value: nil, updatedAt: nil
            )
        ))
        projection.applyRemote(KGNotebookSettings(
            reviewPolicy: KGNotebookSettingsGroup(
                value: KGNotebookReviewPolicy(.default), updatedAt: 19
            ),
            cardLayout: KGNotebookSettingsGroup<KGNotebookCardLayout>(
                value: nil, updatedAt: nil
            )
        ))
        #expect(projection.reviewPolicyOverride == nil)
        #expect(projection.reviewPolicyUpdatedAt == 20)
    }

    private func remoteSettings(
        policyAt: Double?, layoutAt: Double? = nil
    ) -> KGNotebookSettings {
        KGNotebookSettings(
            reviewPolicy: KGNotebookSettingsGroup(
                value: policyAt == nil ? nil : KGNotebookReviewPolicy(.default), updatedAt: policyAt
            ),
            cardLayout: KGNotebookSettingsGroup<KGNotebookCardLayout>(value: nil, updatedAt: layoutAt)
        )
    }

    @Test(arguments: [NotebookSettingsSyncState.failed, .pending])
    func staleRemoteKeepsDirtyStateAndLocalValue(state: NotebookSettingsSyncState) {
        let projection = NotebookSettingsProjection(notebookId: "nb-1")
        var local = ReviewPolicy.default
        local.mode = .custom
        projection.applyLocalReviewPolicy(local, updatedAt: 50)
        projection.syncState = state
        projection.syncError = "offline"

        projection.applyRemote(remoteSettings(policyAt: 40))

        #expect(projection.syncState == state)
        #expect(projection.syncError == "offline")
        #expect(projection.reviewPolicyOverride == local)
        #expect(projection.reviewPolicyUpdatedAt == 50)
    }

    @Test func remoteWithoutLocalGroupTimestampKeepsDirtyLocalGroup() {
        let projection = NotebookSettingsProjection(notebookId: "nb-1")
        projection.applyLocalCardLayout(
            ReviewCardLayoutProfile(recognition: .compact, production: .standard), updatedAt: 30
        )
        projection.syncState = .failed
        projection.syncError = "boom"

        projection.applyRemote(remoteSettings(policyAt: 10, layoutAt: nil))

        #expect(projection.syncState == .failed)
        #expect(projection.syncError == "boom")
        #expect(projection.cardLayoutUpdatedAt == 30)
    }

    @Test func freshRemoteSyncsDirtyProjectionAndClearsError() {
        let projection = NotebookSettingsProjection(notebookId: "nb-1")
        projection.applyLocalReviewPolicy(.default, updatedAt: 50)
        projection.syncState = .failed
        projection.syncError = "offline"

        projection.applyRemote(remoteSettings(policyAt: 50))

        #expect(projection.syncState == .synced)
        #expect(projection.syncError == nil)
    }

    @Test func remoteOnCleanProjectionSetsSynced() {
        let projection = NotebookSettingsProjection(notebookId: "nb-1")
        projection.applyRemote(remoteSettings(policyAt: nil))
        #expect(projection.syncState == .synced)
        #expect(projection.syncError == nil)
    }

    @Test func notebookWireDecodeKeepsSettingsAndSupportsLegacyResponse() throws {
        let settings = KGNotebookSettings(
            reviewPolicy: KGNotebookSettingsGroup(
                value: KGNotebookReviewPolicy(.default), updatedAt: 10
            ),
            cardLayout: KGNotebookSettingsGroup<KGNotebookCardLayout>(
                value: nil, updatedAt: nil
            )
        )
        let current = KGNotebook(
            id: "nb-1",
            name: "本",
            color: nil,
            coverPattern: nil,
            sortOrder: 0,
            isDefault: false,
            isDeleted: false,
            cardCount: 0,
            updatedAt: nil,
            sourceSharedDeckId: nil,
            sourceVersion: nil,
            settings: settings
        )
        let decoded = try JSONDecoder().decode(
            KGNotebook.self,
            from: JSONEncoder().encode(current)
        )
        #expect(decoded.settings?.reviewPolicy.value?.reviewPolicy == .default)

        let legacy = try JSONDecoder().decode(
            KGNotebook.self,
            from: Data(#"{"id":"legacy","name":"舊本"}"#.utf8)
        )
        #expect(legacy.settings == nil)
    }
}


// MARK: - Drain + per-group save

@MainActor
private final class StubNotebookService: NotebookServing {
    typealias PolicyGroup = KGNotebookSettingsPatchGroup<KGNotebookReviewPolicy>
    typealias LayoutGroup = KGNotebookSettingsPatchGroup<KGNotebookCardLayout>

    struct Call {
        let id: String
        let policy: PolicyGroup?
        let layout: LayoutGroup?
    }

    private(set) var calls: [Call] = []
    var handler: (Call) async throws -> KGNotebook = { _ in throw URLError(.notConnectedToInternet) }

    func fetchNotebooks() async throws -> [KGNotebook] { [] }
    func createNotebook(name: String, color: String?, coverPattern: String?) async throws -> KGNotebook {
        throw URLError(.unsupportedURL)
    }
    func updateNotebook(id: String, name: String?, color: String?, coverPattern: String?) async throws -> KGNotebook {
        throw URLError(.unsupportedURL)
    }
    func deleteNotebook(id: String) async throws {}

    func updateNotebookSettings(
        id: String, reviewPolicy: PolicyGroup?, cardLayout: LayoutGroup?
    ) async throws -> KGNotebook {
        let call = Call(id: id, policy: reviewPolicy, layout: cardLayout)
        calls.append(call)
        return try await handler(call)
    }
}

private struct SyncStubError: LocalizedError {
    var errorDescription: String? { "boom" }
}

private func notebook(settings: KGNotebookSettings?) -> KGNotebook {
    KGNotebook(
        id: "nb-1", name: "本", color: nil, coverPattern: nil, sortOrder: 0,
        isDefault: false, isDeleted: false, cardCount: 0, updatedAt: nil,
        sourceSharedDeckId: nil, sourceVersion: nil, settings: settings
    )
}

private func settings(policyAt: Double?, layoutAt: Double?) -> KGNotebookSettings {
    KGNotebookSettings(
        reviewPolicy: KGNotebookSettingsGroup(
            value: policyAt == nil ? nil : KGNotebookReviewPolicy(.default), updatedAt: policyAt
        ),
        cardLayout: KGNotebookSettingsGroup(
            value: layoutAt == nil ? nil : KGNotebookCardLayout(.default), updatedAt: layoutAt
        )
    )
}

@MainActor
struct NotebookSettingsDrainTests {
    private func makeContext() throws -> ModelContext {
        let container = try ModelContainer(
            for: Schema([NotebookSettingsProjection.self]),
            configurations: [ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)]
        )
        return ModelContext(container)
    }

    private func dirtyProjection(
        _ ctx: ModelContext, state: NotebookSettingsSyncState = .failed
    ) -> NotebookSettingsProjection {
        let projection = NotebookSettingsProjection(notebookId: "nb-1")
        projection.applyLocalReviewPolicy(.default, updatedAt: 50)
        projection.syncState = state
        projection.syncError = state == .failed ? "offline" : nil
        ctx.insert(projection)
        return projection
    }

    @Test(arguments: [NotebookSettingsSyncState.failed, .pending])
    func drainSuccessMovesDirtyProjectionToSynced(state: NotebookSettingsSyncState) async throws {
        let ctx = try makeContext()
        let projection = dirtyProjection(ctx, state: state)
        let service = StubNotebookService()
        service.handler = { _ in notebook(settings: settings(policyAt: 50, layoutAt: nil)) }

        await NotebookSettingsDrain.drain(modelContext: ctx, service: service)

        #expect(service.calls.count == 1)
        #expect(service.calls.first?.policy?.updatedAt == 50)
        #expect(service.calls.first?.policy?.value == KGNotebookReviewPolicy(.default))
        #expect(service.calls.first?.layout == nil)
        #expect(projection.syncState == .synced)
        #expect(projection.syncError == nil)
    }

    @Test func drainFailureLeavesFailedWithError() async throws {
        let ctx = try makeContext()
        let projection = dirtyProjection(ctx, state: .pending)
        let service = StubNotebookService()
        service.handler = { _ in throw SyncStubError() }

        await NotebookSettingsDrain.drain(modelContext: ctx, service: service)

        #expect(projection.syncState == .failed)
        #expect(projection.syncError == "boom")
        #expect(projection.reviewPolicyUpdatedAt == 50)
    }

    @Test func drainSkipsSyncedProjections() async throws {
        let ctx = try makeContext()
        let clean = NotebookSettingsProjection(notebookId: "nb-clean")
        ctx.insert(clean)
        let service = StubNotebookService()

        await NotebookSettingsDrain.drain(modelContext: ctx, service: service)

        #expect(service.calls.isEmpty)
        #expect(clean.syncState == .synced)
    }

    @Test func drainKeepsProjectionDirtyWhenServerStillBehind() async throws {
        let ctx = try makeContext()
        let projection = dirtyProjection(ctx)
        let service = StubNotebookService()
        service.handler = { _ in notebook(settings: settings(policyAt: 40, layoutAt: nil)) }

        await NotebookSettingsDrain.drain(modelContext: ctx, service: service)

        #expect(projection.syncState == .failed)
        #expect(projection.reviewPolicyUpdatedAt == 50)
    }

    @Test func overlappingGroupSavesKeepIndependentGenerations() async throws {
        let ctx = try makeContext()
        let projection = NotebookSettingsProjection(notebookId: "nb-1")
        ctx.insert(projection)
        projection.applyLocalReviewPolicy(.default, updatedAt: 10)
        projection.applyLocalCardLayout(.default, updatedAt: 20)

        let service = StubNotebookService()
        var policyGate: CheckedContinuation<Void, Never>?
        service.handler = { call in
            if call.policy != nil {
                await withCheckedContinuation { policyGate = $0 }
                throw SyncStubError()
            }
            return notebook(settings: settings(policyAt: nil, layoutAt: 20))
        }
        let saver = NotebookSettingsSaver()

        let policyTask = Task { @MainActor in
            await saver.saveReviewPolicy(
                projection: projection, policy: .default, updatedAt: 10, service: service
            )
        }
        while policyGate == nil { await Task.yield() }

        let layoutOutcome = await saver.saveCardLayout(
            projection: projection, profile: .default, updatedAt: 20, service: service
        )
        policyGate?.resume()
        let policyOutcome = await policyTask.value

        guard case .applied = layoutOutcome else {
            Issue.record("layout save result was discarded: \(layoutOutcome)")
            return
        }
        guard case let .failed(error) = policyOutcome else {
            Issue.record("policy failure was swallowed by the layout save: \(policyOutcome)")
            return
        }
        #expect(error.localizedDescription == "boom")
        #expect(projection.syncState == .failed)
        #expect(projection.syncError == "boom")
    }

    @Test func newerSaveOfSameGroupSupersedesOlderInFlightOne() async throws {
        let ctx = try makeContext()
        let projection = NotebookSettingsProjection(notebookId: "nb-1")
        ctx.insert(projection)
        projection.applyLocalReviewPolicy(.default, updatedAt: 10)

        let service = StubNotebookService()
        var gate: CheckedContinuation<Void, Never>?
        var first = true
        service.handler = { _ in
            if first {
                first = false
                await withCheckedContinuation { gate = $0 }
            }
            return notebook(settings: settings(policyAt: 11, layoutAt: nil))
        }
        let saver = NotebookSettingsSaver()
        let older = Task { @MainActor in
            await saver.saveReviewPolicy(projection: projection, policy: .default, updatedAt: 10, service: service)
        }
        while gate == nil { await Task.yield() }
        let newer = await saver.saveReviewPolicy(
            projection: projection, policy: .default, updatedAt: 11, service: service
        )
        gate?.resume()
        let olderOutcome = await older.value

        guard case .applied = newer else { Issue.record("newer save should apply"); return }
        guard case .superseded = olderOutcome else { Issue.record("older save should be superseded"); return }
    }
}
