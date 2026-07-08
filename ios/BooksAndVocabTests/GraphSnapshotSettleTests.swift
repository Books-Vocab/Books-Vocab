//
//  GraphSnapshotSettleTests.swift
//  Books & Vocab Tests
//
//  Pins the JS contract of `settleGraphForSnapshot()` in graph.html — the
//  catalog snapshot pipeline (CatalogGraphSnapshotFreezer) relies on it to run
//  the d3 force simulation to convergence *synchronously* and *reproducibly*
//  before rasterizing the WKWebView. Without this contract the catalog PNG for
//  Knowledge Graph surfaces captures frame 0 of an async simulation — or worse,
//  nothing at all (`layer.render(in:)` cannot see out-of-process web content).
//

#if DEBUG
import Foundation
import Testing
import WebKit
@testable import BooksAndVocab

@MainActor
struct GraphSnapshotSettleTests {
    private static let initPayload = """
    {"nodes":[\
    {"id":"a","word":"subtle","tier":"gradient","color":"#33AA55","ratio":0.2,"degree":2},\
    {"id":"b","word":"nuance","tier":"gradient","color":"#AA3355","ratio":2.0,"degree":2},\
    {"id":"c","word":"precise","tier":"gradient","color":"#5533AA","ratio":0.7,"degree":2}],\
    "links":[\
    {"id":"e1","source":"a","target":"b","kind":"contrasts_with"},\
    {"id":"e2","source":"b","target":"c","kind":"shares_usage"}],\
    "forces":{"repel":300,"linkDistance":120,"linkStrength":0.6,"centerStrength":0.07,\
    "baseNodeRadius":4.2,"collideRadius":6.3,"linkThickness":1.1},\
    "theme":{"mode":"dark","background":"transparent",\
    "colors":{"gray":{"dark":"#888888","light":"#888888"}},\
    "edges":{"contrasts_with":"#777777","shares_usage":"#777777"},\
    "label":"#FFFFFF","labelShadow":"#000000"}}
    """

    private struct JSError: Error, CustomStringConvertible {
        let description: String
    }

    private func makeGraphWebView() throws -> WKWebView {
        let webView = WKWebView(frame: CGRect(x: 0, y: 0, width: 390, height: 844))
        guard let htmlURL = Bundle.main.url(forResource: "graph", withExtension: "html") else {
            throw JSError(description: "graph.html missing from host app bundle")
        }
        webView.loadFileURL(htmlURL, allowingReadAccessTo: htmlURL.deletingLastPathComponent())
        return webView
    }

    /// Completion-handler evaluate wrapped for concurrency — the native async
    /// overload traps on `nil` (undefined) JS results, which we need to allow.
    private func evaluate(_ script: String, in webView: WKWebView) async throws -> Any? {
        try await withCheckedThrowingContinuation { continuation in
            webView.evaluateJavaScript(script) { result, error in
                if let error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume(returning: result)
                }
            }
        }
    }

    private func waitForGraphRuntime(in webView: WKWebView) async throws {
        for _ in 0..<200 {
            let loaded = try? await evaluate(
                "typeof window.initGraph === 'function' && typeof d3 !== 'undefined'",
                in: webView
            )
            if loaded as? Bool == true { return }
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        throw JSError(description: "graph.html runtime did not become ready within 10s")
    }

    private func settledPositions(in webView: WKWebView) async throws -> String {
        let settled = try await evaluate("settleGraphForSnapshot()", in: webView)
        #expect(settled as? Bool == true, "settleGraphForSnapshot must report success")

        let alphaConverged = try await evaluate("sim.alpha() <= sim.alphaMin()", in: webView)
        #expect(alphaConverged as? Bool == true, "simulation must be fully converged after settle")

        guard
            let positions = try await evaluate(
                "JSON.stringify(nodes.map(n => [n.id, Math.round(n.x * 100), Math.round(n.y * 100)]))",
                in: webView
            ) as? String
        else {
            throw JSError(description: "settled node positions unreadable")
        }
        return positions
    }

    @Test func settleGraphForSnapshotConvergesSynchronouslyAndDeterministically() async throws {
        let webView = try makeGraphWebView()
        try await waitForGraphRuntime(in: webView)

        _ = try await evaluate("initGraph('\(Self.initPayload.jsSingleQuoteEscaped)')", in: webView)

        let first = try await settledPositions(in: webView)

        // Positions must be finite and mutually distinct (repel + link forces
        // pull a 3-node chain apart) — a frame-0 capture would leave nodes
        // stacked near the spawn origin.
        let allFinite = try await evaluate(
            "nodes.every(n => Number.isFinite(n.x) && Number.isFinite(n.y))",
            in: webView
        )
        #expect(allFinite as? Bool == true)
        let spread = try await evaluate(
            "Math.hypot(nodes[0].x - nodes[1].x, nodes[0].y - nodes[1].y) > 20",
            in: webView
        )
        #expect(spread as? Bool == true, "settled nodes must be spread apart, not stacked at spawn")

        // Re-settling the same graph must reproduce byte-identical positions —
        // catalog snapshots are diffed across runs, so layout must not depend
        // on Math.random spawn state.
        let second = try await settledPositions(in: webView)
        #expect(first == second, "settle must be deterministic across repeated runs")
    }
}
#endif
