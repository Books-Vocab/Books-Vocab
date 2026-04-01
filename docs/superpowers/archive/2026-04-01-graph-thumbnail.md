# Graph Thumbnail Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 在總覽頁「關聯圖」卡片嵌入迷你 D3 力導向圖縮圖。
**Architecture:** 復用 graph.html 加 thumbnail mode flag，新增輕量 GraphThumbnailWebView，StatsPresenter 平行載入 links 並渲染縮圖。
**Tech Stack:** D3.js (existing)、WKWebView、SwiftUI

---

### Task 1: graph.html — 加 thumbnail mode

**Files:**
- Modify: `ios/BooksBrowser/Resources/graph.html`

- [ ] **Step 1: 加 module-scope flag + initGraph 解析**

在 line 16 的 global state 區加入：
```javascript
let isThumbnail = false;
```

在 `initGraph()` 函數（line 257）解析 data 後加入：
```javascript
isThumbnail = !!data.thumbnail;
```

- [ ] **Step 2: thumbnail 時調整 simulation 參數**

在 `initGraph()` 建立 simulation 後（line 314 `.on('tick', draw);` 之後）加入：
```javascript
if (isThumbnail) {
    sim.alphaDecay(0.08).alphaMin(0.05).velocityDecay(0.6);
}
```

- [ ] **Step 3: thumbnail 時縮小初始 spawn radius**

修改 line 285-286 的隨機位置生成：
```javascript
const spawnR = isThumbnail ? 30 : 80;
const spawnMin = isThumbnail ? 10 : 20;
const radius = Math.random() * spawnR + spawnMin;
```

- [ ] **Step 4: draw() 中跳過 glow 和 label**

在 draw() 的 glow 區塊（line 122-130）外包一層：
```javascript
if (!isThumbnail) {
    // existing glow code (lines 122-130)
}
```

在 draw() 的 label 區塊（line 140-155）外包一層：
```javascript
if (!isThumbnail) {
    // existing label code (lines 140-155)
}
```

- [ ] **Step 5: thumbnail 時不綁定互動事件**

將 zoom/drag/click/hover 的綁定（lines 189-254）移入 `initGraph()` 內部，用 `isThumbnail` guard：

替換 lines 188-254 為：
```javascript
// ── Interactions (bound once by initGraph, skipped in thumbnail) ──────────
let interactionsBound = false;

function bindInteractions() {
    if (interactionsBound || isThumbnail) return;
    interactionsBound = true;

    const zoom = d3.zoom()
        .scaleExtent([0.1, 8])
        .on('zoom', e => { transform = e.transform; draw(); });
    d3.select(canvas).call(zoom);

    const drag = d3.drag()
        .subject(function(event) {
            return findNode(event.x, event.y) || null;
        })
        .on('start', function(event) {
            if (!event.subject) return;
            const d = event.subject;
            d.fx = d.x; d.fy = d.y;
            if (sim) sim.alphaTarget(0.3).restart();
        })
        .on('drag', function(event) {
            if (!event.subject) return;
            const d = event.subject;
            d.fx = (event.x - transform.x) / transform.k;
            d.fy = (event.y - transform.y) / transform.k;
        })
        .on('end', function(event) {
            if (!event.subject) return;
            const d = event.subject;
            d.fx = null; d.fy = null;
            if (sim) sim.alphaTarget(0);
        });
    d3.select(canvas).call(drag);

    canvas.addEventListener('click', function(e) {
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const node = findNode(x, y);
        if (node) {
            if (selectedId === node.id) {
                selectedId = null;
            } else {
                selectedId = node.id;
                postBridge({ type: 'nodeClick', nodeId: node.id });
            }
        } else {
            selectedId = null;
        }
        draw();
    });

    canvas.addEventListener('pointermove', function(e) {
        if (e.buttons !== 0) return;
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const node = findNode(x, y);
        const newId = node ? node.id : null;
        if (newId !== hoveredId) {
            hoveredId = newId;
            draw();
        }
    });

    canvas.addEventListener('pointerleave', function() {
        if (hoveredId !== null) { hoveredId = null; draw(); }
    });
}
```

在 `initGraph()` 的末尾（`draw();` 之後）加入：
```javascript
bindInteractions();
```

- [ ] **Step 6: Build 驗證**
Run: `./ops/ios_build.sh`
Expected: Exit 0

---

### Task 2: GraphThumbnailWebView.swift — 新檔案

**Files:**
- Create: `ios/BooksBrowser/Views/Vocabulary/GraphThumbnailWebView.swift`
- Modify: `ios/BooksBrowser.xcodeproj/project.pbxproj` (加入新檔案到 target)

