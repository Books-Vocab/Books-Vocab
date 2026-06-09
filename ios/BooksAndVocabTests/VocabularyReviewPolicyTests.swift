//
//  VocabularyReviewPolicyTests.swift
//  Books & Vocab Tests
//
//  鎖 SRS（間隔複習）排程核心的純函式行為。
//  涵蓋三個目標:
//    1. VocabularyReviewPolicy.nextIntervalHours — base/clamp/multiplier 公式
//    2. VocabularyEntry.applyReviewFeedback — 首次 vs 後續、streak/lapse 轉移、nextReviewAt
//    3. ReviewSettings.effective* — relaxed/intensive/custom 三模式各 getter
//
//  所有 expected 值皆從 VocabularyReview.swift / ReviewSettings.swift 的實作公式
//  親手推導(見每個 case 行內註解的算式),非照抄外部舉例。
//

import Foundation
import Testing
@testable import BooksAndVocab

// MARK: - 目標 1: VocabularyReviewPolicy.nextIntervalHours
//
// 實作(default 多載, VocabularyReview.swift:76-83):
//   let base = max(currentIntervalHours, minimumIntervalHours)   // min=6
//   let multiplier = remembered ? 1.9 : 0.45
//   return min(maximumIntervalHours, max(minimumIntervalHours, base * multiplier))  // max=1440, floor=6

@Suite struct VocabularyReviewPolicyNextIntervalTests {
    private func expectApprox(
        _ actual: Double,
        _ expected: Double,
        sourceLocation: SourceLocation = #_sourceLocation
    ) {
        #expect(abs(actual - expected) < 0.000_000_001, sourceLocation: sourceLocation)
    }

    @Test func remembered_happy_path_multipliesByRememberedMultiplier() {
        // base = max(12, 6) = 12; 12 * 1.9 = 22.8; clamp(6, 1440) → 22.8
        let result = VocabularyReviewPolicy.nextIntervalHours(
            currentIntervalHours: 12,
            feedback: .remembered
        )
        expectApprox(result, 22.8)
    }

    @Test func remembered_clampsBaseUpToMinimum_whenCurrentBelowMin() {
        // current=3 < min=6 → base = max(3, 6) = 6; 6 * 1.9 = 11.4; clamp → 11.4
        let result = VocabularyReviewPolicy.nextIntervalHours(
            currentIntervalHours: 3,
            feedback: .remembered
        )
        expectApprox(result, 11.4)
    }

    @Test func remembered_clampsResultToMaximum_whenProductExceedsMax() {
        // base = max(1000, 6) = 1000; 1000 * 1.9 = 1900; min(1440, 1900) = 1440
        let result = VocabularyReviewPolicy.nextIntervalHours(
            currentIntervalHours: 1000,
            feedback: .remembered
        )
        #expect(result == 1440)
    }

    @Test func forgot_shortensInterval_viaForgotMultiplier() {
        // base = max(100, 6) = 100; 100 * 0.45 = 45; clamp(6, 1440) → 45
        let result = VocabularyReviewPolicy.nextIntervalHours(
            currentIntervalHours: 100,
            feedback: .forgot
        )
        #expect(result == 45)
    }

    @Test func zeroCurrent_floorsBaseToMinimum() {
        // current=0 → base = max(0, 6) = 6; remembered: 6 * 1.9 = 11.4
        let result = VocabularyReviewPolicy.nextIntervalHours(
            currentIntervalHours: 0,
            feedback: .remembered
        )
        expectApprox(result, 11.4)
    }

    @Test func forgot_resultFloorWins_whenProductBelowMinimum() {
        // base = max(6, 6) = 6; forgot: 6 * 0.45 = 2.7; max(6, 2.7) = 6 (floor 生效)
        let result = VocabularyReviewPolicy.nextIntervalHours(
            currentIntervalHours: 6,
            feedback: .forgot
        )
        #expect(result == 6)
    }

    @Test func extremeNegativeCurrent_treatedAsBelowMinimum() {
        // current=-50 → base = max(-50, 6) = 6; remembered: 6 * 1.9 = 11.4
        let result = VocabularyReviewPolicy.nextIntervalHours(
            currentIntervalHours: -50,
            feedback: .remembered
        )
        expectApprox(result, 11.4)
    }

    // settings 多載(VocabularyReview.swift:85-95)使用 settings.effective* 邊界與乘數。
    // 以 .intensive 驗證 min=4, rem=1.4 真的被採用(而非 default 的 6/1.9)。
    @Test func settingsOverload_usesIntensiveBoundsAndMultiplier() {
        // intensive: min=4, max=1440, rem=1.4
        // current=2 < min=4 → base = max(2, 4) = 4; 4 * 1.4 = 5.6; clamp(4, 1440) → 5.6
        let result = VocabularyReviewPolicy.nextIntervalHours(
            currentIntervalHours: 2,
            feedback: .remembered,
            settings: ReviewSettings(
                mode: .intensive,
                customInitialIntervalHours: 0,
                customRememberedMultiplier: 0,
                customForgotMultiplier: 0,
                customMinimumIntervalHours: 0,
                customMaximumIntervalHours: 0
            )
        )
        #expect(result == 5.6)
    }
}

