//
//  ReaderProgressSaverTests.swift
//  Books & Vocab Tests
//
//  Spec for Track 20: EPUB reader last-read locator persistence fix.
//
//  Root cause: ReaderView.handleLocationChange mutated Book.lastReadLocatorJSON
//  every page-turn but never called modelContext.save() (unlike PDFReaderView's
//  explicit safeSave()), so the last position could be lost on crash/OOM before
//  SwiftData's non-deterministic autosave flushed.
//
//  NOTE: This target cannot run locally in this environment (CLAUDE.md Scope
//  forbids ios_test.sh here). Cases are the executable spec for the debounce /
//  flush / encode-skip behaviour, validated by CI / reviewer.
//

import Foundation
import Testing
import ReadiumShared
@testable import BooksAndVocab

@MainActor
struct ReaderProgressSaverTests {

    /// Consecutive page-turns inside the debounce window collapse to a single
    /// save — no per-page synchronous I/O.
    @Test func consecutivePageTurnsCoalesceToSingleSave() async throws {
        let saves = Counter()
        let sut = ReaderProgressSaver(flushDelay: 0.05)

        var applied = 0
        for _ in 0..<10 {
            sut.recordChange(apply: { applied += 1 }, save: { saves.increment() })
        }

        // apply runs synchronously every page (in-memory model stays fresh)...
        #expect(applied == 10)
        // ...but no save has flushed yet within the window.
        #expect(saves.value == 0)

        try await Task.sleep(nanoseconds: 200_000_000)
        // Exactly one coalesced save fires at the window tail.
        #expect(saves.value == 1)
    }

    /// flush() persists immediately and cancels the pending debounced save,
    /// so it never double-fires — covers onDisappear / scenePhase .background.
    @Test func flushSavesImmediatelyAndCancelsPending() async throws {
        let saves = Counter()
        let sut = ReaderProgressSaver(flushDelay: 0.5)

        sut.recordChange(apply: {}, save: { saves.increment() })
        #expect(saves.value == 0)   // still pending

        sut.flush()
        #expect(saves.value == 1)   // immediate

        // The previously-scheduled debounced save must have been cancelled.
        try await Task.sleep(nanoseconds: 700_000_000)
        #expect(saves.value == 1)
    }

    /// flush() with nothing pending is a no-op (no spurious save).
    @Test func flushWithoutPendingIsNoOp() {
        let saves = Counter()
        let sut = ReaderProgressSaver(flushDelay: 0.5)
        sut.flush()
        #expect(saves.value == 0)
    }

    /// A record() arriving after a flush() schedules a fresh debounce window.
    @Test func recordAfterFlushSchedulesNewWindow() async throws {
        let saves = Counter()
        let sut = ReaderProgressSaver(flushDelay: 0.05)

        sut.recordChange(apply: {}, save: { saves.increment() })
        sut.flush()                 // save #1
        #expect(saves.value == 1)

        sut.recordChange(apply: {}, save: { saves.increment() })
        try await Task.sleep(nanoseconds: 200_000_000)
        #expect(saves.value == 2)   // debounced save #2
    }

    /// A valid locator round-trips to a non-nil JSON the restore path can decode
    /// (no "{}" pollution on the happy path). Built via the same `jsonString`
    /// decode seam the restore path uses (ReaderView+Panels.initialLocator).
    @Test func encodedLocatorJSONReturnsJSONForValidLocator() throws {
        let sourceJSON = """
        {"href":"chapter1.html","type":"text/html","locations":{"totalProgression":0.42}}
        """
        let locator = try #require(try? Locator(jsonString: sourceJSON))

        let json = try #require(ReaderProgressSaver.encodedLocatorJSON(locator))
        // Must round-trip back into a Locator carrying the same progression.
        let restored = try #require(try? Locator(jsonString: json))
        #expect(restored.locations.totalProgression == 0.42)
    }
}

/// Minimal thread-safe counter for observing save invocations.
private final class Counter: @unchecked Sendable {
    private let lock = NSLock()
    private var _value = 0
    var value: Int { lock.lock(); defer { lock.unlock() }; return _value }
    func increment() { lock.lock(); _value += 1; lock.unlock() }
}
