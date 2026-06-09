//
//  PerfLog.swift
//  Books & Vocab
//
//  App-wide performance observability — PERMANENT infrastructure, reused across
//  optimizations (NOT throwaway diagnostic code). Supersedes the temporary
//  PodcastPerfLog.
//
//  Three industry-standard signals behind one ergonomic facade:
//    1. os.Logger per category  — filter in Console.app / Xcode by subsystem
//       "<bundleId>.perf" + category (render / layout / scroll / underline / …).
//    2. OSSignposter intervals  — colored spans on Instruments' os_signpost /
//       Points-of-Interest track for begin/end timing of expensive work.
//    3. Rate counters           — per-frame events are counted and summarized as
//       a per-second rate so the console never floods.
//
//  ── RELEASE: (near-)zero overhead ───────────────────────────────────────────
//  Messages are @autoclosure (lazy interpolation) and every entry point is
//  @inline(__always). `tick` is FULLY behind #if DEBUG → in optimized
//  (whole-module) RELEASE the unused closure is dead-code-eliminated and the call
//  site compiles to nothing (no atomics, no lock, no string work). `mark` and
//  `measure`/`interval` keep a RELEASE path guarded by `signpostsEnabled` (a
//  runtime bool, default false) so Instruments can profile a RELEASE build via
//  KG_PERF_SIGNPOST=1; when off, `mark` is a single bool load + branch and the
//  detail autoclosure is still DCE'd. `measure` always returns the elapsed ms
//  (so callers compile) but logs/signposts only when enabled.
//
//  ── Thread-safety ───────────────────────────────────────────────────────────
//  os.Logger / OSSignposter are thread-safe. The only mutable shared state is the
//  rate-counter dictionary, guarded by OSAllocatedUnfairLock (same pattern as
//  LocaleAwareFormatter), so tick() is correct from ANY thread/actor — Layout
//  protocol sizeThatFits/placeSubviews, the underline TimelineView, and main-actor
//  view bodies.
//  measure()/interval() keep all timing state on the stack → reentrant.
//
//  ── Runtime toggle (no recompile) ───────────────────────────────────────────
//  Xcode scheme ▸ Run ▸ Arguments ▸ Environment Variables:
//    KG_PERF_LOG=all                 (DEBUG default when unset)
//    KG_PERF_LOG=off
//    KG_PERF_LOG=underline,layout    (comma list of PerfCategory rawValues)
//    KG_PERF_SIGNPOST=1              (force signposts in a RELEASE build for
//                                     Instruments; console output stays suppressed)
//

import Foundation
import os
#if canImport(QuartzCore)
import QuartzCore
#endif

/// App-wide perf categories. `rawValue` is the Console/Xcode category string and
/// the `KG_PERF_LOG` token. Add cases as new subsystems get instrumented.
enum PerfCategory: String, CaseIterable, Sendable {
    case render      // SwiftUI body re-eval / token-tree builds
    case layout      // Layout protocol sizeThatFits / placeSubviews
    case scroll      // ScrollViewReader / follow-engine timing
    case underline   // per-frame continuous-underline TimelineView ticks
    case audio       // playback clock / anchor projection / engine
    case sync        // backend sync lifecycle timing
    case reader      // Readium navigator / highlight render timing
    case startup     // cold-launch / bootstrap spans
    case review      // today-review flip → submit → prewarm → next-card render timing
    case general     // uncategorized ad-hoc measurements
}

enum PerfLog {
    static let render    = PerfChannel(.render)
    static let layout    = PerfChannel(.layout)
    static let scroll    = PerfChannel(.scroll)
    static let underline = PerfChannel(.underline)
    static let audio     = PerfChannel(.audio)
    static let sync      = PerfChannel(.sync)
    static let reader    = PerfChannel(.reader)
    static let startup   = PerfChannel(.startup)
    static let review    = PerfChannel(.review)
    static let general   = PerfChannel(.general)

    /// Perf signals get their own subsystem suffix so they isolate cleanly from
    /// AppLog in Console.app / Instruments, while staying under the app bundle id.
    static let subsystem = (Bundle.main.bundleIdentifier ?? "com.wordnexus.BooksBrowser") + ".perf"