// MARK: - 目標 2: VocabularyEntry.applyReviewFeedback
//
// 實作(VocabularyReview.swift:127-149):
//   baseInterval = reviewCount == 0 ? settings.effectiveInitialIntervalHours : reviewIntervalHours
//   updatedInterval = nextIntervalHours(currentIntervalHours: baseInterval, feedback, settings)
//   reviewIntervalHours = updatedInterval
//   nextReviewAt = now + updatedInterval * 3600
//   lastReviewedAt = now; reviewCount += 1; lastReviewFeedbackRaw = feedback.rawValue
//   remembered → reviewStreak += 1 ; forgot → lapseCount += 1, reviewStreak = 0

@Suite struct VocabularyEntryApplyReviewFeedbackTests {

    private func makeEntry() -> VocabularyEntry {
        VocabularyEntry(word: "w", translation: "t", context: "c", bookTitle: "b")
    }

    /// 固定 now,避免 Date() 浮動;比對到秒級即可。
    private let fixedNow = Date(timeIntervalSince1970: 1_700_000_000)

    @Test func firstReview_usesEffectiveInitialInterval_notStoredInterval() {
        // reviewCount==0 → base = effectiveInitialIntervalHours(.relaxed default = 24),
        // 忽略 entry 自身的 reviewIntervalHours(預設 12)。
        // .default mode = .relaxed: init=24, rem=2.5, min=6, max=1440
        // base = max(24, 6) = 24; 24 * 2.5 = 60; clamp → 60
        let entry = makeEntry()
        #expect(entry.reviewCount == 0)
        entry.applyReviewFeedback(.remembered, settings: .default, now: fixedNow)

        #expect(entry.reviewIntervalHours == 60)
        #expect(entry.reviewCount == 1)
        #expect(entry.reviewStreak == 1)
        #expect(entry.lapseCount == 0)
        #expect(entry.lastReviewedAt == fixedNow)
        #expect(entry.lastReviewFeedbackRaw == ReviewFeedback.remembered.rawValue)
        // nextReviewAt = now + 60h * 3600 = now + 216000s
        #expect(entry.nextReviewAt == fixedNow.addingTimeInterval(60 * 3600))
    }

    @Test func subsequentReview_usesStoredInterval_notInitial() {
        // 先做一次首評 → reviewCount=1, reviewIntervalHours=60。
        // 第二次 remembered: reviewCount!=0 → base = reviewIntervalHours = 60。
        // .relaxed: 60 * 2.5 = 150; clamp(6, 1440) → 150。
        let entry = makeEntry()
        entry.applyReviewFeedback(.remembered, settings: .default, now: fixedNow)
        #expect(entry.reviewIntervalHours == 60)

        let now2 = fixedNow.addingTimeInterval(60 * 3600)
        entry.applyReviewFeedback(.remembered, settings: .default, now: now2)

        #expect(entry.reviewIntervalHours == 150)
        #expect(entry.reviewCount == 2)
        #expect(entry.nextReviewAt == now2.addingTimeInterval(150 * 3600))
    }

    @Test func consecutiveRemembered_accumulatesStreak() {
        let entry = makeEntry()
        var now = fixedNow
        for expectedStreak in 1...3 {
            entry.applyReviewFeedback(.remembered, settings: .default, now: now)
            #expect(entry.reviewStreak == expectedStreak)
            now = entry.nextReviewAt
        }
        #expect(entry.reviewCount == 3)
        #expect(entry.lapseCount == 0)
    }

    @Test func forgot_resetsStreak_andIncrementsLapse() {
        let entry = makeEntry()
        // 建 streak = 2
        entry.applyReviewFeedback(.remembered, settings: .default, now: fixedNow)
        entry.applyReviewFeedback(.remembered, settings: .default, now: entry.nextReviewAt)
        #expect(entry.reviewStreak == 2)
        #expect(entry.lapseCount == 0)

        // forgot → streak 歸零, lapse+1
        let nowForgot = entry.nextReviewAt
        entry.applyReviewFeedback(.forgot, settings: .default, now: nowForgot)
        #expect(entry.reviewStreak == 0)
        #expect(entry.lapseCount == 1)
        #expect(entry.lastReviewFeedbackRaw == ReviewFeedback.forgot.rawValue)
    }

    @Test func firstReviewForgot_usesInitialInterval_shortenedByForgotMultiplier() {
        // reviewCount==0, forgot, .relaxed: base = init = 24; forgot mult = 0.5
        // 24 * 0.5 = 12; clamp(min=6, max=1440) → 12
        let entry = makeEntry()
        entry.applyReviewFeedback(.forgot, settings: .default, now: fixedNow)

        #expect(entry.reviewIntervalHours == 12)
        #expect(entry.lapseCount == 1)
        #expect(entry.reviewStreak == 0)
        #expect(entry.nextReviewAt == fixedNow.addingTimeInterval(12 * 3600))
    }

