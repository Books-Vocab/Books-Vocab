//
//  AutoplaySpeedTests.swift
//  Books & Vocab Tests
//
//  Pins AutoplaySpeed.revealDelay / stayDelay / next.
//  A regression here changes card dwell times in review autoplay,
//  directly affecting perceived UX (too fast → can’t read; too slow → boring).
//

import Foundation
import Testing
@testable import BooksAndVocab

struct AutoplaySpeedTests {

    // MARK: - revealDelay (time before flip)

    @Test func slowRevealDelayIsFourSeconds() {
        #expect(AutoplaySpeed.slow.revealDelay == .seconds(4))
    }

    @Test func normalRevealDelayIsTwoSeconds() {
        #expect(AutoplaySpeed.normal.revealDelay == .seconds(2))
    }

    @Test func fastRevealDelayIsOneSecond() {
        #expect(AutoplaySpeed.fast.revealDelay == .seconds(1))
    }

    // MARK: - stayDelay (time on back before next card)

    @Test func slowStayDelayIsEightSeconds() {
        #expect(AutoplaySpeed.slow.stayDelay == .seconds(8))
    }

    @Test func normalStayDelayIsFourSeconds() {
        #expect(AutoplaySpeed.normal.stayDelay == .seconds(4))
    }

    @Test func fastStayDelayIsTwoSeconds() {
        #expect(AutoplaySpeed.fast.stayDelay == .seconds(2))
    }

    // MARK: - next (cyclic state machine)

    @Test func slowCyclesToNormal() {
        #expect(AutoplaySpeed.slow.next == .normal)
    }

    @Test func normalCyclesToFast() {
        #expect(AutoplaySpeed.normal.next == .fast)
    }

    @Test func fastCyclesToSlow() {
        #expect(AutoplaySpeed.fast.next == .slow)
    }

    @Test func tripleNextReturnsToOriginal() {
        #expect(AutoplaySpeed.slow.next.next.next == .slow)
        #expect(AutoplaySpeed.normal.next.next.next == .normal)
        #expect(AutoplaySpeed.fast.next.next.next == .fast)
    }
}
