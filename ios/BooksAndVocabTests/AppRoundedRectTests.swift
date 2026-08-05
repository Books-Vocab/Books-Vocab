//
//  AppRoundedRectTests.swift
//  Books & Vocab Tests
//
//  Pins the geometry contract of `AppRoundedRect` — the single rounded-rectangle
//  shape for the whole app. Corner radius is derived at render time from the
//  shape's own box via a dimensionless roundness `t`:
//
//      r = t · min(W, H) / 2 ,   0 ≤ t ≤ 1
//
//  A silent drift here (clamping the wrong way, using max instead of min,
//  recomputing the base off the inset box) is invisible in a diff but changes
//  every corner in the app at once.
//
//  Deliberately NOT asserted: that t = 1 degenerates to `Circle()` or `Capsule()`.
//  The product decision is that the t = 1 endpoint stays a continuous-curvature
//  squircle, not a circular-arc capsule.
//

import SwiftUI
import Testing
@testable import BooksAndVocab

@Suite struct AppRoundedRectTests {

    private let wide = CGRect(x: 0, y: 0, width: 300, height: 100)   // min = 100
    private let tall = CGRect(x: 0, y: 0, width: 80, height: 240)    // min = 80
    private let square = CGRect(x: 0, y: 0, width: 120, height: 120) // min = 120

    // MARK: - Core formula

    @Test func radiusIsHalfTheMinorAxisTimesRoundness() async throws {
        #expect(AppRoundedRect(roundness: 0.5).radius(in: wide) == 25)    // 0.5 · 100/2
        #expect(AppRoundedRect(roundness: 0.5).radius(in: tall) == 20)    // 0.5 · 80/2
        #expect(AppRoundedRect(roundness: 0.5).radius(in: square) == 30)  // 0.5 · 120/2
    }

    @Test func radiusUsesTheMinorAxisNotTheMajor() async throws {
        // 300×100 and 100×300 must round identically — orientation must not matter.
        let landscape = CGRect(x: 0, y: 0, width: 300, height: 100)
        let portrait = CGRect(x: 0, y: 0, width: 100, height: 300)
        let shape = AppRoundedRect(roundness: 0.8)
        #expect(shape.radius(in: landscape) == shape.radius(in: portrait))
        #expect(shape.radius(in: landscape) == 40) // 0.8 · 100/2
    }

    @Test func zeroRoundnessIsASquareCorner() async throws {
        #expect(AppRoundedRect(roundness: 0).radius(in: wide) == 0)
        #expect(AppRoundedRect(roundness: 0).radius(in: square) == 0)
    }

    @Test func fullRoundnessReachesHalfTheMinorAxis() async throws {
        #expect(AppRoundedRect(roundness: 1).radius(in: wide) == 50)
        #expect(AppRoundedRect(roundness: 1).radius(in: square) == 60)
    }

    @Test func roundnessIsClampedToTheUnitInterval() async throws {
        #expect(AppRoundedRect(roundness: -0.5).radius(in: wide) == 0)
        #expect(AppRoundedRect(roundness: 1.5).radius(in: wide) == 50)   // same as t = 1
        #expect(AppRoundedRect(roundness: 99).radius(in: square) == 60)
    }

    @Test func radiusScalesLinearlyWithRoundness() async throws {
        // Non-square on purpose: a square box hides minor/major-axis mistakes.
        for step in 0...10 {
            let t = CGFloat(step) / 10
            #expect(abs(AppRoundedRect(roundness: t).radius(in: wide) - t * 50) < 0.0001)
        }
    }

    @Test func radiusIsIndependentOfOrigin() async throws {
        let atOrigin = CGRect(x: 0, y: 0, width: 120, height: 60)
        let offset = CGRect(x: 57, y: -13, width: 120, height: 60)
        let shape = AppRoundedRect(roundness: 0.4)
        #expect(shape.radius(in: atOrigin) == shape.radius(in: offset))
    }

    // MARK: - Concentric inset (drives .strokeBorder and nested containers)

    @Test func insettingShrinksTheRadiusByExactlyTheInset() async throws {
        // Concentric requires r_inner == r_outer − d, NOT t·(min−2d)/2.
        // On `wide` (300×100): base = 50, so t=0.5 → 25, and inset 4 → 21.
        // The proportional-recompute mistake would give 0.5·(100−8)/2 = 23.
        #expect(AppRoundedRect(roundness: 0.5).radius(in: wide) == 25)
        #expect(AppRoundedRect(roundness: 0.5).inset(by: 4).radius(in: wide) == 21)
    }

    @Test func insetRadiusNeverGoesNegative() async throws {
        // t·min/2 = 5, inset 20 → would be −15; must floor at 0, not invert.
        #expect(AppRoundedRect(roundness: 0.1).inset(by: 20).radius(in: wide) == 0)
    }

    @Test func insetsAccumulate() async throws {
        let once = AppRoundedRect(roundness: 0.5).inset(by: 10).radius(in: wide)
        let twice = AppRoundedRect(roundness: 0.5).inset(by: 4).inset(by: 6).radius(in: wide)
        #expect(once == twice)
        #expect(once == 15) // 0.5 · 100/2 − 10
    }