    /// Signposts: DEBUG by default; RELEASE only when KG_PERF_SIGNPOST=1
    /// (Instruments reads signposts even when console output is suppressed).
    static let signpostsEnabled: Bool = {
        #if DEBUG
        return true
        #else
        return ProcessInfo.processInfo.environment["KG_PERF_SIGNPOST"] == "1"
        #endif
    }()

    #if DEBUG
    /// Debug-menu live override (no relaunch). nil ⇒ KG_PERF_LOG env baseline.
    /// Benignly racy by design — worst case one stale frame of logging.
    nonisolated(unsafe) static var runtimeCategories: Set<PerfCategory>?

    /// Parsed once from KG_PERF_LOG; immutable ⇒ free to read concurrently.
    static let envCategories: Set<PerfCategory> = {
        guard let raw = ProcessInfo.processInfo.environment["KG_PERF_LOG"]?.lowercased() else {
            return Set(PerfCategory.allCases)   // DEBUG default: all on
        }
        if raw == "off" || raw == "none" { return [] }
        if raw == "all" { return Set(PerfCategory.allCases) }
        let tokens = raw.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
        return Set(tokens.compactMap(PerfCategory.init(rawValue:)))
    }()

    static func isEnabled(_ cat: PerfCategory) -> Bool {
        (runtimeCategories ?? envCategories).contains(cat)
    }
    #endif
}

/// One category's logger + shared signposter + (DEBUG) lock-protected rate
/// counters. `@unchecked Sendable`: os.Logger / OSSignposter are thread-safe and
/// the rate dictionary is behind an OSAllocatedUnfairLock.
final class PerfChannel: @unchecked Sendable {
    let category: PerfCategory
    let log: Logger
    let signposter: OSSignposter

    #if DEBUG
    private struct RateState {
        var counts: [String: Int] = [:]
        var lastDetail: [String: String] = [:]
        var windowStart: DispatchTime = .now()
    }
    private let rate = OSAllocatedUnfairLock(initialState: RateState())
    private static let flushSeconds: Double = 1.0
    /// Last `mark()` payload, used as a render breadcrumb: when a FrameSampler records
    /// a new worst gap it snapshots this, so a hitchy frame is attributed to whatever
    /// view marked just before/during it (e.g. `compose.active` vs `stack.preview`).
    /// Main-thread only in practice (marks + CADisplayLink both on main); benignly racy.
    nonisolated(unsafe) static var lastBreadcrumb: String = ""
    /// Active CADisplayLink frame samplers keyed by label. Lets a caller bracket a
    /// window (a fling, a scroll) and get the real per-frame cadence the main thread
    /// produced — something SwiftUI body-eval marks miss, because Core Animation
    /// interpolates modifiers (offset/opacity) at the render layer without re-running
    /// the body each frame. Summary on stop: frames / dur / fps / maxGap / stalls.
    private let frameSamplers = OSAllocatedUnfairLock(initialState: [String: FrameSampler]())
    #endif

    init(_ category: PerfCategory) {
        self.category = category
        let l = Logger(subsystem: PerfLog.subsystem, category: category.rawValue)
        self.log = l
        self.signposter = OSSignposter(logger: l)
    }

    /// Count a high-frequency event; a per-second rate summary is flushed via
    /// `Logger.debug`. `label` MUST be a stable literal so dynamic values (n=3 /
    /// n=4) aggregate into ONE bucket — put the dynamic part in `detail`, sampled
    /// lazily only into the periodic summary line.
    @inline(__always)
    func tick(_ label: StaticString, _ detail: @autoclosure () -> String = "") {
        #if DEBUG
        guard PerfLog.isEnabled(category) else { return }
        emitTick(label.description, detail())
        #endif
    }

    /// One-shot timestamped event: a `Logger.debug` line plus an Instruments
    /// signpost flag. For boundary moments (a body eval, a scroll commit).
    @inline(__always)
    func mark(_ label: StaticString, _ detail: @autoclosure () -> String = "") {
        #if DEBUG
        guard PerfLog.isEnabled(category) else { return }
        let d = detail()
        PerfChannel.lastBreadcrumb = d.isEmpty ? label.description : "\(label.description) \(d)"
        if PerfLog.signpostsEnabled { signposter.emitEvent(label, "\(d, privacy: .public)") }
        if d.isEmpty { log.debug("\(label)") } else { log.debug("\(label) \(d, privacy: .public)") }
        #else
        if PerfLog.signpostsEnabled { signposter.emitEvent(label) }
        #endif
    }

