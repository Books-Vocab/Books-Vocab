# Graph Health Blob Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 把總覽頁圖譜縮圖改為密集色塊信號器 + 極簡健康度 bar。
**Architecture:** 調整 D3 thumbnail 力參數產生密集色團，SwiftUI 端新增漸層 bar + marker，修正 signature hash bug。
**Tech Stack:** D3.js (graph.html)、SwiftUI、ReviewGradient

---

### Task 1: graph.html — thumbnail 色團模式

**Files:**
- Modify: `ios/BooksBrowser/Resources/graph.html:81-85` (opacityForEdge)
- Modify: `ios/BooksBrowser/Resources/graph.html:317-330` (initGraph simulation setup)

- [ ] **Step 1: `opacityForEdge` 加 thumbnail 分支**

在 `opacityForEdge` 函式開頭加入 thumbnail 短路：

```javascript
function opacityForEdge(sid, tid) {
    if (isThumbnail) return 0.08;
    if (!selectedId) return 0.25;
    if (sid === selectedId || tid === selectedId) return 0.7;
    return 0.05;
}
```

- [ ] **Step 2: `initGraph` — thumbnail 移除 collide force**

在 `graph.html` 第 328-330 行的 `if (isThumbnail)` 區塊內，加入移除 collide：

```javascript
if (isThumbnail) {
    sim.alphaDecay(0.08).alphaMin(0.05).velocityDecay(0.6);
    sim.force('collide', null);
}
```

- [ ] **Step 3: iOS build 驗證**

Run: `./ops/ios_build.sh`
Expected: Exit 0（graph.html 是 bundle resource，只要語法正確即可）

---

### Task 2: GraphThumbnailWebView — 力參數 + signature 修正

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/GraphThumbnailWebView.swift:32-37` (updateUIView signature)
- Modify: `ios/BooksBrowser/Views/Vocabulary/GraphThumbnailWebView.swift:83-87` (forces)

- [ ] **Step 1: 更新 forces 參數**

```swift
let forces = GraphForces(
    repel: 12, linkDistance: 12, linkStrength: 1.8,
    centerStrength: 0.2, baseNodeRadius: 4,
    collideRadius: 0, linkThickness: 0.8
)
```

注意：`collideRadius` 仍傳 0（GraphForces struct 要求），但 JS 端已用 `sim.force('collide', null)` 處理。

- [ ] **Step 2: 修正 signature hash**

將 `updateUIView` 中的 signature 改為包含 nodes 內容 hash：

```swift
func updateUIView(_ webView: WKWebView, context: Context) {
    let coord = context.coordinator
    var hasher = Hasher()
    hasher.combine(colorScheme == .dark)
    for n in nodes {
        hasher.combine(n.id)
        hasher.combine(n.colorHex)
        hasher.combine(n.ratio)
    }
    hasher.combine(edges.count)
    let sig = "\(hasher.finalize())"
    guard coord.lastSignature != sig else { return }
    coord.lastSignature = sig
    coord.sendInitGraph(buildPayload(), webView: webView)
}
```

- [ ] **Step 3: iOS build 驗證**

Run: `./ops/ios_build.sh`
Expected: Exit 0

---

### Task 3: StatsPresenter — 健康度 Bar + 重構

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/StatsPresenter.swift:125-197`

- [ ] **Step 1: 消除 graphThumbnailNodes 重複計算**

將 `graphEntrySection` 重構，nodes 只算一次：

```swift
private var graphEntrySection: some View {
    let nodes = graphThumbnailNodes
    let nodeIDs = Set(nodes.map(\.id))
    let edges = graphLinks.map {
        KnowledgeGraphPresentation.edges(from: $0, validNodeIDs: nodeIDs)
    } ?? []

    return NavigationLink {
        KnowledgeGraphView(allEntries: filteredEntries)
    } label: {
        VocabCard(padding: 0) {
            VStack(spacing: 0) {
                graphEntryHeader(nodeCount: nodes.count)
                    .padding(vocabSkin.metrics.cardBlockPadding)

                graphEntryBody(nodes: nodes, edges: edges)
                    .frame(height: 140)

                if let avgRatio = averageRatio(of: nodes), !nodes.isEmpty {
                    healthBar(ratio: avgRatio)
                        .padding(.horizontal, vocabSkin.metrics.cardBlockPadding)
                        .padding(.bottom, 8)
                }
            }
        }
    }
    .buttonStyle(.liftable)
}
```

