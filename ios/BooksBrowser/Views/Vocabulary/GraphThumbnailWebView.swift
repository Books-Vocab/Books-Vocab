import SwiftUI
import WebKit

struct GraphThumbnailWebView: UIViewRepresentable {
    let nodes: [KnowledgeGraphNode]
    let edges: [KnowledgeGraphEdge]
    let theme: KnowledgeGraphTheme
    let colorScheme: ColorScheme

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.userContentController.add(context.coordinator, name: "graphBridge")

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.scrollView.isScrollEnabled = false
        webView.scrollView.bounces = false
        webView.scrollView.backgroundColor = .clear
        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.isUserInteractionEnabled = false
        context.coordinator.webView = webView

        guard let htmlURL = Bundle.main.url(forResource: "graph", withExtension: "html") else {
            return webView
        }
        webView.loadFileURL(htmlURL, allowingReadAccessTo: htmlURL.deletingLastPathComponent())
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        let coord = context.coordinator
        let sig = "\(colorScheme)-\(nodes.count)-\(edges.count)-\(theme.backgroundHex)"
        guard coord.lastSignature != sig else { return }
        coord.lastSignature = sig
        coord.sendInitGraph(buildPayload(), webView: webView)
    }

    static func dismantleUIView(_ webView: WKWebView, coordinator: Coordinator) {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "graphBridge")
    }

    // MARK: - Payload

    private func buildPayload() -> String {
        struct NodePayload: Encodable {
            let id: String; let word: String; let tier: String
            let color: String?; let ratio: Double?; let degree: Int
        }
        struct LinkPayload: Encodable {
            let id: String; let source: String; let target: String; let kind: String
        }
        struct TierPair: Encodable { let dark: String; let light: String }
        struct ThemePayload: Encodable {
            let mode: String; let background: String
            let colors: [String: TierPair]; let edges: [String: String]
            let label: String; let labelShadow: String
        }
        struct Payload: Encodable {
            let nodes: [NodePayload]; let links: [LinkPayload]
            let forces: GraphForces; let theme: ThemePayload; let thumbnail: Bool
        }

        let mode = colorScheme == .dark ? "dark" : "light"
        let nodePayloads = nodes.map {
            NodePayload(id: $0.id, word: $0.word, tier: $0.tier ?? "unknown",
                        color: $0.colorHex, ratio: $0.ratio, degree: $0.degree)
        }
        let linkPayloads = edges.map {
            LinkPayload(id: $0.id, source: $0.from, target: $0.to, kind: $0.kind)
        }
        let tierNames = ["gray", "archived"]
        let colorPairs = tierNames.reduce(into: [String: TierPair]()) { result, name in
            let hex = theme.tierHexes[name] ?? "#888888"
            result[name] = TierPair(dark: hex, light: hex)
        }
        let themePayload = ThemePayload(
            mode: mode, background: "transparent",
            colors: colorPairs, edges: theme.edgeHexes,
            label: theme.labelHex, labelShadow: theme.labelShadowHex
        )
        let forces = GraphForces(
            repel: 40, linkDistance: 30, linkStrength: 1.2,
            centerStrength: 0.04, baseNodeRadius: 3,
            collideRadius: 3, linkThickness: 0.8
        )
        let payload = Payload(
            nodes: nodePayloads, links: linkPayloads,
            forces: forces, theme: themePayload, thumbnail: true
        )
        guard let data = try? JSONEncoder().encode(payload),
              let json = String(data: data, encoding: .utf8) else { return "{}" }
        return json
    }

    // MARK: - Coordinator

    class Coordinator: NSObject, WKScriptMessageHandler {
        var graphBridgeReady = false
        var pendingPayload: String?
        var lastSignature: String?
        weak var webView: WKWebView?

        func sendInitGraph(_ json: String, webView: WKWebView) {
            guard graphBridgeReady else { pendingPayload = json; return }
            let escaped = json
                .replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "'", with: "\\'")
            webView.evaluateJavaScript("initGraph('\(escaped)')", completionHandler: nil)
        }

        func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
            guard message.name == "graphBridge",
                  let body = message.body as? [String: Any],
                  let type = body["type"] as? String,
                  type == "ready" else { return }
            graphBridgeReady = true
            if let pending = pendingPayload, let wv = webView {
                pendingPayload = nil
                sendInitGraph(pending, webView: wv)
            }
        }
    }
}