    /// Wrap `body` in a signpost interval, log the elapsed ms, and return both the
    /// body's result and the measured ms. In RELEASE the body still runs and ms is
    /// still returned (callers compile), but logging/signposts are skipped unless
    /// KG_PERF_SIGNPOST=1.
    @discardableResult
    @inline(__always)
    func measure<T>(
        _ name: StaticString,
        _ detail: @autoclosure () -> String = "",
        _ body: () throws -> T
    ) rethrows -> (value: T, ms: Double) {
        guard emitEnabled else {
            let start = DispatchTime.now()
            let value = try body()
            return (value, Self.ms(since: start))
        }
        let state = signposter.beginInterval(name, id: signposter.makeSignpostID())
        let start = DispatchTime.now()
        defer { signposter.endInterval(name, state) }
        let value = try body()
        let ms = Self.ms(since: start)
        logInterval(name, ms: ms, detail: detail())
        return (value, ms)
    }

    /// RAII span for non-closure scopes (begin in onAppear, end in onDisappear).
    /// `span.end()` closes the signpost, logs ms, and returns it; auto-ends on
    /// dealloc so a dropped handle never leaks an open interval.
    @inline(__always)
    func interval(_ name: StaticString) -> PerfSpan {
        guard emitEnabled else { return PerfSpan() }
        let state = signposter.beginInterval(name, id: signposter.makeSignpostID())
        return PerfSpan(channel: self, name: name, state: state)
    }

    // MARK: - internals (shared by measure / interval / PerfSpan)

    var emitEnabled: Bool {
        #if DEBUG
        return PerfLog.signpostsEnabled || PerfLog.isEnabled(category)
        #else
        return PerfLog.signpostsEnabled
        #endif
    }

    func logInterval(_ name: StaticString, ms: Double, detail: String) {
        #if DEBUG
        guard PerfLog.isEnabled(category) else { return }
        if detail.isEmpty {
            log.debug("\(name) \(ms, format: .fixed(precision: 2))ms")
        } else {
            log.debug("\(name) \(detail, privacy: .public) \(ms, format: .fixed(precision: 2))ms")
        }
        #endif
    }

    func endSignpost(_ name: StaticString, _ state: OSSignpostIntervalState) {
        signposter.endInterval(name, state)
    }

    static func ms(since start: DispatchTime) -> Double {
        Double(DispatchTime.now().uptimeNanoseconds &- start.uptimeNanoseconds) / 1_000_000
    }

    #if DEBUG
    private func emitTick(_ key: String, _ detail: String) {
        let summary: String? = rate.withLock { st in
            st.counts[key, default: 0] += 1
            if !detail.isEmpty { st.lastDetail[key] = detail }
            let now = DispatchTime.now()
            let elapsed = Double(now.uptimeNanoseconds &- st.windowStart.uptimeNanoseconds) / 1_000_000_000
            guard elapsed >= Self.flushSeconds else { return nil }
            let secs = max(elapsed, .leastNonzeroMagnitude)
            let line = st.counts.map { k, v -> String in
                let r = "\(Int(Double(v) / secs))/s"
                if let d = st.lastDetail[k], !d.isEmpty { return "\(k)(\(d))=\(r)" }
                return "\(k)=\(r)"
            }.sorted().joined(separator: "  ")
            st.counts.removeAll(keepingCapacity: true)
            st.lastDetail.removeAll(keepingCapacity: true)
            st.windowStart = now
            return line
        }
        if let summary { log.debug("rate \(summary, privacy: .public)") }
    }