    @Test func concentricIdentityHoldsAtExtremeInsets() async throws {
        // Deep inset stays on the r = t·base − d line all the way down to the floor.
        // (No separate box-clamp is needed: t ≤ 1 makes t·base − d ≤ base − d, which
        // is exactly half the inset box's minor axis.)
        #expect(AppRoundedRect(roundness: 1).inset(by: 40).radius(in: wide) == 10)
        #expect(AppRoundedRect(roundness: 1).inset(by: 49).radius(in: wide) == 1)
        #expect(AppRoundedRect(roundness: 1).inset(by: 50).radius(in: wide) == 0)
    }

    // MARK: - Path agreement with the reference shape

    // The expected radius is a LITERAL here, never re-derived from the shape under
    // test. Deriving it from `shape.radius(in:)` would make these pass vacuously
    // no matter how wrong the arithmetic is.

    @Test func pathMatchesRoundedRectangleAtTheDerivedRadius() async throws {
        let expected = RoundedRectangle(cornerRadius: 15, style: .continuous) // 0.3 · 100/2
        #expect(AppRoundedRect(roundness: 0.3).path(in: wide) == expected.path(in: wide))
    }

    @Test func insetPathIsDrawnInsideTheInsetBox() async throws {
        let inset: CGFloat = 8
        let expected = RoundedRectangle(cornerRadius: 12, style: .continuous) // 0.4 · 100/2 − 8
        let box = wide.insetBy(dx: inset, dy: inset)
        #expect(AppRoundedRect(roundness: 0.4).inset(by: inset).path(in: wide) == expected.path(in: box))
    }

    // MARK: - Animation

    @Test func animatableDataTracksRoundness() async throws {
        var shape = AppRoundedRect(roundness: 0.2)
        #expect(shape.animatableData == 0.2)
        shape.animatableData = 0.7
        #expect(shape.roundness == 0.7)
    }

    // MARK: - Per-corner variant

    @Test func unevenCornersShareTheSameMinorAxisBase() async throws {
        // Both corners derive from min(W,H)/2 of the SAME box, so equal t means equal r.
        let shape = AppUnevenRoundedRect(topRoundness: 0.5, bottomRoundness: 0.5)
        #expect(shape.topRadius(in: wide) == 25)
        #expect(shape.bottomRadius(in: wide) == 25)
    }

    @Test func unevenCornersAreIndependent() async throws {
        // Non-square box: `square` would make a minor/major-axis mistake invisible.
        let shape = AppUnevenRoundedRect(topRoundness: 0.5, bottomRoundness: 0)
        #expect(shape.topRadius(in: wide) == 25)
        #expect(shape.bottomRadius(in: wide) == 0)
    }

    @Test func unevenCornersAreClampedIndividually() async throws {
        let shape = AppUnevenRoundedRect(topRoundness: 4, bottomRoundness: -1)
        #expect(shape.topRadius(in: square) == 60)
        #expect(shape.bottomRadius(in: square) == 0)
    }

    // The radius accessors above are thin wrappers over one shared helper, so on
    // their own they leave `path(in:)` completely uncovered — swapping top for
    // bottom in the UnevenRoundedRectangle construction would keep them all green
    // while rendering every top-rounded book cover bottom-rounded instead.
    // These pin the corner-to-edge assignment itself.

    @Test func unevenPathAssignsEachRadiusToTheCorrectEdge() async throws {
        let shape = AppUnevenRoundedRect(topRoundness: 0.5, bottomRoundness: 0)
        let expected = UnevenRoundedRectangle(
            topLeadingRadius: 25,        // 0.5 · 100/2
            bottomLeadingRadius: 0,
            bottomTrailingRadius: 0,
            topTrailingRadius: 25,
            style: .continuous
        )
        #expect(shape.path(in: wide) == expected.path(in: wide))
    }

    @Test func unevenPathIsNotSymmetricUnderTopBottomSwap() async throws {
        // Guards the swap directly: these two must NOT produce the same path.
        let topRounded = AppUnevenRoundedRect(topRoundness: 0.5, bottomRoundness: 0)
        let bottomRounded = AppUnevenRoundedRect(topRoundness: 0, bottomRoundness: 0.5)
        #expect(topRounded.path(in: wide) != bottomRounded.path(in: wide))
    }

    @Test func unevenPathIsContinuousCurvatureLikeTheEvenShape() async throws {
        // `.circular` is the SwiftUI default; forgetting `style:` silently drops
        // the squircle. A circular reference must therefore NOT match.
        let shape = AppUnevenRoundedRect(topRoundness: 1, bottomRoundness: 1)
        let circular = UnevenRoundedRectangle(
            topLeadingRadius: 50, bottomLeadingRadius: 50,
            bottomTrailingRadius: 50, topTrailingRadius: 50,
            style: .circular
        )
        #expect(shape.path(in: wide) != circular.path(in: wide))
    }

    // MARK: - Degenerate boxes

    @Test func collapsedBoxYieldsAnEmptyPathRatherThanCrashing() async throws {
        // inset 60 on a 300×100 box leaves a 180×−20 rect: negative height.
        #expect(AppRoundedRect(roundness: 1).inset(by: 60).path(in: wide).isEmpty)
        #expect(AppRoundedRect(roundness: 0.5).path(in: .zero).isEmpty)
        #expect(AppUnevenRoundedRect(topRoundness: 0.5, bottomRoundness: 0).path(in: .zero).isEmpty)
    }
}
