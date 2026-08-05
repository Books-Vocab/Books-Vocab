//
//  PullSerializationTests.swift
//  Books & Vocab Tests
//
//  Pins the two properties that keep `pullCardsToLocal` from producing the
//  "Network error: 已取消" banner and the duplicate-cursor requests seen in
//  production logs:
//
//   1. Pulls run one at a time. Five call sites reach this pull and only
//      `backgroundSync` used to guard; the logs showed two `GET /api/vocab`
//      seconds apart carrying an *identical* `?since=` cursor, because the
//      second read the incremental boundary before the first wrote it back.
//   2. The work is immune to the caller's cancellation. It used to run inside
//      the `.task`/`.refreshable` Task, so a view re-render cancelled the
//      in-flight URLSession request and `-999` was reported as a network fault.
//
//  These exercise `enqueuePull` / `finishPull` directly rather than through
//  `performPullCardsToLocal`, so no network or ModelContainer is involved.
//

#if os(iOS)
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@MainActor
struct PullSerializationTests {

    /// No network is reachable from these tests: the pull bodies are supplied by
    /// the test itself, so the service is only here to own the queue state.
    private func makeService() -> KGService {
        KGService(authSession: NilTokenSession(), sessionInvalidator: NoopInvalidator())
    }

    /// Two pulls enqueued back to back must not overlap: the second body may not
    /// begin until the first has finished. This is the property that stops two
    /// requests from carrying the same `?since=` cursor.
    @Test func secondPull_waitsForTheFirstToFinish() async throws {
        let service = makeService()
        let tracker = OverlapTracker()

        let first = service.enqueuePull { predecessor, id in
            Task {
                defer { service.finishPull(id: id) }
                _ = await predecessor?.result
                await tracker.enter()
                try? await Task.sleep(for: .milliseconds(120))
                await tracker.leave()
                return KGPullOutcome(pipelinePending: false, inserted: 1)
            }
        }
        let second = service.enqueuePull { predecessor, id in
            Task {
                defer { service.finishPull(id: id) }
                _ = await predecessor?.result
                await tracker.enter()
                await tracker.leave()
                return KGPullOutcome(pipelinePending: false, inserted: 2)
            }
        }

        let firstOutcome = try await first.value
        let secondOutcome = try await second.value

        #expect(firstOutcome.inserted == 1)
        #expect(secondOutcome.inserted == 2)
        #expect(await tracker.maxConcurrent == 1, "pulls overlapped — serialization broken")
        #expect(await tracker.completed == 2)
    }

    /// Every caller gets its own run. Coalescing onto one shared response would
    /// hand the sync sheet a payload fetched *before* its upload, whose
    /// `X-Pipeline-Pending` would then wrongly say "nothing pending".
    @Test func eachCaller_getsItsOwnRun() async throws {
        let service = makeService()
        let counter = RunCounter()

        var tasks: [Task<KGPullOutcome, Error>] = []
        for _ in 0..<4 {
            tasks.append(service.enqueuePull { predecessor, id in
                Task {
                    defer { service.finishPull(id: id) }
                    _ = await predecessor?.result
                    await counter.increment()
                    return .unchanged
                }
            })
        }
        for task in tasks { _ = try await task.value }

        #expect(await counter.count == 4)
    }

    /// A failing pull must not poison the queue behind it: the next caller still
    /// runs, and still gets its own result.
    @Test func failedPull_doesNotFailItsSuccessor() async throws {
        let service = makeService()

        struct Boom: Error {}
        let failing = service.enqueuePull { predecessor, id in
            Task {
                defer { service.finishPull(id: id) }
                _ = await predecessor?.result
                throw Boom()
            }
        }
        let following = service.enqueuePull { predecessor, id in
            Task {
                defer { service.finishPull(id: id) }
                _ = await predecessor?.result
                return KGPullOutcome(pipelinePending: false, updated: 7)
            }
        }

        await #expect(throws: Boom.self) { try await failing.value }
        let outcome = try await following.value
        #expect(outcome.updated == 7)
    }

    /// The core of the「網路錯誤：已取消」fix: cancelling the *caller* must not
    /// cancel the pull. An unstructured `Task` does not inherit cancellation, so
    /// the sync finishes and its data lands even though the waiter gave up.
    @Test func cancellingTheCaller_doesNotCancelThePull() async throws {
        let service = makeService()
        let completion = CompletionFlag()

        let pull = service.enqueuePull { predecessor, id in
            Task {
                defer { service.finishPull(id: id) }
                _ = await predecessor?.result
                try? await Task.sleep(for: .milliseconds(150))
                await completion.record(cancelled: Task.isCancelled)
                return .unchanged
            }
        }

        // A caller that awaits the pull and is then cancelled mid-wait.
        let waiter = Task { _ = try? await pull.value }
        try await Task.sleep(for: .milliseconds(20))
        waiter.cancel()
        _ = await waiter.value

        _ = try await pull.value
        #expect(await completion.finished, "pull did not run to completion")
        #expect(await completion.sawCancellation == false, "pull inherited the caller's cancellation")
    }
}

// MARK: - Service stubs

private final class NilTokenSession: AuthSessionProviding {
    var isLoggedIn: Bool { true }
    var token: String? { nil }
}

private final class NoopInvalidator: SessionInvalidating {
    func logout(modelContainer: ModelContainer?, reason: String) {}
    func waitForPendingLocalDataCleanup() async {}
}

// MARK: - Probes

/// Records whether two pull bodies were ever inside their critical section at
/// the same time.
private actor OverlapTracker {
    private var current = 0
    private(set) var maxConcurrent = 0
    private(set) var completed = 0

    func enter() {
        current += 1
        maxConcurrent = max(maxConcurrent, current)
    }

    func leave() {
        current -= 1
        completed += 1
    }
}

private actor RunCounter {
    private(set) var count = 0
    func increment() { count += 1 }
}

private actor CompletionFlag {
    private(set) var finished = false
    private(set) var sawCancellation = true

    func record(cancelled: Bool) {
        finished = true
        sawCancellation = cancelled
    }
}
#endif
