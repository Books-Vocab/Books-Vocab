//
//  CatalogGraphSnapshotFreezer.swift
//  Books & Vocab
//
//  Makes WKWebView-hosted knowledge-graph content capturable by catalog
//  snapshots.
//
//  Root cause this solves (2026-07, blank Knowledge Graph catalog PNGs):
//  PlaybookSnapshot without a `keyWindow` rasterizes scenarios via
//  `CALayer.render(in:)`, which walks the *in-process* layer tree only.
//  WKWebView composites its content out-of-process (WebContent process), so
//  the graph canvas is structurally invisible to that capture — byte-identical
//  blank output on every dataset, regardless of timing. Independently, the d3
//  force layout is asynchronous, so even a screen-level capture at t≈0 would
//  show frame 0 (nodes at spawn) instead of the settled layout.
//
//  Fix: arm the scenario's `SnapshotWaiter`, and once `initGraph` has been
//  applied in the web process (`\.kgGraphWebViewInitHook` from GraphWebView),
//  run the simulation to convergence synchronously (`settleGraphForSnapshot()`
//  in graph.html — seeded PRNG, deterministic layout), ask the web process for
//  a bitmap (`takeSnapshot`), verify it is not blank, overlay it as a plain
//  `UIImageView` (in-process, capturable, inherits the SwiftUI mask/legend
//  stack), then fulfil the waiter so the snapshot proceeds.
//

#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import WebKit

@MainActor
final class CatalogGraphSnapshotFreezer {
    /// Scenarios whose content hosts a WKWebView and therefore must be
    /// captured by the async web-view pass in `CatalogSnapshotTests`, not by
    /// `Snapshot.run`. Playbook's `Snapshot.run` waits by spinning
    /// `RunLoop.run(mode:before:)` on the main thread — WebKit cannot finish
    /// launching its WebContent processes inside that loop (measured: 12
    /// processes stuck "~598s to launch", unblocking only when the loop
    /// exited), so graph web views never render there.
    ///
    /// Keep in sync: every catalog scenario wrapped in
    /// `CatalogGraphSnapshotScene` must have its `"<category>/<title>"` key
    /// listed here. A wrapped-but-unlisted scenario would fall into the main
    /// `Snapshot.run` pass, wait out its 30s waiter, and silently write a
    /// blank canvas — which is why `CatalogSnapshotTests` asserts `armedCount`
    /// stays untouched across the main pass (turning that misconfiguration
    /// into a loud failure).
    static let webViewSnapshotScenarioKeys: Set<String> = [
        "Knowledge Graph View/Populated graph",
        "Vocabulary · Knowledge Graph/With Data",
        "Vocabulary · Knowledge Graph/Settings Open",
    ]

    /// Total successful freezes (settled + rasterized + overlay installed) in
    /// this process. The catalog runner asserts this increments once per
    /// web-view scenario capture — the loud gate against silently shipping a
    /// legend-only blank canvas again.
    private(set) static var freezeCount = 0

    /// Total waiters armed in snapshot context in this process. Must stay
    /// constant across the main `Snapshot.run` pass — a change there means a
    /// `CatalogGraphSnapshotScene`-wrapped scenario is missing from
    /// `webViewSnapshotScenarioKeys` and would render a blank canvas.
    private(set) static var armedCount = 0

    private let waiter: SnapshotWaiter?
    private var frozen = false

    init(context: ScenarioContext) {
        if context.isSnapshot {
            waiter = context.snapshotWaiter
            // Ceiling covers WKWebView cold start inside the snapshot window;
            // the settle + rasterize itself completes well under a second.
            context.snapshotWaiter.wait(until: .now() + 30)
            Self.armedCount += 1
        } else {
            // Interactive catalog browsing keeps the live simulation untouched.
            waiter = nil
        }
    }

    /// Hook for `\.kgGraphWebViewInitHook`; nil outside snapshot context.
    var initGraphHook: (@MainActor (WKWebView) -> Void)? {
        guard waiter != nil else { return nil }
        return { [self] webView in freeze(webView) }
    }

    private func freeze(_ webView: WKWebView) {
        guard !frozen else { return }
        frozen = true
        webView.evaluateJavaScript("settleGraphForSnapshot()") { [self] result, error in
            precondition(
                error == nil,
                "settleGraphForSnapshot() threw in graph.html: \(String(describing: error))"
            )
            precondition(
                (result as? Bool) == true,
                "settleGraphForSnapshot() reported failure — simulation missing after initGraph?"
            )
            let configuration = WKSnapshotConfiguration()
            configuration.rect = webView.bounds
            webView.takeSnapshot(with: configuration) { [self] image, error in
                guard let image else {
                    preconditionFailure(
                        "graph WKWebView takeSnapshot failed: \(String(describing: error))"
                    )
                }
                // False-green guard: a regression back to an empty canvas must
                // fail the catalog run loudly, not ship legend-only PNGs.
                precondition(
                    Self.hasVisibleContent(image),
                    "graph WKWebView rasterized to a uniform/blank image — no nodes rendered"
                )
                let imageView = UIImageView(image: image)
                imageView.frame = webView.bounds
                imageView.autoresizingMask = [.flexibleWidth, .flexibleHeight]
                webView.addSubview(imageView)
                Self.freezeCount += 1
                waiter?.fulfill()
            }
        }
    }

    /// Nearest-neighbour downsample; content exists iff any sampled pixel
    /// differs from the first one. A blank canvas (transparent or solid theme
    /// background) is uniform; nodes/edges/labels are not.
    static func hasVisibleContent(_ image: UIImage) -> Bool {
        guard let cgImage = image.cgImage else { return false }
        let side = 64
        let bytesPerRow = side * 4
        var pixels = [UInt8](repeating: 0, count: side * bytesPerRow)
        let drawn: Bool = pixels.withUnsafeMutableBytes { buffer in
            guard let context = CGContext(
                data: buffer.baseAddress,
                width: side,
                height: side,
                bitsPerComponent: 8,
                bytesPerRow: bytesPerRow,
                space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
            ) else { return false }
            context.interpolationQuality = .none
            context.draw(cgImage, in: CGRect(x: 0, y: 0, width: side, height: side))
            return true
        }
        guard drawn else { return false }

        let tolerance = 4
        let r0 = Int(pixels[0]), g0 = Int(pixels[1]), b0 = Int(pixels[2]), a0 = Int(pixels[3])
        for offset in stride(from: 4, to: pixels.count, by: 4) {
            if abs(Int(pixels[offset]) - r0) > tolerance
                || abs(Int(pixels[offset + 1]) - g0) > tolerance
                || abs(Int(pixels[offset + 2]) - b0) > tolerance
                || abs(Int(pixels[offset + 3]) - a0) > tolerance {
                return true
            }
        }
        return false
    }
}

/// Scenario wrapper that installs the freezer around any graph-bearing
/// content. Usage in a catalog scenario:
///
///     Scenario("Populated graph", layout: .fill) { context in
///         CatalogGraphSnapshotScene(context: context) {
///             KnowledgeGraphViewScene(fixture: .populated)
///         }
///     }
struct CatalogGraphSnapshotScene<Content: View>: View {
    private let freezer: CatalogGraphSnapshotFreezer
    private let content: Content

    init(context: ScenarioContext, @ViewBuilder content: () -> Content) {
        self.freezer = CatalogGraphSnapshotFreezer(context: context)
        self.content = content()
    }

    var body: some View {
        content
            .environment(\.kgGraphWebViewInitHook, freezer.initGraphHook)
    }
}
#endif
