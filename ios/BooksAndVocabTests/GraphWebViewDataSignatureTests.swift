#if os(iOS)
import Foundation
import Testing
@testable import BooksAndVocab

/// Pins `GraphWebView.dataSignature` — the content diff that decides whether
/// `updateWebView` re-sends the graph payload (which resets the d3 layout).
///
/// The signature MUST be stable while nothing visually changed, otherwise every
/// SwiftUI `body` recomputation forces a spurious redraw + layout reset. The
/// landmine is `node.ratio`: it derives from `Date()` in
/// `KnowledgeGraphPresentation.reviewRatio`, so it drifts continuously. These
/// tests lock down that ratio drift does NOT move the signature, while a genuine
/// review color change (`colorHex`) DOES — mirroring `GraphThumbnailWebView`.
struct GraphWebViewDataSignatureTests {

    private func node(
        id: String,
        tier: String? = "gradient",
        colorHex: String? = "#AABBCC",
        ratio: Double?,
        degree: Int = 2
    ) -> KnowledgeGraphNode {
        KnowledgeGraphNode(id: id, word: id, tier: tier, colorHex: colorHex, ratio: ratio, degree: degree)
    }

    private func edge(_ id: String, from: String, to: String, kind: String = "related") -> KnowledgeGraphEdge {
        KnowledgeGraphEdge(id: id, from: from, to: to, kind: kind)
    }

    // MARK: - Stability invariant: ratio drift must not move the signature

    @Test func ratioDrift_doesNotChangeSignature() {
        // Same node identity/tier/color/degree, only `ratio` differs (as it would
        // between two `body` recomputations seconds apart). Color is held constant
        // because in production colorHex is quantized from ratio; here we isolate
        // the raw-ratio leak the old `%.4f` formatting failed to contain.
        let early = [node(id: "n1", ratio: 0.5000)]
        let drifted = [node(id: "n1", ratio: 0.5042)] // ~5s of SRS drift under the 6h floor
        let edges = [edge("e1", from: "n1", to: "n2")]

        let sigA = GraphWebView.dataSignature(nodes: early, edges: edges)
        let sigB = GraphWebView.dataSignature(nodes: drifted, edges: edges)

        #expect(sigA == sigB, "raw ratio drift must not force a redraw — it would reset the d3 layout every few seconds")
    }

    @Test func largeRatioGap_sameColor_doesNotChangeSignature() {
        // Even a big ratio gap (minutes) is irrelevant as long as the quantized
        // color did not change — colorHex is the source of truth for visual state.
        let a = [node(id: "n1", ratio: 0.10)]
        let b = [node(id: "n1", ratio: 0.90)]
        let edges = [edge("e1", from: "n1", to: "n2")]

        #expect(
            GraphWebView.dataSignature(nodes: a, edges: edges)
                == GraphWebView.dataSignature(nodes: b, edges: edges),
            "with colorHex held constant, ratio alone must never move the signature"
        )
    }

    // MARK: - Sensitivity invariant: real visual changes still trigger a redraw

    @Test func colorChange_changesSignature() {
        // A review that shifts the gradient changes colorHex (cssHex quantization),
        // which MUST still flip the signature so the graph repaints.
        let before = [node(id: "n1", colorHex: "#112233", ratio: 0.3)]
        let after = [node(id: "n1", colorHex: "#445566", ratio: 0.3)]
        let edges = [edge("e1", from: "n1", to: "n2")]

        #expect(
            GraphWebView.dataSignature(nodes: before, edges: edges)
                != GraphWebView.dataSignature(nodes: after, edges: edges),
            "a color change (review repaint) must change the signature so the graph redraws"
        )
    }

    @Test func tierChange_changesSignature() {
        // First review: gray (unreviewed) → gradient. colorHex also moves nil→hex.
        let unreviewed = [node(id: "n1", tier: "gray", colorHex: nil, ratio: nil)]
        let reviewed = [node(id: "n1", tier: "gradient", colorHex: "#AABBCC", ratio: 0.5)]
        let edges = [edge("e1", from: "n1", to: "n2")]

        #expect(
            GraphWebView.dataSignature(nodes: unreviewed, edges: edges)
                != GraphWebView.dataSignature(nodes: reviewed, edges: edges),
            "first review (gray→gradient) must change the signature"
        )
    }

    @Test func degreeChange_changesSignature() {
        let before = [node(id: "n1", ratio: 0.5, degree: 1)]
        let after = [node(id: "n1", ratio: 0.5, degree: 3)]
        let edges = [edge("e1", from: "n1", to: "n2")]

        #expect(
            GraphWebView.dataSignature(nodes: before, edges: edges)
                != GraphWebView.dataSignature(nodes: after, edges: edges),
            "degree (node radius) is a visual feature — its change must redraw"
        )
    }

    @Test func edgeChange_changesSignature() {
        let nodes = [node(id: "n1", ratio: 0.5)]
        let before = [edge("e1", from: "n1", to: "n2", kind: "related")]
        let after = [edge("e1", from: "n1", to: "n2", kind: "synonym")]

        #expect(
            GraphWebView.dataSignature(nodes: nodes, edges: before)
                != GraphWebView.dataSignature(nodes: nodes, edges: after),
            "edge kind drives stroke color — its change must redraw"
        )
    }

    // MARK: - Identity invariant: identical input is byte-stable

    @Test func identicalInput_isStable() {
        let nodes = [node(id: "n1", ratio: 0.5), node(id: "n2", ratio: 0.2)]
        let edges = [edge("e1", from: "n1", to: "n2")]

        #expect(
            GraphWebView.dataSignature(nodes: nodes, edges: edges)
                == GraphWebView.dataSignature(nodes: nodes, edges: edges),
            "identical input must produce an identical signature"
        )
    }
}
#endif
