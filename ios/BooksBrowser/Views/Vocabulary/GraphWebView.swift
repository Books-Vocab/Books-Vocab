import SwiftUI
import UIKit
import WebKit

// MARK: - GraphForces

struct GraphForces: Equatable, Encodable {
    let repel: Double
    let linkDistance: Double
    let linkStrength: Double
    let centerStrength: Double
    let baseNodeRadius: Double
    let collideRadius: Double
    let linkThickness: Double

    func toJSONString() -> String {
        (try? String(data: JSONEncoder().encode(self), encoding: .utf8)) ?? "{}"
    }
}

// MARK: - GraphWebView

struct GraphWebView: UIViewRepresentable {
    let nodes: [KnowledgeGraphNode]
    let edges: [KnowledgeGraphEdge]
    let colorScheme: ColorScheme
    let backgroundHex: String
    let tierHexes: [String: String]
    let edgeHexes: [String: String]
    let labelHex: String
    let labelShadowHex: String
    let forces: GraphForces
    var onNodeTap: (String) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onNodeTap: onNodeTap)
    }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.userContentController.add(context.coordinator, name: "graphBridge")

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.scrollView.isScrollEnabled = false
        webView.scrollView.bounces = false
        webView.scrollView.backgroundColor = .clear
        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.navigationDelegate = context.coordinator
        context.coordinator.webView = webView

        guard let htmlURL = Bundle.main.url(forResource: "graph", withExtension: "html") else {
            return webView
        }
        let bundleDir = htmlURL.deletingLastPathComponent()
        webView.loadFileURL(htmlURL, allowingReadAccessTo: bundleDir)
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        let coord = context.coordinator
        coord.onNodeTap = onNodeTap

        let themeSignature = themeSignature

        // Layer 1: theme change
        if coord.lastThemeSignature != themeSignature || coord.lastColorScheme != colorScheme {
            coord.lastThemeSignature = themeSignature
            coord.lastColorScheme = colorScheme
            coord.sendInitGraph(buildPayload(), webView: webView)
        }

        // Layer 2: forces change
        if coord.lastForces != forces {
            coord.lastForces = forces
            let json = forces.toJSONString()
            webView.evaluateJavaScript("updateForces(\(json))", completionHandler: nil)
        }

        // Layer 3: graph data change
        if coord.lastNodeCount != nodes.count || coord.lastLinkCount != edges.count {
            coord.lastNodeCount = nodes.count
            coord.lastLinkCount = edges.count
            coord.sendInitGraph(buildPayload(), webView: webView)
        }
    }

    // MARK: - Payload builder

    private func buildPayload() -> String {
        let mode = colorScheme == .dark ? "dark" : "light"
        let bg = backgroundHex

        let tierNames = ["green", "yellow", "orange", "red"]
        var colorsDict: [String: [String: String]] = [:]
        for tierName in tierNames {
            let hex = tierHexes[tierName] ?? "#888888"
            colorsDict[tierName] = [
                "dark": hex,
                "light": hex
            ]
        }

        struct NodePayload: Encodable {
            let id, word: String
            let tier: String
            let degree: Int
        }
        struct LinkPayload: Encodable {
            let id, source, target, kind: String
        }
        struct TierPair: Encodable {
            let dark, light: String
        }
        struct ThemePayload: Encodable {
            let mode, background: String
            let colors: [String: TierPair]
            let edges: [String: String]
            let label: String
            let labelShadow: String
        }
        struct Payload: Encodable {
            let nodes: [NodePayload]
            let links: [LinkPayload]
            let forces: GraphForces
            let theme: ThemePayload
        }

        let nodePayloads = nodes.map {
            NodePayload(id: $0.id, word: $0.word, tier: $0.tier ?? "unknown", degree: $0.degree)
        }
        let linkPayloads = edges.map {
            LinkPayload(id: $0.id, source: $0.from, target: $0.to, kind: $0.kind)
        }
        let colorPairs = colorsDict.mapValues { TierPair(dark: $0["dark"]!, light: $0["light"]!) }
        let theme = ThemePayload(
            mode: mode,
            background: bg,
            colors: colorPairs,
            edges: edgeHexes,
            label: labelHex,
            labelShadow: labelShadowHex
        )
        let payload = Payload(nodes: nodePayloads, links: linkPayloads, forces: forces, theme: theme)

        guard let data = try? JSONEncoder().encode(payload),
              let json = String(data: data, encoding: .utf8) else { return "{}" }
        return json
    }

    private var themeSignature: String {
        let sortedTiers = tierHexes.sorted { $0.key < $1.key }
            .map { "\($0.key)=\($0.value)" }
            .joined(separator: "|")
        let sortedEdges = edgeHexes.sorted { $0.key < $1.key }
            .map { "\($0.key)=\($0.value)" }
            .joined(separator: "|")
        return "\(colorScheme)-\(backgroundHex)-\(labelHex)-\(labelShadowHex)-\(sortedTiers)-\(sortedEdges)"
    }

    // MARK: - Coordinator

    class Coordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
        var graphBridgeReady = false
        var pendingPayload: String? = nil
        weak var webView: WKWebView?
        var onNodeTap: (String) -> Void

        var lastColorScheme: ColorScheme? = nil
        var lastThemeSignature: String? = nil
        var lastForces: GraphForces? = nil
        var lastNodeCount = -1
        var lastLinkCount = -1

        init(onNodeTap: @escaping (String) -> Void) {
            self.onNodeTap = onNodeTap
        }

        deinit {
            webView?.configuration.userContentController.removeScriptMessageHandler(forName: "graphBridge")
        }

        func sendInitGraph(_ json: String, webView: WKWebView) {
            guard graphBridgeReady else {
                pendingPayload = json
                return
            }
            let escaped = json
                .replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "'", with: "\\'")
            webView.evaluateJavaScript("initGraph('\(escaped)')", completionHandler: nil)
        }

        // MARK: WKScriptMessageHandler

        func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
            guard message.name == "graphBridge",
                  let body = message.body as? [String: Any],
                  let type = body["type"] as? String else { return }

            switch type {
            case "ready":
                graphBridgeReady = true
                if let pending = pendingPayload, let wv = webView {
                    pendingPayload = nil
                    let escaped = pending
                        .replacingOccurrences(of: "\\", with: "\\\\")
                        .replacingOccurrences(of: "'", with: "\\'")
                    wv.evaluateJavaScript("initGraph('\(escaped)')", completionHandler: nil)
                }
            case "nodeClick":
                if let nodeId = body["nodeId"] as? String {
                    DispatchQueue.main.async { self.onNodeTap(nodeId) }
                }
            default:
                break
            }
        }
    }
}
