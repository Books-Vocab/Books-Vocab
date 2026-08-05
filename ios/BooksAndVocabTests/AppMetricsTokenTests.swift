//
//  AppMetricsTokenTests.swift
//  Books & Vocab Tests
//
//  Pins the raw numeric values of the design-system tokens in `AppMetrics.swift`
//  (`AppSpacing` 8pt grid, `AppRoundness` scale, `AppElevation` depth language).
//  These constants are referenced app-wide and a silent drift — e.g. nudging a
//  radius from 8 to 7 or an elevation opacity during a "polish" pass — degrades
//  visual consistency with no failing test and no obvious diff signal.
//
//  All expected values were read directly from `AppMetrics.swift` (the source of
//  truth), NOT from any design doc.
//

import SwiftUI
import Testing
@testable import BooksAndVocab

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

    // MARK: - AppRoundness (dimensionless t, the live corner system)

    @Test func roundnessScaleIsPinned() async throws {
        #expect(AppRoundness.none == 0)
        #expect(AppRoundness.card == 0.15)
        #expect(AppRoundness.control == 0.30)
        #expect(AppRoundness.icon == 0.45)
        #expect(AppRoundness.pill == 1)
    }

    @Test func roundnessScaleIsMonotonicallyIncreasing() async throws {
        let scale: [CGFloat] = [
            AppRoundness.none, AppRoundness.card,
            AppRoundness.control, AppRoundness.icon, AppRoundness.pill,
        ]
        #expect(zip(scale, scale.dropFirst()).allSatisfy { $0 < $1 })
    }

    @Test func roundnessStaysInTheUnitInterval() async throws {
        // t is dimensionless and normalised: 0 = square corner, 1 = radius eats
        // half the minor axis. A value outside [0,1] means someone put a pt
        // length in the roundness plane by mistake.
        for t in [AppRoundness.none, AppRoundness.card, AppRoundness.control,
                  AppRoundness.icon, AppRoundness.pill] {
            #expect(t >= 0 && t <= 1)
        }
    }

    @Test func skinRoundnessTracksTheScale() async throws {
        let skin = AppSkin.themed(.light)
        #expect(skin.roundness.card == AppRoundness.card)
        #expect(skin.roundness.control == AppRoundness.control)
        #expect(skin.roundness.icon == AppRoundness.icon)
        #expect(skin.roundness.pill == AppRoundness.pill)
    }

    @Test func roundnessIsThemeInvariant() async throws {
        let light = AppSkin.themed(.light).roundness
        let dark = AppSkin.themed(.dark).roundness
        #expect(light.card == dark.card)
        #expect(light.control == dark.control)
        #expect(light.icon == dark.icon)
        #expect(light.pill == dark.pill)
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
