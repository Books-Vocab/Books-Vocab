//
//  NotebookStackMetricsTests.swift
//  Books & Vocab Tests
//
//  Pins the pure geometry / jitter helpers in `NotebookStackMetrics`. These values
//  drive `NotebookStackedCoverView` layout every frame, and a regression in
//  `layerCount` boundary buckets or `stableSeed` determinism would jitter the
//  editorial stack across launches or grow the deck past its 4-layer cap.
//

import Foundation
import SwiftUI
import Testing
@testable import BooksAndVocab

struct NotebookStackMetricsTests {

    // MARK: - layerCount(forCardCount:)

    @Test func layerCountEmptyNotebookFallsBackToSingleLayer() async throws {
        #expect(NotebookStackMetrics.layerCount(forCardCount: 0) == 1)
        #expect(NotebookStackMetrics.layerCount(forCardCount: -5) == 1)
    }

    @Test func layerCountThinDeckBucket() async throws {
        #expect(NotebookStackMetrics.layerCount(forCardCount: 1) == 2)
        #expect(NotebookStackMetrics.layerCount(forCardCount: 25) == 2)
        #expect(NotebookStackMetrics.layerCount(forCardCount: 50) == 2)
    }

    @Test func layerCountMediumDeckBucket() async throws {
        #expect(NotebookStackMetrics.layerCount(forCardCount: 51) == 3)
        #expect(NotebookStackMetrics.layerCount(forCardCount: 120) == 3)
        #expect(NotebookStackMetrics.layerCount(forCardCount: 200) == 3)
    }

    @Test func layerCountCapsAtFourLayers() async throws {
        #expect(NotebookStackMetrics.layerCount(forCardCount: 201) == 4)
        #expect(NotebookStackMetrics.layerCount(forCardCount: 1_000) == 4)
        #expect(NotebookStackMetrics.layerCount(forCardCount: Int.max) == 4)
    }

    // MARK: - Layer table integrity (jitter arrays must cover max depth)

    @Test func layerTablesCoverMaxLayerCount() async throws {
        // layerCount caps at 4 — both rotation + dx jitter arrays must have ≥ 4 entries
        // so `seedJitter(depth:)` never falls off the end for the deepest ghost.
        #expect(NotebookStackMetrics.layerRotations.count >= 4)
        #expect(NotebookStackMetrics.layerDxJitter.count >= 4)
    }

    // MARK: - seedJitter(seed:depth:) determinism + clamping

    @Test func seedJitterDeterministicAcrossCalls() async throws {
        let a = NotebookStackMetrics.seedJitter(seed: 12345, depth: 2)
        let b = NotebookStackMetrics.seedJitter(seed: 12345, depth: 2)
        #expect(a.angle == b.angle)
        #expect(a.dx == b.dx)
    }

    @Test func seedJitterDepthClampedToTopWhenNegative() async throws {
        let clamped = NotebookStackMetrics.seedJitter(seed: 7, depth: -10)
        let top = NotebookStackMetrics.seedJitter(seed: 7, depth: 0)
        // Negative depth is clamped to 0 — `mixed` differs (depth term changes), but
        // base values are pulled from index 0. We only assert it does not crash and
        // the returned angle stays within ±50% of the base rotation.
        let base = NotebookStackMetrics.layerRotations[0]
        #expect(abs(clamped.angle) <= abs(base) * 1.5 + 0.0001)
        _ = top
    }

    @Test func seedJitterDepthClampedToLastWhenOverflowing() async throws {
        let overflow = NotebookStackMetrics.seedJitter(seed: 7, depth: 999)
        let base = NotebookStackMetrics.layerRotations.last ?? 0
        #expect(abs(overflow.angle) <= abs(base) * 1.5 + 0.0001)
    }

    @Test func seedJitterNegativeSeedStaysWithinRange() async throws {
        // Regression: Swift `%` on negative operands yields negative — `abs()` guard
        // in the implementation keeps perturb ∈ [-0.5, +0.5]. Verify range invariant.
        for depth in 0..<4 {
            let result = NotebookStackMetrics.seedJitter(seed: -987_654, depth: depth)
            let baseAngle = NotebookStackMetrics.layerRotations[depth]
            let baseDx = NotebookStackMetrics.layerDxJitter[depth]
            #expect(abs(result.angle) <= abs(baseAngle) * 1.5 + 0.0001)
            #expect(abs(result.dx) <= abs(baseDx) * 1.5 + 0.0001)
        }
    }

    // MARK: - stableSeed(for:)

    @Test func stableSeedIsDeterministicAcrossCalls() async throws {
        let s1 = NotebookStackMetrics.stableSeed(for: "我的詞彙本")
        let s2 = NotebookStackMetrics.stableSeed(for: "我的詞彙本")
        #expect(s1 == s2)
    }

    @Test func stableSeedKnownDjb2Values() async throws {
        // djb2 reference values — pins the hash so cross-launch rotation never drifts.
        // hash("") = 5381; hash("a") = 5381*33 + 97 = 177670.
        #expect(NotebookStackMetrics.stableSeed(for: "") == 5381)
        #expect(NotebookStackMetrics.stableSeed(for: "a") == 177_670)
    }

    @Test func stableSeedAlwaysNonNegative() async throws {
        for s in ["", "a", "long notebook name 很長的名字", "🍎📚"] {
            #expect(NotebookStackMetrics.stableSeed(for: s) >= 0)
        }
    }

    @Test func stableSeedDifferentInputsDiffer() async throws {
        let a = NotebookStackMetrics.stableSeed(for: "alpha")
        let b = NotebookStackMetrics.stableSeed(for: "beta")
        #expect(a != b)
    }

    // MARK: - ghostPaperColor(depth:scheme:)

    @Test func ghostPaperColorMapsDepthToCorrectPaperToken() async throws {
        // depth 1 → paperLight, depth 2 → paperSepia, depth ≥ 3 → paperSepiaDeep.
        // `Color` conforms to Equatable when both sides are constructed from the
        // same provenance (here: identical `AppColors.*` static lookup).
        #expect(NotebookStackMetrics.ghostPaperColor(depth: 1, scheme: .light) == AppColors.paperLight)
        #expect(NotebookStackMetrics.ghostPaperColor(depth: 2, scheme: .light) == AppColors.paperSepia)
        #expect(NotebookStackMetrics.ghostPaperColor(depth: 3, scheme: .light) == AppColors.paperSepiaDeep)
        #expect(NotebookStackMetrics.ghostPaperColor(depth: 4, scheme: .light) == AppColors.paperSepiaDeep)
        // depths below 1 fall into the `default` branch and resolve to paperSepiaDeep.
        #expect(NotebookStackMetrics.ghostPaperColor(depth: 0, scheme: .light) == AppColors.paperSepiaDeep)
    }

    @Test func ghostPaperColorIgnoresColorScheme() async throws {
        // Implementation explicitly silences scheme — dark variant pending. Pin
        // current behavior so a future dark hook doesn't silently regress light.
        #expect(
            NotebookStackMetrics.ghostPaperColor(depth: 1, scheme: .light)
            == NotebookStackMetrics.ghostPaperColor(depth: 1, scheme: .dark)
        )
        #expect(
            NotebookStackMetrics.ghostPaperColor(depth: 2, scheme: .light)
            == NotebookStackMetrics.ghostPaperColor(depth: 2, scheme: .dark)
        )
    }
}