    /// CADisplayLink-backed per-frame cadence recorder. Created on start, retained by
    /// the run loop until invalidated on stop. NSObject for the @objc selector target.
    final class FrameSampler: NSObject {
        private var link: CADisplayLink?
        private let log: Logger
        private let label: String
        private let start = DispatchTime.now()
        private var lastFrame: DispatchTime
        private var frames = 0
        private var maxGapMs: Double = 0
        private var maxGapAtMs: Double = 0   // ms-since-start of the worst gap → pins the freeze to the timeline
        private var maxGapCrumb = ""         // PerfChannel.lastBreadcrumb at the worst gap → names the culprit render
        private var stalls = 0   // inter-frame gaps > 33ms (≈ a dropped frame at 60fps)

        init(log: Logger, label: String) {
            self.log = log
            self.label = label
            self.lastFrame = .now()
            super.init()
            let dl = CADisplayLink(target: self, selector: #selector(onFrame))
            dl.add(to: .main, forMode: .common)
            self.link = dl
        }

        @objc private func onFrame() {
            let now = DispatchTime.now()
            let gapMs = Double(now.uptimeNanoseconds &- lastFrame.uptimeNanoseconds) / 1_000_000
            lastFrame = now
            frames += 1
            if frames > 1 {   // first callback's gap includes setup latency — skip it
                if gapMs > maxGapMs {
                    maxGapMs = gapMs
                    maxGapAtMs = Double(now.uptimeNanoseconds &- start.uptimeNanoseconds) / 1_000_000
                    maxGapCrumb = PerfChannel.lastBreadcrumb
                }
                if gapMs > 33 { stalls += 1 }
            }
        }

        func stop() {
            link?.invalidate()
            link = nil
            let totalMs = Double(DispatchTime.now().uptimeNanoseconds &- start.uptimeNanoseconds) / 1_000_000
            let fps = totalMs > 0 ? Double(frames) / (totalMs / 1000) : 0
            log.debug("\(self.label).summary frames=\(self.frames) dur=\(totalMs, format: .fixed(precision: 1))ms fps=\(fps, format: .fixed(precision: 0)) maxGap=\(self.maxGapMs, format: .fixed(precision: 1))ms maxGapAt=\(self.maxGapAtMs, format: .fixed(precision: 1))ms stalls=\(self.stalls) after=[\(self.maxGapCrumb, privacy: .public)]")
        }
    }
    #endif

    /// Begin a per-frame cadence sample under `label`; pair with `stopFrameSampler`.
    /// DEBUG + main-thread only (CADisplayLink lives on the main run loop); a no-op in
    /// RELEASE and when the category is disabled. Re-starting an active label restarts.
    func startFrameSampler(_ label: String) {
        #if DEBUG
        guard PerfLog.isEnabled(category) else { return }
        frameSamplers.withLock { samplers in
            samplers[label]?.stop()
            samplers[label] = FrameSampler(log: log, label: label)
        }
        #endif
    }

    /// End the `label` sample and emit its summary line. Idempotent.
    func stopFrameSampler(_ label: String) {
        #if DEBUG
        frameSamplers.withLock { samplers in
            samplers[label]?.stop()
            samplers[label] = nil
        }
        #endif
    }
}

/// Handle returned by `PerfChannel.interval`. `end()` closes the signpost, logs
/// the elapsed ms, and returns it. Idempotent; auto-ends on dealloc so a dropped
/// handle never leaks an open signpost interval.
struct PerfSpan {
    private final class Token {
        let channel: PerfChannel
        let name: StaticString
        let state: OSSignpostIntervalState
        let start = DispatchTime.now()
        var closed = false
        init(_ c: PerfChannel, _ n: StaticString, _ s: OSSignpostIntervalState) {
            channel = c; name = n; state = s
        }
        @discardableResult func close(_ detail: String) -> Double {
            guard !closed else { return 0 }
            closed = true
            let ms = PerfChannel.ms(since: start)
            channel.endSignpost(name, state)
            channel.logInterval(name, ms: ms, detail: detail)
            return ms
        }
        deinit { close("") }   // safety net: dropped handle still closes the span
    }

    private let token: Token?
    init() { token = nil }
    init(channel: PerfChannel, name: StaticString, state: OSSignpostIntervalState) {
        token = Token(channel, name, state)
    }

    @discardableResult
    func end(_ detail: @autoclosure () -> String = "") -> Double {
        guard let token else { return 0 }
        return token.close(detail())
    }
}
