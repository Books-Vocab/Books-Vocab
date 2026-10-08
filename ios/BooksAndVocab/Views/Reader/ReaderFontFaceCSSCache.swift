#if os(iOS)
import Foundation
import os

/// Process-wide cache of the bundled reader `@font-face` CSS (16 TTF, ~3.4 MB → ~4.5 MB base64).
///
/// The fonts are bundled resources that never change at runtime, so the CSS is built
/// once. Building it costs 16 × `Data(contentsOf:)` + base64, which must never happen
/// on the main thread: the Readium `setupUserScripts` delegate (main thread) used to
/// pay it synchronously on first book open (issue #2052).
///
/// - `prewarm()` builds off-main in a detached `.utility` task (call it early; idempotent).
/// - `cachedCSS()` is a non-blocking read.
/// - `css()` is the delegate-path accessor: a pure cache read once warmed. If the delegate
///   ever wins the race against the prewarm it falls back to a single-flight synchronous
///   build (correctness over speed; logged) so the page never loses its fonts.
final class ReaderFontFaceCSSCache: @unchecked Sendable {
    /// Loads the raw TTF bytes for a bundle resource stem (e.g. `CrimsonPro-Regular`).
    /// Injected so tests can prove when — and on which thread — file IO happens.
    typealias Loader = @Sendable (_ resource: String) -> Data?

    struct FontDefinition: Sendable {
        let file: String
        let family: String
        let weight: String
        let style: String
    }

    static let fontDefinitions: [FontDefinition] = [
        .init(file: "CormorantGaramond-Regular", family: "Cormorant Garamond", weight: "normal", style: "normal"),
        .init(file: "CormorantGaramond-Bold", family: "Cormorant Garamond", weight: "bold", style: "normal"),
        .init(file: "CormorantGaramond-Italic", family: "Cormorant Garamond", weight: "normal", style: "italic"),
        .init(file: "CormorantGaramond-BoldItalic", family: "Cormorant Garamond", weight: "bold", style: "italic"),
        .init(file: "CrimsonPro-Regular", family: "Crimson Pro", weight: "normal", style: "normal"),
        .init(file: "CrimsonPro-Bold", family: "Crimson Pro", weight: "bold", style: "normal"),
        .init(file: "CrimsonPro-Italic", family: "Crimson Pro", weight: "normal", style: "italic"),
        .init(file: "CrimsonPro-BoldItalic", family: "Crimson Pro", weight: "bold", style: "italic"),
        .init(file: "ElmsSans-Regular", family: "Elms Sans", weight: "normal", style: "normal"),
        .init(file: "ElmsSans-Bold", family: "Elms Sans", weight: "bold", style: "normal"),
        .init(file: "ElmsSans-Italic", family: "Elms Sans", weight: "normal", style: "italic"),
        .init(file: "ElmsSans-BoldItalic", family: "Elms Sans", weight: "bold", style: "italic"),
        .init(file: "SpaceMono-Regular", family: "Space Mono", weight: "normal", style: "normal"),
        .init(file: "SpaceMono-Bold", family: "Space Mono", weight: "bold", style: "normal"),
        .init(file: "SpaceMono-Italic", family: "Space Mono", weight: "normal", style: "italic"),
        .init(file: "SpaceMono-BoldItalic", family: "Space Mono", weight: "bold", style: "italic"),
    ]

    static let bundleLoader: Loader = { resource in
        guard let url = Bundle.main.url(forResource: resource, withExtension: "ttf") else { return nil }
        return try? Data(contentsOf: url)
    }

    static let shared = ReaderFontFaceCSSCache()

    private let loader: Loader
    /// Guards `built` and `prewarmTask` (short critical sections only).
    private let stateLock = NSLock()
    private var built: String?
    private var prewarmTask: Task<Void, Never>?
    /// Serialises the (long) build so a prewarm and a cold delegate never both do the IO.
    private let buildLock = NSLock()

    init(loader: @escaping Loader = ReaderFontFaceCSSCache.bundleLoader) {
        self.loader = loader
    }

    /// Non-blocking read of the already-built CSS; nil when not warmed yet.
    func cachedCSS() -> String? {
        stateLock.withLock { built }
    }

    /// Builds the CSS in a detached `.utility` task. Idempotent: repeated calls return
    /// the same task, and an already-built cache returns an already-finished task.
    @discardableResult
    func prewarm() -> Task<Void, Never> {
        stateLock.withLock {
            if let prewarmTask { return prewarmTask }
            let task: Task<Void, Never>
            if built != nil {
                task = Task {}
            } else {
                task = Task.detached(priority: .utility) { [self] in
                    _ = buildIfNeeded()
                }
            }
            prewarmTask = task
            return task
        }
    }

    /// Delegate-path accessor: cached value when warm (no IO). Cold fallback builds
    /// synchronously, once, and logs — it should only occur if nothing prewarmed first.
    func css() -> String {
        if let cached = cachedCSS() { return cached }
        AppLog.reader.warning("Reader font CSS requested before prewarm finished; building synchronously")
        PerfLog.reader.mark("fontCSS.coldFallback")
        return buildIfNeeded()
    }

    private func buildIfNeeded() -> String {
        buildLock.lock()
        defer { buildLock.unlock() }
        if let cached = cachedCSS() { return cached }
        let span = PerfLog.reader.interval("fontFaceCSS.build")
        let rendered = Self.render(loader: loader)
        span.end()
        stateLock.withLock { built = rendered }
        return rendered
    }

    private static func render(loader: Loader) -> String {
        var css = ""
        for def in fontDefinitions {
            guard let data = loader(def.file) else {
                AppLog.reader.warning("Font not found in bundle: \(def.file).ttf")
                continue
            }
            let b64 = data.base64EncodedString()
            css += """
            @font-face {
                font-family: '\(def.family)';
                font-weight: \(def.weight);
                font-style: \(def.style);
                src: url('data:font/truetype;base64,\(b64)') format('truetype');
            }

            """
        }
        return css
    }
}
#endif
