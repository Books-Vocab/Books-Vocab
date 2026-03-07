import SwiftUI
import SwiftData
import UIKit

struct KnowledgeGraphView: View {
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.vocabSkin) private var vocabSkin
    @Query private var allEntries: [VocabularyEntry]

    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager

    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var isShowingSettings = false
    @State private var links: [KGGraphLink] = []
    @State private var selectedEntry: VocabularyEntry? = nil

    // ── Force 參數（Obsidian 風格，直接對應 D3 各力）────────────────────────
    @State private var centerForce: Double   = 0.05   // 0-1 → forceX/Y gravity 0-0.3
    @State private var repelForce: Double    = 0.20   // 0-1 → manyBody strength 0-400
    @State private var linkForce: Double     = 0.50   // 0-1 → forceLink strength 0-2
    @State private var linkDistance: Double  = 50     // px，直接傳 D3
    @State private var nodeSize: Double      = 5.0    // = baseNodeRadius
    @State private var linkThickness: Double = 1.0    // screen-space px

    private var repelStrength: Double   { repelForce * 400 }
    private var centerStrength: Double  { centerForce * 0.3 }   // forceX/Y gravity
    private var linkStrengthVal: Double { linkForce * 2 }
    private var collideRadius: Double   { nodeSize * 1.5 }

    var body: some View {
        ZStack {
            vocabSkin.palette.pageBackground.ignoresSafeArea()

            if !authManager.isLoggedIn {
                ContentUnavailableView(
                    "需登入帳號",
                    systemImage: "person.crop.circle.badge.exclamationmark",
                    description: Text("請至設定中登入以查閱您的知識關聯。")
                )
            } else if isLoading {
                ProgressView("正在載入關聯圖...")
            } else if let error = errorMessage {
                ContentUnavailableView(
                    "載入失敗",
                    systemImage: "exclamationmark.triangle",
                    description: Text(error)
                )
            } else if nodes.isEmpty {
                ContentUnavailableView(
                    "知識圖譜為空",
                    systemImage: "point.3.connected.trianglepath.dotted",
                    description: Text("知識庫中尚無單字，或尚未與伺服器同步。")
                )
            } else {
                ZStack(alignment: .bottom) {
                    graphView

                    if isShowingSettings {
                        settingsOverlay
                            .transition(.move(edge: .bottom).combined(with: .opacity))
                    }
                }
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button {
                            withAnimation(.spring(response: 0.3, dampingFraction: 0.8)) {
                                isShowingSettings.toggle()
                            }
                        } label: {
                            VocabToolbarGlyph(
                                systemImage: isShowingSettings ? "xmark.circle.fill" : "slider.horizontal.3"
                            )
                        }
                    }
                }
            }
        }
        .task { await loadGraphData() }
        .sheet(item: $selectedEntry) { entry in
            WordDetailSheet(entry: entry)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
    }

    // MARK: - Graph View

    private var graphView: some View {
        GraphWebView(
            nodes: nodes,
            edges: edges,
            colorScheme: colorScheme,
            backgroundHex: cssHex(vocabSkin.palette.pageBackground),
            tierHexes: [
                "core": cssHex(vocabSkin.palette.success),
                "intermediate": cssHex(vocabSkin.tierColor(for: "intermediate")),
                "advanced": cssHex(vocabSkin.tierColor(for: "advanced")),
                "rare": cssHex(vocabSkin.palette.destructive),
                "unknown": cssHex(vocabSkin.palette.secondaryText)
            ],
            forces: GraphForces(
                repel: repelStrength,
                linkDistance: linkDistance,
                linkStrength: linkStrengthVal,
                centerStrength: centerStrength,
                baseNodeRadius: nodeSize,
                collideRadius: collideRadius,
                linkThickness: linkThickness
            ),
            onNodeTap: { nodeId in
                selectedEntry = allEntries.first { $0.kgCardId == nodeId }
            }
        )
        .ignoresSafeArea()
        .mask(
            LinearGradient(
                stops: [
                    .init(color: .clear, location: 0.00),
                    .init(color: .black, location: 0.05),
                    .init(color: .black, location: 0.88),
                    .init(color: .clear, location: 1.00)
                ],
                startPoint: .top,
                endPoint: .bottom
            )
        )
    }

    // MARK: - Settings Overlay（Obsidian 風格）

    private var settingsOverlay: some View {
        VocabCard(padding: 0) {
            VStack(spacing: 0) {
                // Header
                HStack {
                    Button("重設", action: resetForces)
                        .font(vocabSkin.typography.body)
                        .foregroundStyle(vocabSkin.palette.accent)
                    Spacer()
                    Text("關聯圖")
                        .font(vocabSkin.typography.captionStrong)
                        .foregroundStyle(vocabSkin.palette.primaryText)
                    Spacer()
                    Button {
                        withAnimation(.spring(response: 0.3, dampingFraction: 0.8)) {
                            isShowingSettings = false
                        }
                    } label: {
                        VocabToolbarGlyph(systemImage: "xmark.circle.fill")
                    }
                }
                .padding(.horizontal, 16)
                .padding(.top, 14)
                .padding(.bottom, 10)

                Divider().padding(.horizontal, 8)

                VStack(spacing: 0) {
                    // ── 力 ────────────────────────────────────────────────
                    sectionHeader("力")
                    forceRow("向心力",    value: $centerForce,   range: 0...1,     fmt: "%.2f")
                    forceRow("排斥力",    value: $repelForce,    range: 0...1,     fmt: "%.2f")
                    forceRow("連結強度",  value: $linkForce,     range: 0...1,     fmt: "%.2f")
                    forceRow("連結距離",  value: $linkDistance,  range: 20...300,  fmt: "%.0f")

                    Divider().padding(.vertical, 6)

                    // ── 顯示 ──────────────────────────────────────────────
                    sectionHeader("顯示")
                    forceRow("節點大小",  value: $nodeSize,       range: 1...10,   fmt: "%.1f")
                    forceRow("連結粗細",  value: $linkThickness,  range: 0.5...3,  fmt: "%.1f")
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 12)
            }
        }
        .frame(maxWidth: 420)
        .padding(.horizontal, 12)
        .padding(.bottom, 8)
    }

    private func resetForces() {
        centerForce = 0.05; repelForce = 0.20; linkForce = 0.50
        linkDistance = 50;  nodeSize = 5.0;    linkThickness = 1.0
    }

    private func sectionHeader(_ title: String) -> some View {
        HStack {
            Text(title)
                .font(vocabSkin.typography.captionStrong)
                .foregroundStyle(vocabSkin.palette.tertiaryText)
                .tracking(0.5)
            Spacer()
        }
        .padding(.top, 10)
        .padding(.bottom, 2)
    }

    private func forceRow(_ label: String, value: Binding<Double>,
                           range: ClosedRange<Double>, fmt: String) -> some View {
        HStack(spacing: 8) {
            Text(label)
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.primaryText)
                .frame(width: 52, alignment: .leading)
            Slider(value: value, in: range)
            Text(String(format: fmt, value.wrappedValue))
                .font(vocabSkin.typography.monoLabel)
                .foregroundStyle(vocabSkin.palette.secondaryText)
                .frame(width: 36, alignment: .trailing)
        }
        .frame(height: 32)
    }

    // MARK: - Data

    struct GraphNode: Identifiable {
        let id: String
        let word: String
        let tier: String?
        var degree: Int = 0
    }

    struct GraphEdge: Identifiable {
        let id: String
        let from: String
        let to: String
        let kind: String
    }

    private var nodes: [GraphNode] {
        var degreeMap: [String: Int] = [:]
        for link in links {
            degreeMap[link.fromId, default: 0] += 1
            degreeMap[link.toId, default: 0] += 1
        }
        var result: [GraphNode] = []
        for entry in allEntries {
            guard entry.isSynced, let kgId = entry.kgCardId else { continue }
            let degree = degreeMap[kgId] ?? 0
            if degree > 0 {
                result.append(GraphNode(id: kgId, word: entry.word,
                                        tier: entry.difficultyTier, degree: degree))
            }
        }
        return result
    }

    private var edges: [GraphEdge] {
        let validIds = Set(nodes.map { $0.id })
        return links.compactMap { link in
            guard validIds.contains(link.fromId) && validIds.contains(link.toId) else { return nil }
            return GraphEdge(id: link.id, from: link.fromId, to: link.toId, kind: link.kind)
        }
    }

    // MARK: - Networking

    private func loadGraphData() async {
        guard authManager.isLoggedIn else { return }
        isLoading = true
        errorMessage = nil
        do {
            links = try await kgService.pullGraphLinks()
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    private func cssHex(_ color: Color) -> String {
        var r: CGFloat = 0
        var g: CGFloat = 0
        var b: CGFloat = 0
        var a: CGFloat = 0
        UIColor(color).getRed(&r, green: &g, blue: &b, alpha: &a)
        return String(format: "#%02X%02X%02X", Int(r * 255), Int(g * 255), Int(b * 255))
    }
}
