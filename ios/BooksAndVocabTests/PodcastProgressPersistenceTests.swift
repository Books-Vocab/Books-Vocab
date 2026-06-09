//
//  PodcastProgressPersistenceTests.swift
//  Books & Vocab Tests
//
//  Pins PodcastProgressPersistenceController.shouldPersist() — the gate that
//  suppresses position-0 writes during playback ticks while allowing explicit
//  user transitions (pause / episode switch) to persist. A false positive here
//  floods SwiftData with no-op writes; a false negative loses the user's
//  explicit reset-to-start intent.
//

import Testing
@testable import BooksAndVocab

struct PodcastProgressPersistenceTests {

    // MARK: - shouldPersist

    @Test func tickAtPositionZeroIsDropped() {
        #expect(
            PodcastProgressPersistenceController.shouldPersist(
                currentTime: 0, reason: .tick
            ) == false
        )
    }

    @Test func tickAtNonZeroPositionIsAllowed() {
        #expect(
            PodcastProgressPersistenceController.shouldPersist(
                currentTime: 1.0, reason: .tick
            ) == true
        )
    }

    @Test func pauseAtPositionZeroIsAllowed() {
        #expect(
            PodcastProgressPersistenceController.shouldPersist(
                currentTime: 0, reason: .pause
            ) == true
        )
    }

    @Test func episodeSwitchAtPositionZeroIsAllowed() {
        #expect(
            PodcastProgressPersistenceController.shouldPersist(
                currentTime: 0, reason: .episodeSwitch
            ) == true
        )
    }

    @Test func pauseAtNonZeroPositionIsAllowed() {
        #expect(
            PodcastProgressPersistenceController.shouldPersist(
                currentTime: 42.5, reason: .pause
            ) == true
        )
    }

    @Test func fractionalZeroIsStillZero() {
        // 0.0 with any non-tick reason should persist.
        #expect(
            PodcastProgressPersistenceController.shouldPersist(
                currentTime: 0.0, reason: .pause
            ) == true
        )
    }
}
