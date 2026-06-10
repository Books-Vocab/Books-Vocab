//
//  RenderStormProbe.swift
//  Books & Vocab
//
//  DEBUG-only diagnostic for SwiftUI body re-evaluation storms.
//  Filter Xcode console by category "RenderStorm" — emits at most one
//  throttled line per label per second, so it never floods.
//

#if DEBUG
import Foundation
import os

@MainActor
final class RenderStormProbe {
    static let shared = RenderStormProbe()

    private let log = Logger(
        subsystem: Bundle.main.bundleIdentifier ?? BrandIdentity.bundleSubsystemFallback,
        category: "RenderStorm"
    )
    private var count: [String: Int] = [:]
    private var windowStart: [String: DispatchTime] = [:]

    /// Whether to ALSO emit SwiftUI's `_printChanges()` (names the property that
    /// invalidated the view). Off by default — it can't be category-filtered and
    /// prints to stdout. Enable with env var `SETTINGS_RENDER_DEBUG=1` in the
    /// scheme when you need to pin the exact dependency.
    static let printChangesEnabled =
        ProcessInfo.processInfo.environment["SETTINGS_RENDER_DEBUG"] == "1"

    /// Call once at the top of a `body` getter. Counts evaluations and logs a
    /// throttled summary every ~1s. >5 evals/sec is flagged as a storm.
    func tick(_ label: String) {
        let now = DispatchTime.now()
        let start = windowStart[label] ?? now
        windowStart[label] = start
        count[label, default: 0] += 1
        let elapsed = Double(now.uptimeNanoseconds &- start.uptimeNanoseconds) / 1_000_000_000
        guard elapsed >= 1.0 else { return }

        let n = count[label] ?? 0
        let rate = Double(n) / elapsed
        if rate > 5 {
            log.warning("⚠️ STORM \(label, privacy: .public): \(n) evals in \(elapsed, format: .fixed(precision: 1))s (\(rate, format: .fixed(precision: 0))/s)")
        } else {
            log.debug("\(label, privacy: .public): \(n) evals in \(elapsed, format: .fixed(precision: 1))s")
        }
        count[label] = 0
        windowStart[label] = now
    }
}
#endif
