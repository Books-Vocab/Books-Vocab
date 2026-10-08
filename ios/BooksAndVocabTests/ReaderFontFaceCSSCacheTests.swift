//
//  ReaderFontFaceCSSCacheTests.swift
//  Books & Vocab Tests
//
//  Issue #2052: the Readium `setupUserScripts` delegate used to build the ~4.5 MB
//  base64 `@font-face` CSS (16 × `Data(contentsOf:)`) synchronously on the main
//  thread the first time a book opened. The build now happens in a detached
//  `.utility` prewarm; the delegate path only reads the cached value.
//

#if os(iOS)
import Foundation
import Testing
@testable import BooksAndVocab

/// Thread-safe recorder for the injected loader (it runs off the main thread).
private final class LoaderProbe: @unchecked Sendable {
    private let lock = NSLock()
    private var _calls: [String] = []
    private var _mainThreadCalls = 0

    var calls: [String] { lock.withLock { _calls } }
    var count: Int { lock.withLock { _calls.count } }
    var mainThreadCalls: Int { lock.withLock { _mainThreadCalls } }

    func loader(missing: Set<String> = []) -> ReaderFontFaceCSSCache.Loader {
        { [self] resource in
            lock.withLock {
                _calls.append(resource)
                if Thread.isMainThread { _mainThreadCalls += 1 }
            }
            return missing.contains(resource) ? nil : Data(resource.utf8)
        }
    }
}

struct ReaderFontFaceCSSCacheTests {

    private static let fontCount = ReaderFontFaceCSSCache.fontDefinitions.count

    @Test func catalogCoversFourFamiliesInFourFaces() {
        #expect(Self.fontCount == 16)
        #expect(Set(ReaderFontFaceCSSCache.fontDefinitions.map(\.family)).count == 4)
    }

    /// Reading before any warm-up is a pure read: no loader traffic at all.
    @Test func coldPeekNeverTouchesLoader() {
        let probe = LoaderProbe()
        let cache = ReaderFontFaceCSSCache(loader: probe.loader())
        #expect(cache.cachedCSS() == nil)
        #expect(probe.count == 0)
    }

    /// The prewarm builds all faces, and never on the main thread.
    @Test @MainActor func prewarmBuildsAllFacesOffMainThread() async {
        let probe = LoaderProbe()
        let cache = ReaderFontFaceCSSCache(loader: probe.loader())
        #expect(Thread.isMainThread)

        await cache.prewarm().value

        #expect(probe.count == Self.fontCount)
        #expect(probe.mainThreadCalls == 0)
        let css = cache.cachedCSS()
        #expect(css != nil)
        #expect(css?.components(separatedBy: "@font-face").count == Self.fontCount + 1)
        #expect(css?.contains("font-family: 'Crimson Pro'") == true)
        #expect(css?.contains("base64,\(Data("CrimsonPro-Regular".utf8).base64EncodedString())") == true)
    }

    /// The delegate path after warm-up must be a pure cache read:
    /// zero further `Data(contentsOf:)` (loader) calls, however often it runs.
    @Test @MainActor func delegatePathAfterPrewarmDoesNotLoadAnything() async {
        let probe = LoaderProbe()
        let cache = ReaderFontFaceCSSCache(loader: probe.loader())
        await cache.prewarm().value
        let callsAfterWarm = probe.count

        for _ in 0..<5 { _ = cache.css() }

        #expect(probe.count == callsAfterWarm)
        #expect(probe.mainThreadCalls == 0)
    }

    @Test @MainActor func prewarmIsIdempotent() async {
        let probe = LoaderProbe()
        let cache = ReaderFontFaceCSSCache(loader: probe.loader())
        let first = cache.prewarm()
        let second = cache.prewarm()
        await first.value
        await second.value
        _ = cache.prewarm()

        #expect(probe.count == Self.fontCount)
    }

    /// Safety net: if the delegate fires before the prewarm finished it must
    /// still return correct CSS (and build only once), never an empty string.
    @Test @MainActor func coldDelegateFallsBackToCorrectCSSAndCachesIt() {
        let probe = LoaderProbe()
        let cache = ReaderFontFaceCSSCache(loader: probe.loader())

        let css = cache.css()

        #expect(css.components(separatedBy: "@font-face").count == Self.fontCount + 1)
        #expect(probe.count == Self.fontCount)
        _ = cache.css()
        #expect(probe.count == Self.fontCount)
        #expect(cache.cachedCSS() == css)
    }

    /// A missing bundle resource skips only that face.
    @Test @MainActor func missingResourceSkipsOnlyThatFace() async {
        let probe = LoaderProbe()
        let cache = ReaderFontFaceCSSCache(loader: probe.loader(missing: ["SpaceMono-Bold"]))
        await cache.prewarm().value
        let css = cache.cachedCSS() ?? ""
        #expect(css.components(separatedBy: "@font-face").count == Self.fontCount)
        #expect(!css.contains(Data("SpaceMono-Bold".utf8).base64EncodedString()))
    }

    /// The real bundle loader resolves every shipped TTF (guards a renamed/removed font).
    @Test @MainActor func bundleLoaderResolvesEveryShippedFont() async {
        let cache = ReaderFontFaceCSSCache(loader: ReaderFontFaceCSSCache.bundleLoader)
        await cache.prewarm().value
        let css = cache.cachedCSS() ?? ""
        #expect(css.components(separatedBy: "@font-face").count == Self.fontCount + 1)
        #expect(css.utf8.count > 1_000_000)
    }
}
#endif
