//
//  ReviewSettingsPauseTests.swift
//  Books & Vocab Tests
//
//  Pins ReviewSettings.pauseProgress / resumeProgress / reviewReferenceDate.
//  A regression in pause-clock state transitions causes the app to compute
//  different review due counts across devices or resume incorrectly.
//

import Foundation
import Testing
@testable import BooksAndVocab

struct ReviewSettingsPauseTests {

    // MARK: - reviewReferenceDate

    @Test func unpausedReturnsNow() {
        var settings = ReviewSettings.default
        settings.isProgressPaused = false
        settings.progressPausedAt = nil

        let anchor = Date(timeIntervalSince1970: 1000)
        let result = settings.reviewReferenceDate(now: anchor)

        #expect(result == anchor)
    }

    @Test func pausedReturnsPausedAt() {
        var settings = ReviewSettings.default
        let anchor = Date(timeIntervalSince1970: 500)
        settings.pauseProgress(at: anchor)

        let now = Date(timeIntervalSince1970: 1000)
        let result = settings.reviewReferenceDate(now: now)

        #expect(result == anchor)
    }

    @Test func pausedWithNilPausedAtFallsBackToNow() {
        var settings = ReviewSettings.default
        settings.isProgressPaused = true
        settings.progressPausedAt = nil

        let now = Date(timeIntervalSince1970: 1000)
        let result = settings.reviewReferenceDate(now: now)

        #expect(result == now)
    }

    // MARK: - pauseProgress

    @Test func pauseSetsPausedFlagAndAnchor() {
        var settings = ReviewSettings.default
        let anchor = Date(timeIntervalSince1970: 1234)

        settings.pauseProgress(at: anchor)

        #expect(settings.isProgressPaused == true)
        #expect(settings.progressPausedAt == anchor)
    }

    @Test func repeatedPauseDoesNotUpdateAnchor() {
        var settings = ReviewSettings.default
        let firstAnchor = Date(timeIntervalSince1970: 100)
        let secondAnchor = Date(timeIntervalSince1970: 200)

        settings.pauseProgress(at: firstAnchor)
        settings.pauseProgress(at: secondAnchor)

        #expect(settings.progressPausedAt == firstAnchor)
    }

    // MARK: - resumeProgress

    @Test func resumeClearsPausedFlagAndAnchor() {
        var settings = ReviewSettings.default
        settings.pauseProgress(at: Date())

        settings.resumeProgress()

        #expect(settings.isProgressPaused == false)
        #expect(settings.progressPausedAt == nil)
    }

    @Test func resumeOnAlreadyUnpausedIsNoOp() {
        var settings = ReviewSettings.default
        settings.isProgressPaused = false
        settings.progressPausedAt = nil

        settings.resumeProgress()

        #expect(settings.isProgressPaused == false)
        #expect(settings.progressPausedAt == nil)
    }

    // MARK: - pause → resume → pause sequence

    @Test func pauseResumePauseUsesNewAnchor() {
        var settings = ReviewSettings.default
        let first = Date(timeIntervalSince1970: 100)
        let second = Date(timeIntervalSince1970: 200)

        settings.pauseProgress(at: first)
        settings.resumeProgress()
        settings.pauseProgress(at: second)

        #expect(settings.isProgressPaused == true)
        #expect(settings.progressPausedAt == second)
    }
}