- [ ] **Step 2: 新增 `averageRatio` 計算**

```swift
private func averageRatio(of nodes: [KnowledgeGraphNode]) -> Double? {
    let ratios = nodes.compactMap(\.ratio)
    guard !ratios.isEmpty else { return nil }
    return ratios.reduce(0, +) / Double(ratios.count)
}
```

- [ ] **Step 3: 新增 `healthBar` view**

```swift
private func healthBar(ratio: Double) -> some View {
    let stops: [Gradient.Stop] = [
        0, 0.15, 0.30, 0.45, 0.60, 0.72, 0.85, 1.0, 1.3, 2.0, 3.0
    ].map { r in
        Gradient.Stop(
            color: ReviewGradient.color(for: r),
            location: CGFloat(min(r / 3.0, 1.0))
        )
    }
    let position = CGFloat(min(max(ratio, 0), 3.0) / 3.0)

    return VStack(spacing: 0) {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                // Gradient bar
                RoundedRectangle(cornerRadius: 1)
                    .fill(LinearGradient(
                        stops: stops,
                        startPoint: .leading,
                        endPoint: .trailing
                    ))
                    .frame(height: 2)

                // Triangle marker
                Triangle()
                    .fill(vocabSkin.palette.primaryText)
                    .frame(width: 6, height: 5)
                    .offset(
                        x: geo.size.width * position - 3,
                        y: -4
                    )
            }
        }
        .frame(height: 7)
    }
}
```

- [ ] **Step 4: 新增 Triangle shape（倒三角 ▼，尖端朝下指向 bar）**

在 StatsPresenter 檔案底部：

```swift
private struct Triangle: Shape {
    func path(in rect: CGRect) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: rect.midX, y: rect.maxY))
        p.addLine(to: CGPoint(x: rect.maxX, y: 0))
        p.addLine(to: CGPoint(x: rect.minX, y: 0))
        p.closeSubpath()
        return p
    }
}
```

- [ ] **Step 5: 刪除舊 computed property，改為接受參數的函式**

**刪除**原有的 `private var graphEntryHeader: some View`（L142-161）和 `private var graphEntryBody: some View`（L163-188），替換為以下函式（兩者同名但 signature 不同，必須刪除舊定義否則 redeclaration error）：

```swift
private func graphEntryHeader(nodeCount: Int) -> some View {
    HStack(spacing: vocabSkin.spacing.inlineGap) {
        Image(systemName: "point.3.connected.trianglepath.dotted")
            .font(vocabSkin.typography.iconMedium)
            .foregroundStyle(vocabSkin.palette.accent)
        Text("關聯圖".localized)
            .font(vocabSkin.typography.captionStrong)
            .foregroundStyle(vocabSkin.palette.primaryText)
        Spacer()
        if let graphLinks, !graphLinks.isEmpty {
            Text("\(nodeCount) 詞 · \(graphLinks.count) 連結")
                .font(vocabSkin.typography.monoLabel)
                .foregroundStyle(vocabSkin.palette.quaternaryText)
        }
        Image(systemName: "chevron.right")
            .font(vocabSkin.typography.iconSmall)
            .foregroundStyle(vocabSkin.palette.quaternaryText)
    }
}

@ViewBuilder
private func graphEntryBody(nodes: [KnowledgeGraphNode], edges: [KnowledgeGraphEdge]) -> some View {
    if graphLinks != nil {
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
```

- [ ] **Step 6: iOS build 驗證**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 7: Commit**

```
ios: graph thumbnail — dense blob mode + health bar
```
