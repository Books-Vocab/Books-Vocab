//
//  ReviewSettingsEffectiveParamsTests.swift
//  Books & Vocab Tests
//
//  Pins ReviewSettings effective* computed properties — the mapping from mode
//  (relaxed / intensive / custom) to concrete SRS scheduling parameters.
//  A regression here shifts the entire review schedule for all users.
//

import Testing
@testable import BooksAndVocab

struct ReviewSettingsEffectiveParamsTests {

    private var relaxed: ReviewSettings {
        var s = ReviewSettings.default
        s.mode = .relaxed
        return s
    }

    private var intensive: ReviewSettings {
        var s = ReviewSettings.default
        s.mode = .intensive
        return s
    }

    private var custom: ReviewSettings {
        var s = ReviewSettings.default
        s.mode = .custom
        s.customInitialIntervalHours = 12
        s.customRememberedMultiplier = 2.0
        s.customForgotMultiplier = 0.4
        s.customMinimumIntervalHours = 3
        s.customMaximumIntervalHours = 720
        return s
    }

    // MARK: - effectiveInitialIntervalHours

    @Test func relaxedInitialIntervalIs24Hours() {
        #expect(relaxed.effectiveInitialIntervalHours == 24)
    }

    @Test func intensiveInitialIntervalIs8Hours() {
        #expect(intensive.effectiveInitialIntervalHours == 8)
    }

    @Test func customInitialIntervalReturnsCustomValue() {
        #expect(custom.effectiveInitialIntervalHours == 12)
    }

    // MARK: - effectiveRememberedMultiplier

    @Test func relaxedRememberedMultiplierIs2_5() {
        #expect(relaxed.effectiveRememberedMultiplier == 2.5)
    }

    @Test func intensiveRememberedMultiplierIs1_4() {
        #expect(intensive.effectiveRememberedMultiplier == 1.4)
    }

    @Test func customRememberedMultiplierReturnsCustomValue() {
        #expect(custom.effectiveRememberedMultiplier == 2.0)
    }

    // MARK: - effectiveForgotMultiplier

    @Test func relaxedForgotMultiplierIs0_5() {
        #expect(relaxed.effectiveForgotMultiplier == 0.5)
    }

    @Test func intensiveForgotMultiplierIs0_35() {
        #expect(intensive.effectiveForgotMultiplier == 0.35)
    }

    @Test func customForgotMultiplierReturnsCustomValue() {
        #expect(custom.effectiveForgotMultiplier == 0.4)
    }

    // MARK: - effectiveMinimumIntervalHours

    @Test func relaxedMinimumIntervalIs6Hours() {
        #expect(relaxed.effectiveMinimumIntervalHours == 6)
    }

    @Test func intensiveMinimumIntervalIs4Hours() {
        #expect(intensive.effectiveMinimumIntervalHours == 4)
    }

    @Test func customMinimumIntervalReturnsCustomValue() {
        #expect(custom.effectiveMinimumIntervalHours == 3)
    }

    // MARK: - effectiveMaximumIntervalHours

    @Test func relaxedMaximumIntervalIs1440Hours() {
        #expect(relaxed.effectiveMaximumIntervalHours == 1440)
    }

    @Test func intensiveMaximumIntervalIs1440Hours() {
        #expect(intensive.effectiveMaximumIntervalHours == 1440)
    }

    @Test func customMaximumIntervalReturnsCustomValue() {
        #expect(custom.effectiveMaximumIntervalHours == 720)
    }

    // MARK: - default values

    @Test func defaultModeIsRelaxed() {
        #expect(ReviewSettings.default.mode == .relaxed)
    }

    @Test func defaultInitialIntervalIs24() {
        #expect(ReviewSettings.default.effectiveInitialIntervalHours == 24)
    }

    @Test func defaultIsNotPaused() {
        #expect(ReviewSettings.default.isProgressPaused == false)
    }
}
