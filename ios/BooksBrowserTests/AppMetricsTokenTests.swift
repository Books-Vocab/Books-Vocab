//
//  AppMetricsTokenTests.swift
//  Books & Vocab Tests
//
//  Pins the raw numeric values of the design-system tokens in `AppMetrics.swift`
//  (`AppSpacing` 8pt grid, `AppRadius` scale, `AppElevation` depth language).
//  These constants are referenced app-wide and a silent drift — e.g. nudging a
//  radius from 8 to 7 or an elevation opacity during a "polish" pass — degrades
//  visual consistency with no failing test and no obvious diff signal.
//
//  All expected values were read directly from `AppMetrics.swift` (the source of
//  truth), NOT from any design doc — the docs are known to disagree on `AppRadius`.
//

import SwiftUI
import Testing
@testable import BooksBrowser

@Suite struct AppMetricsTokenTests {

    // MARK: - AppSpacing (8pt grid)

    @Test func spacingGridStepsArePinned() async throws {
        #expect(AppSpacing.zero == 0)
        #expect(AppSpacing.hairline == 1)
        #expect(AppSpacing.microGap == 2)
        #expect(AppSpacing.tinyGap == 3)
        #expect(AppSpacing.s1 == 4)
        #expect(AppSpacing.s2 == 8)
        #expect(AppSpacing.s3 == 12)
        #expect(AppSpacing.s4 == 16)
        #expect(AppSpacing.s5 == 20)
        #expect(AppSpacing.s6 == 24)
        #expect(AppSpacing.s7 == 32)
        #expect(AppSpacing.s8 == 40)
        #expect(AppSpacing.s9 == 48)
        #expect(AppSpacing.s10 == 64)
    }

    @Test func spacingCardAliasesTrackTheirGridSteps() async throws {
        // Card padding tokens are defined as aliases of grid steps; pin both the
        // value and the aliasing so a future grid retune can't desync them.
        #expect(AppSpacing.cardOuterPadding == 24)
        #expect(AppSpacing.cardOuterPadding == AppSpacing.s6)
        #expect(AppSpacing.cardInnerGap == 16)
        #expect(AppSpacing.cardInnerGap == AppSpacing.s4)
        #expect(AppSpacing.cardSectionGap == 12)
        #expect(AppSpacing.cardSectionGap == AppSpacing.s3)
    }

    @Test func spacingStepsAreMonotonicallyIncreasing() async throws {
        let scale: [CGFloat] = [
            AppSpacing.s1, AppSpacing.s2, AppSpacing.s3, AppSpacing.s4,
            AppSpacing.s5, AppSpacing.s6, AppSpacing.s7, AppSpacing.s8,
            AppSpacing.s9, AppSpacing.s10,
        ]
        #expect(zip(scale, scale.dropFirst()).allSatisfy { $0 < $1 })
    }

    // MARK: - AppRadius

    @Test func radiusScaleIsPinned() async throws {
        // Values read from AppMetrics.swift — the design doc is stale on these.
        #expect(AppRadius.none == 0)
        #expect(AppRadius.xs == 4)
        #expect(AppRadius.sm == 6)
        #expect(AppRadius.md == 8)
        #expect(AppRadius.lg == 12)
        #expect(AppRadius.xl == 16)
        #expect(AppRadius.pill == 999)
    }

    @Test func radiusScaleIsMonotonicallyIncreasing() async throws {
        let scale: [CGFloat] = [
            AppRadius.none, AppRadius.xs, AppRadius.sm,
            AppRadius.md, AppRadius.lg, AppRadius.xl, AppRadius.pill,
        ]
        #expect(zip(scale, scale.dropFirst()).allSatisfy { $0 < $1 })
    }

    // MARK: - AppElevation (z0 flush → z4 modal)

    @Test func elevationOpacityIsPinned() async throws {
        #expect(AppElevation.z0.opacity == 0)
        #expect(AppElevation.z1.opacity == 0.03)
        #expect(AppElevation.z2.opacity == 0.06)
        #expect(AppElevation.z3.opacity == 0.10)
        #expect(AppElevation.z4.opacity == 0.16)
    }

    @Test func elevationRadiusIsPinned() async throws {
        #expect(AppElevation.z0.radius == 0)
        #expect(AppElevation.z1.radius == 4)
        #expect(AppElevation.z2.radius == 10)
        #expect(AppElevation.z3.radius == 18)
        #expect(AppElevation.z4.radius == 28)
    }

    @Test func elevationOffsetYIsPinned() async throws {
        #expect(AppElevation.z0.y == 0)
        #expect(AppElevation.z1.y == 1)
        #expect(AppElevation.z2.y == 4)
        #expect(AppElevation.z3.y == 8)
        #expect(AppElevation.z4.y == 14)
    }

    @Test func elevationDepthIncreasesAcrossLevels() async throws {
        // z0 flush → z4 modal: every depth dimension must climb monotonically so
        // the layering language stays legible (no two levels collapsing together).
        let levels: [AppElevation] = [.z0, .z1, .z2, .z3, .z4]
        #expect(zip(levels, levels.dropFirst()).allSatisfy { $0.opacity < $1.opacity })
        #expect(zip(levels, levels.dropFirst()).allSatisfy { $0.radius < $1.radius })
        #expect(zip(levels, levels.dropFirst()).allSatisfy { $0.y < $1.y })
    }
}
