import SwiftUI
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

#if os(iOS)
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
        let webView = Self.createWebView(context: context)
        webView.scrollView.isScrollEnabled = false
        webView.scrollView.bounces = false
        webView.scrollView.backgroundColor = .clear
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        Self.updateWebView(webView, context: context, nodes: nodes, edges: edges,
                           colorScheme: colorScheme, backgroundHex: backgroundHex,
                           tierHexes: tierHexes, edgeHexes: edgeHexes, labelHex: labelHex,
                           labelShadowHex: labelShadowHex, forces: forces, onNodeTap: onNodeTap)
    }

    static func dismantleUIView(_ webView: WKWebView, coordinator: Coordinator) {
        Self.dismantleWebView(webView, coordinator: coordinator)
    }
}
#elseif os(macOS)
struct GraphWebView: NSViewRepresentable {
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

    func makeNSView(context: Context) -> WKWebView {
        Self.createWebView(context: context)
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        Self.updateWebView(webView, context: context, nodes: nodes, edges: edges,
                           colorScheme: colorScheme, backgroundHex: backgroundHex,
                           tierHexes: tierHexes, edgeHexes: edgeHexes, labelHex: labelHex,
                           labelShadowHex: labelShadowHex, forces: forces, onNodeTap: onNodeTap)
    }

    static func dismantleNSView(_ webView: WKWebView, coordinator: Coordinator) {
        Self.dismantleWebView(webView, coordinator: coordinator)
    }
}
#endif

// MARK: - Shared implementation

extension GraphWebView {
    static func createWebView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.userContentController.add(context.coordinator, name: "graphBridge")

        let webView = WKWebView(frame: .zero, configuration: config)
        #if os(iOS)
        webView.isOpaque = false
        webView.backgroundColor = .clear
        #elseif os(macOS)
        webView.setValue(false, forKey: "drawsBackground")
        #endif
        webView.navigationDelegate = context.coordinator
        context.coordinator.webView = webView

        guard let htmlURL = Bundle.main.url(forResource: "graph", withExtension: "html") else {
            return webView
        }
        let bundleDir = htmlURL.deletingLastPathComponent()
        webView.loadFileURL(htmlURL, allowingReadAccessTo: bundleDir)
        return webView
    }

    static func updateWebView(
        _ webView: WKWebView, context: Context,
        nodes: [KnowledgeGraphNode], edges: [KnowledgeGraphEdge],
        colorScheme: ColorScheme, backgroundHex: String,
        tierHexes: [String: String], edgeHexes: [String: String],
        labelHex: String, labelShadowHex: String,
        forces: GraphForces, onNodeTap: @escaping (String) -> Void
    ) {
        let coord = context.coordinator
        coord.onNodeTap = onNodeTap

        let sig = themeSignature(colorScheme: colorScheme, backgroundHex: backgroundHex,
                                  labelHex: labelHex, labelShadowHex: labelShadowHex,
                                  tierHexes: tierHexes, edgeHexes: edgeHexes)
        let themeChanged = coord.lastThemeSignature != sig || coord.lastColorScheme != colorScheme
        let dataChanged = coord.lastNodeCount != nodes.count || coord.lastLinkCount != edges.count

        if themeChanged || dataChanged {
            coord.lastThemeSignature = sig
            coord.lastColorScheme = colorScheme
            coord.lastNodeCount = nodes.count
            coord.lastLinkCount = edges.count
            let payload = buildPayload(nodes: nodes, edges: edges, colorScheme: colorScheme,
                                        backgroundHex: backgroundHex, tierHexes: tierHexes,
                                        edgeHexes: edgeHexes, labelHex: labelHex,
                                        labelShadowHex: labelShadowHex, forces: forces)
            coord.sendInitGraph(payload, webView: webView)
        }

        if coord.lastForces != forces {
            coord.lastForces = forces
            let json = forces.toJSONString()
            webView.evaluateJavaScript("updateForces(\(json))", completionHandler: nil)
        }
    }

    static func dismantleWebView(_ webView: WKWebView, coordinator: Coordinator) {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "graphBridge")
        coordinator.onNodeTap = nil
    }

    // MARK: - Payload builder

    private static func buildPayload(
        nodes: [KnowledgeGraphNode], edges: [KnowledgeGraphEdge],
        colorScheme: ColorScheme, backgroundHex: String,
        tierHexes: [String: String], edgeHexes: [String: String],
        labelHex: String, labelShadowHex: String, forces: GraphForces
    ) -> String {
        let mode = colorScheme == .dark ? "dark" : "light"

        let tierNames = ["gray", "archived"]
        var colorsDict: [String: [String: String]] = [:]
        for tierName in tierNames {
            let hex = tierHexes[tierName] ?? "#888888"
            colorsDict[tierName] = ["dark": hex, "light": hex]
        }

        struct NodePayload: Encodable {
            let id, word: String
            let tier: String
            let color: String?
            let ratio: Double?
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
            NodePayload(id: $0.id, word: $0.word, tier: $0.tier ?? "unknown", color: $0.colorHex, ratio: $0.ratio, degree: $0.degree)
        }
        let linkPayloads = edges.map {
            LinkPayload(id: $0.id, source: $0.from, target: $0.to, kind: $0.kind)
        }
        let colorPairs = colorsDict.reduce(into: [String: TierPair]()) { partialResult, entry in
            let dark = entry.value["dark"] ?? "#888888"
            let light = entry.value["light"] ?? dark
            partialResult[entry.key] = TierPair(dark: dark, light: light)
        }
        let theme = ThemePayload(mode: mode, background: backgroundHex, colors: colorPairs,
                                  edges: edgeHexes, label: labelHex, labelShadow: labelShadowHex)
        let payload = Payload(nodes: nodePayloads, links: linkPayloads, forces: forces, theme: theme)

        guard let data = try? JSONEncoder().encode(payload),
              let json = String(data: data, encoding: .utf8) else { return "{}" }
        return json
    }

    private static func themeSignature(
        colorScheme: ColorScheme, backgroundHex: String,
        labelHex: String, labelShadowHex: String,
        tierHexes: [String: String], edgeHexes: [String: String]
    ) -> String {
        let sortedTiers = tierHexes.sorted { $0.key < $1.key }
            .map { "\($0.key)=\($0.value)" }.joined(separator: "|")
        let sortedEdges = edgeHexes.sorted { $0.key < $1.key }
            .map { "\($0.key)=\($0.value)" }.joined(separator: "|")
        return "\(colorScheme)-\(backgroundHex)-\(labelHex)-\(labelShadowHex)-\(sortedTiers)-\(sortedEdges)"
    }

    // MARK: - Coordinator

    class Coordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
        var graphBridgeReady = false
        var pendingPayload: String? = nil
        weak var webView: WKWebView?
        var onNodeTap: ((String) -> Void)?

        var lastColorScheme: ColorScheme? = nil
        var lastThemeSignature: String? = nil
        var lastForces: GraphForces? = nil
        var lastNodeCount = -1
        var lastLinkCount = -1

        init(onNodeTap: @escaping (String) -> Void) {
            self.onNodeTap = onNodeTap
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
                    DispatchQueue.main.async { [weak self] in
                        self?.onNodeTap?(nodeId)
                    }
                }
            default:
                break
            }
        }
    }
}
