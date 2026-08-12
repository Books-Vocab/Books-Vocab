#if DEBUG
import Foundation

/// Shared frozen-clock resolver for Catalog scenarios that render review state.
///
/// Calendar scenarios use `required(...)` below and never fall back. The
/// older `now(fallback:)` helper remains only for unrelated legacy scenarios
/// that have not yet adopted the calendar evidence contract.
///
/// The frozen epoch equals the UI World's
/// `review_settings_progress_paused_at` (single SoT), so aligning both the graph
/// `now` and the review-settings paused-at to it lets the ReviewGradient expand
/// its colour layers (fresh green → amber → due → overdue red) instead of
/// collapsing to all-green under a stale 2026-06-01 anchor.
enum FixtureReviewClock {
    /// Resolve the review clock required by a calendar scenario. This is
    /// deliberately fail-fast: a catalog calendar without an explicit clock
    /// is not deterministic evidence and must never silently fall back.
    static func required(
        context: UIWorldScenarioContextSeed?,
        reviewHistory: [UIWorldReviewHistorySeed],
        fixtureID: String
    ) -> ReviewCalendarClock {
        guard let seed = context?.reviewClock else {
            preconditionFailure(
                "UI World scenarioContext.reviewClock is required for review calendar fixture \(fixtureID)"
            )
        }
        guard let now = seed.now,
              let frozenEpoch = seed.frozenEpoch,
              let anchorDay = seed.anchorDay,
              let source = seed.source,
              !source.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              source == ReviewCalendarClock.historyPlanSource,
              let timeZoneIdentifier = seed.timeZone,
              let timeZone = TimeZone(identifier: timeZoneIdentifier)
        else {
            preconditionFailure(
                "UI World scenarioContext.reviewClock must declare now, frozenEpoch, anchorDay, timeZone, and source=\(ReviewCalendarClock.historyPlanSource) for fixture \(fixtureID)"
            )
        }

        guard let parsedNow = parseISO8601(now) else {
            preconditionFailure(
                "UI World scenarioContext.reviewClock.now is not ISO-8601 for fixture \(fixtureID)"
            )
        }
        let epochNow = Date(timeIntervalSince1970: TimeInterval(frozenEpoch))
        guard abs(parsedNow.timeIntervalSince1970 - epochNow.timeIntervalSince1970) < 0.5 else {
            preconditionFailure(
                "UI World review clock now/frozenEpoch drift for fixture \(fixtureID)"
            )
        }

        let clock = ReviewCalendarClock(
            now: epochNow,
            timeZone: timeZone,
            provenance: source
        )
        guard clock.dayKey(for: clock.now) == anchorDay else {
            preconditionFailure(
                "UI World review clock anchorDay does not match frozen now in \(timeZoneIdentifier) for fixture \(fixtureID)"
            )
        }

        if let latest = reviewHistory.map(\.reviewedAt).max() {
            let nowComponents = clock.calendar.dateComponents([.year, .month], from: clock.now)
            let latestComponents = clock.calendar.dateComponents([.year, .month], from: latest)
            let latestDay = clock.dayKey(for: latest)
            guard latest <= clock.now,
                  nowComponents.year == latestComponents.year,
                  nowComponents.month == latestComponents.month,
                  latestDay <= anchorDay
            else {
                preconditionFailure(
                    "UI World reviewHistory latest month/day is outside the injected review clock source for fixture \(fixtureID)"
                )
            }
        }
        return clock
    }

    /// Frozen "now" for structured scenarios, or `fallback` when the UI World
    /// does not provide one.
    static func now(fallback: Date) -> Date {
        guard let epoch = FixtureDatasetStore.scenarioContext()?.reviewClock?.frozenEpoch else {
            return fallback
        }
        return Date(timeIntervalSince1970: TimeInterval(epoch))
    }

    private static func parseISO8601(_ value: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.date(from: value)
            ?? {
                formatter.formatOptions = [.withInternetDateTime]
                return formatter.date(from: value)
            }()
    }
}
#endif