    @Test func nextReviewAt_isExactlyNowPlusIntervalSeconds() {
        // 顯式驗 now 注入契約: nextReviewAt == now + interval*3600。
        // .intensive: init=8, rem=1.4 → base=max(8,4)=8; 8*1.4=11.2; clamp(4,1440) → 11.2
        let entry = makeEntry()
        let settings = ReviewSettings(
            mode: .intensive,
            customInitialIntervalHours: 0,
            customRememberedMultiplier: 0,
            customForgotMultiplier: 0,
            customMinimumIntervalHours: 0,
            customMaximumIntervalHours: 0
        )
        entry.applyReviewFeedback(.remembered, settings: settings, now: fixedNow)
        #expect(entry.reviewIntervalHours == 11.2)
        #expect(entry.nextReviewAt == fixedNow.addingTimeInterval(11.2 * 3600))
    }
}

// MARK: - 目標 3: ReviewSettings.effective*
//
// 實作(ReviewSettings.swift:44-82):
//   relaxed   → init=24, rem=2.5, forgot=0.5,  min=6, max=1440
//   intensive → init=8,  rem=1.4, forgot=0.35, min=4, max=1440
//   custom    → 直通 customXxx 欄位

@Suite struct ReviewSettingsEffectiveValueTests {

    private func settings(_ mode: ReviewSettingsMode, custom: Double = -999) -> ReviewSettings {
        ReviewSettings(
            mode: mode,
            customInitialIntervalHours: custom,
            customRememberedMultiplier: custom,
            customForgotMultiplier: custom,
            customMinimumIntervalHours: custom,
            customMaximumIntervalHours: custom
        )
    }

    @Test func relaxedMode_returnsRelaxedConstants() {
        let s = settings(.relaxed)
        #expect(s.effectiveInitialIntervalHours == 24)
        #expect(s.effectiveRememberedMultiplier == 2.5)
        #expect(s.effectiveForgotMultiplier == 0.5)
        #expect(s.effectiveMinimumIntervalHours == 6)
        #expect(s.effectiveMaximumIntervalHours == 1440)
    }

    @Test func intensiveMode_returnsIntensiveConstants() {
        let s = settings(.intensive)
        #expect(s.effectiveInitialIntervalHours == 8)
        #expect(s.effectiveRememberedMultiplier == 1.4)
        #expect(s.effectiveForgotMultiplier == 0.35)
        #expect(s.effectiveMinimumIntervalHours == 4)
        #expect(s.effectiveMaximumIntervalHours == 1440)
    }

    @Test func customMode_passesThroughUserValues() {
        // custom 模式所有 getter 直通用戶輸入,不替換成 preset 常數。
        let s = ReviewSettings(
            mode: .custom,
            customInitialIntervalHours: 36,
            customRememberedMultiplier: 3.1,
            customForgotMultiplier: 0.2,
            customMinimumIntervalHours: 2,
            customMaximumIntervalHours: 999
        )
        #expect(s.effectiveInitialIntervalHours == 36)
        #expect(s.effectiveRememberedMultiplier == 3.1)
        #expect(s.effectiveForgotMultiplier == 0.2)
        #expect(s.effectiveMinimumIntervalHours == 2)
        #expect(s.effectiveMaximumIntervalHours == 999)
    }

    @Test func activeReviewReferenceDateUsesNow() {
        let now = Date(timeIntervalSince1970: 1_780_704_000)
        let pausedAt = now.addingTimeInterval(-86_400)
        var s = settings(.relaxed)
        s.isProgressPaused = false
        s.progressPausedAt = pausedAt
        #expect(s.reviewReferenceDate(now: now) == now)
    }

    @Test func pausedReviewReferenceDateFreezesAtPausedAt() {
        let now = Date(timeIntervalSince1970: 1_780_704_000)
        let pausedAt = now.addingTimeInterval(-86_400)
        var s = settings(.relaxed)
        s.isProgressPaused = true
        s.progressPausedAt = pausedAt
        #expect(s.reviewReferenceDate(now: now) == pausedAt)
    }

    // Table-driven: preset 模式應【忽略】custom 欄位,custom 模式應【採用】之。
    @Test(arguments: [
        (ReviewSettingsMode.relaxed,   24.0, 2.5, 0.5,  6.0,  1440.0),
        (ReviewSettingsMode.intensive, 8.0,  1.4, 0.35, 4.0,  1440.0),
    ])
    func presetModesIgnoreCustomFields(
        mode: ReviewSettingsMode,
        expectedInit: Double,
        expectedRem: Double,
        expectedForgot: Double,
        expectedMin: Double,
        expectedMax: Double
    ) {
        // 餵明顯不同的 custom 值(7777),驗 preset getter 不被污染。
        let s = settings(mode, custom: 7777)
        #expect(s.effectiveInitialIntervalHours == expectedInit)
        #expect(s.effectiveRememberedMultiplier == expectedRem)
        #expect(s.effectiveForgotMultiplier == expectedForgot)
        #expect(s.effectiveMinimumIntervalHours == expectedMin)
        #expect(s.effectiveMaximumIntervalHours == expectedMax)
    }
}