- [ ] **Step 1: 建立 GraphThumbnailWebView（含正確的 Coordinator）**

```swift
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

    private func buildPayload() -> String {
        struct NodePayload: Encodable {
            let id, word: String; let tier: String; let color: String?; let ratio: Double?; let degree: Int
        }
        struct LinkPayload: Encodable {
            let id, source, target, kind: String
        }
        struct TierPair: Encodable { let dark, light: String }
        struct ThemePayload: Encodable {
            let mode, background: String; let colors: [String: TierPair]
            let edges: [String: String]; let label, labelShadow: String
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
```

- [ ] **Step 2: Build 驗證**
Run: `./ops/ios_build.sh`
Expected: Exit 0

---

### Task 3: StatsPresenter.swift — 整合縮圖

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/StatsPresenter.swift`

- [ ] **Step 1: 加環境注入和 state**

在 `@Environment(\.vocabSkin)` 下方加：
```swift
@Environment(\.kgService) private var kgService
@Environment(\.authManager) private var authManager
@Environment(\.colorScheme) private var colorScheme
```

在 `@State private var contentReady = false` 下方加：
```swift
@State private var graphLinks: [KGGraphLink]?
```

- [ ] **Step 2: 平行載入 links**

將 `.task(id: recomputeKey)` 改為（`buildSummary` 是同步函數，先算完；`loadGraphLinks` 是 async，獨立載入）：
```swift
.task(id: recomputeKey) {
    let entries = filteredEntries
    let records = filteredReviewRecords
    let days = forecastDays
    summary = StatsPresentation.buildSummary(
        from: entries,
        reviewRecords: records,
        forecastDays: days
    )
    graphLinks = await loadGraphLinks()
}
```

在 `recomputeKey` computed property 下方加：
```swift
private func loadGraphLinks() async -> [KGGraphLink] {
    if authManager.isDemoMode {
        return DemoDataProvider.demoGraphLinks
    }
    guard authManager.isLoggedIn else { return [] }
    return (try? await kgService.pullGraphLinks()) ?? []
}
```

- [ ] **Step 3: 替換 graphEntrySection**

替換整個 `graphEntrySection` computed property（lines 113-133）為：

```swift
private var graphEntrySection: some View {
    NavigationLink {
        KnowledgeGraphView(allEntries: filteredEntries)
    } label: {
        VocabCard(padding: 0) {
            VStack(spacing: 0) {
                graphEntryHeader
                    .padding(vocabSkin.metrics.cardBlockPadding)

                graphEntryBody
                    .frame(height: 140)
            }
        }
    }
    .buttonStyle(.liftable)
}

private var graphEntryHeader: some View {
    HStack(spacing: vocabSkin.spacing.inlineGap) {
        Image(systemName: "point.3.connected.trianglepath.dotted")
            .font(vocabSkin.typography.iconMedium)
            .foregroundStyle(vocabSkin.palette.accent)
        Text("關聯圖".localized)
            .font(vocabSkin.typography.captionStrong)
            .foregroundStyle(vocabSkin.palette.primaryText)
        Spacer()
        if let graphLinks, !graphLinks.isEmpty {
            let nodes = graphThumbnailNodes
            Text("\(nodes.count) 詞 · \(graphLinks.count) 連結")
                .font(vocabSkin.typography.monoLabel)
                .foregroundStyle(vocabSkin.palette.quaternaryText)
        }
        Image(systemName: "chevron.right")
            .font(vocabSkin.typography.iconSmall)
            .foregroundStyle(vocabSkin.palette.quaternaryText)
    }
}

@ViewBuilder
private var graphEntryBody: some View {
    if let graphLinks {
        let nodes = graphThumbnailNodes
        let nodeIDs = Set(nodes.map(\.id))
        let edges = KnowledgeGraphPresentation.edges(from: graphLinks, validNodeIDs: nodeIDs)

        if nodes.isEmpty {
            VocabStateMessageCard(
                title: "探索單字建立連結".localized,
                systemImage: "point.3.connected.trianglepath.dotted"
            )
        } else {
            GraphThumbnailWebView(
                nodes: nodes,
                edges: edges,
                theme: KnowledgeGraphPresentation.theme(for: vocabSkin),
                colorScheme: colorScheme
            )
        }
    } else {
        ProgressView()
            .controlSize(.small)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private var graphThumbnailNodes: [KnowledgeGraphNode] {
    guard let graphLinks else { return [] }
    return KnowledgeGraphPresentation.nodes(
        from: filteredEntries,
        links: graphLinks,
        showIsolatedNodes: false
    )
}
```

- [ ] **Step 4: Build 驗證**
Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 5: Commit**
