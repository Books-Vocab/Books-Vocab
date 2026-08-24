import Foundation
import Testing
@testable import BooksAndVocab

struct NotebookSettingsResolverTests {
    private let customPolicy = ReviewPolicy(
        mode: .custom,
        customInitialIntervalHours: 3,
        customRememberedMultiplier: 1.7,
        customForgotMultiplier: 0.4,
        customMinimumIntervalHours: 2,
        customMaximumIntervalHours: 900
    )

    @Test func noOverrideUsesGlobalValuesExactly() {
        var global = ReviewSettings.default
        global.isProgressPaused = true
        global.progressPausedAt = Date(timeIntervalSince1970: 10)
        global.autoplaySpeed = .fast
        global.autoplaySoundEnabled = false
        let resolver = NotebookSettingsResolver(
            globalReviewSettings: global,
            globalCardLayout: .default
        )

        let resolved = resolver.resolve(notebookId: "nb-1")
        #expect(resolved.reviewPolicy == ReviewPolicy(global))
        #expect(resolved.cardLayout == .default)
        #expect(resolved.reviewPolicySource == .user)
        #expect(resolved.cardLayoutSource == .user)
        #expect(resolved.reviewPolicy.applying(to: global).isProgressPaused)
        #expect(resolved.reviewPolicy.applying(to: global).autoplaySpeed == .fast)
        #expect(resolved.reviewPolicy.applying(to: global).autoplaySoundEnabled == false)
    }

    @Test func notebookOverrideOnlyChangesItsNotebookAndKeepsGlobalChrome() {
        let notebookLayout = ReviewCardLayoutProfile(recognition: .compact, production: .standard)
        let resolver = NotebookSettingsResolver(
            globalReviewSettings: .default,
            globalCardLayout: .default,
            overrides: [
                "nb-1": NotebookSettingsOverride(
                    reviewPolicy: customPolicy,
                    cardLayout: notebookLayout
                )
            ]
        )

        let overridden = resolver.resolve(notebookId: "nb-1")
        let fallback = resolver.resolve(notebookId: "nb-2")
        #expect(overridden.reviewPolicy == customPolicy)
        #expect(overridden.cardLayout == notebookLayout)
        #expect(overridden.reviewPolicySource == .notebook)
        #expect(overridden.cardLayoutSource == .notebook)
        #expect(fallback.reviewPolicy == ReviewPolicy(.default))
        #expect(fallback.cardLayout == .default)
    }

    @Test func resetRepresentedByNilOverrideReturnsToGlobal() {
        let resolver = NotebookSettingsResolver(
            globalReviewSettings: .default,
            globalCardLayout: .default,
            overrides: ["nb-1": .empty]
        )
        let snapshot = resolver.snapshot(for: ["nb-1", "nb-2"])
        #expect(snapshot.reviewSettings(for: "nb-1") == .default)
        #expect(snapshot.cardLayout(for: "nb-1") == .default)
        #expect(snapshot.notebookReviewPolicies.isEmpty)
        #expect(snapshot.notebookCardLayouts.isEmpty)
    }

    @Test func mixedNotebookSnapshotResolvesEachCardPolicy() {
        let resolver = NotebookSettingsResolver(
            globalReviewSettings: .default,
            globalCardLayout: .default,
            overrides: [
                "nb-custom": NotebookSettingsOverride(reviewPolicy: customPolicy, cardLayout: nil)
            ]
        )
        let snapshot = resolver.snapshot(for: ["nb-global", "nb-custom"])
        #expect(snapshot.reviewSettings(for: "nb-global") == .default)
        #expect(snapshot.reviewSettings(for: "nb-custom").mode == .custom)
        #expect(snapshot.reviewSettings(for: "nb-custom").customInitialIntervalHours == 3)
    }
}
