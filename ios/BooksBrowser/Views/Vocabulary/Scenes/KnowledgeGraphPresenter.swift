import SwiftUI

struct KnowledgeGraphPresenter: View {
    struct ForceBindings {
        let centerForce: Binding<Double>
        let repelForce: Binding<Double>
        let linkForce: Binding<Double>
        let linkDistance: Binding<Double>
        let nodeSize: Binding<Double>
        let linkThickness: Binding<Double>
    }

    struct State {
        struct EmptyState {
            let title: String
            let systemImage: String
            let description: String
        }

        let emptyState: EmptyState?
        let nodes: [KnowledgeGraphNode]
        let edges: [KnowledgeGraphEdge]
        let graphTheme: KnowledgeGraphTheme
        let forces: GraphForces
        let showsSettings: Bool
    }

    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.vocabSkin) private var vocabSkin

    let state: State
    let bindings: ForceBindings
    let onToggleSettings: () -> Void
    let onResetForces: () -> Void
    let onNodeTapped: (String) -> Void

    var body: some View {
        ZStack {
            vocabSkin.palette.pageBackground.ignoresSafeArea()

            if let emptyState = state.emptyState {
                centeredStateCard(emptyState)
                    .transition(.contentSwap)
            } else {
                ZStack(alignment: .bottom) {
                    graphView

                    if state.showsSettings {
                        settingsOverlay
                            .transition(.readerPanelReveal)
                    }
                }
                .animation(AppMotion.standardSpring, value: state.showsSettings)
                .transition(.opacity)
                .animation(AppMotion.contentFade, value: state.emptyState == nil)
            .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button(action: onToggleSettings) {
                            VocabToolbarGlyph(
                                systemImage: state.showsSettings ? "xmark.circle.fill" : "slider.horizontal.3"
                            )
                        }
                    }
                }
            }
        }
    }

    private var graphView: some View {
        GraphWebView(
            nodes: state.nodes,
            edges: state.edges,
            colorScheme: colorScheme,
            backgroundHex: state.graphTheme.backgroundHex,
            tierHexes: state.graphTheme.tierHexes,
            edgeHexes: state.graphTheme.edgeHexes,
            labelHex: state.graphTheme.labelHex,
            labelShadowHex: state.graphTheme.labelShadowHex,
            forces: state.forces,
            onNodeTap: onNodeTapped
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

    private var settingsOverlay: some View {
        VocabCard(padding: 0) {
            VStack(spacing: 0) {
                VocabOverlayHeader(
                    title: "關聯圖",
                    systemImage: "point.3.connected.trianglepath.dotted",
                    onClose: onToggleSettings
                ) {
                    VocabInlineActionButton(title: "重設", action: onResetForces)
                }

                Divider().padding(.horizontal, vocabSkin.metrics.overlayCompactDividerInset)

                VStack(spacing: 0) {
                    VocabSectionHeader(title: "力")
                    VocabSliderRow(label: "向心力", value: bindings.centerForce, range: 0...1, format: "%.2f")
                    VocabSliderRow(label: "排斥力", value: bindings.repelForce, range: 0...1, format: "%.2f")
                    VocabSliderRow(label: "連結強度", value: bindings.linkForce, range: 0...1, format: "%.2f")
                    VocabSliderRow(label: "連結距離", value: bindings.linkDistance, range: 20...300, format: "%.0f")

                    Divider().padding(.vertical, vocabSkin.spacing.microGap)

                    VocabSectionHeader(title: "顯示")
                    VocabSliderRow(label: "節點大小", value: bindings.nodeSize, range: 1...10, format: "%.1f")
                    VocabSliderRow(label: "連結粗細", value: bindings.linkThickness, range: 0.5...3, format: "%.1f")
                }
                .padding(.horizontal, vocabSkin.metrics.listRowHorizontalInset)
                .padding(.bottom, vocabSkin.metrics.graphDrawerBottomInset)
            }
        }
        .frame(maxWidth: 420)
        .padding(.horizontal, vocabSkin.metrics.overlayDrawerHorizontalInset)
        .padding(.bottom, vocabSkin.metrics.overlayDrawerBottomInset)
    }

    private func centeredStateCard(_ state: State.EmptyState) -> some View {
        VStack {
            Spacer()
            VocabEmptyStateCard(
                title: state.title,
                systemImage: state.systemImage,
                description: state.description
            )
            Spacer()
        }
        .padding(vocabSkin.metrics.emptyStateOuterInset)
    }
}

private struct KnowledgeGraphPresenterPreviewHarness: View {
    @State private var centerForce = 0.24
    @State private var repelForce = 0.76
    @State private var linkForce = 0.32
    @State private var linkDistance = 120.0
    @State private var nodeSize = 4.2
    @State private var linkThickness = 1.1

    let state: KnowledgeGraphPresenter.State

    private var bindings: KnowledgeGraphPresenter.ForceBindings {
        .init(
            centerForce: $centerForce,
            repelForce: $repelForce,
            linkForce: $linkForce,
            linkDistance: $linkDistance,
            nodeSize: $nodeSize,
            linkThickness: $linkThickness
        )
    }

    var body: some View {
        NavigationStack {
            KnowledgeGraphPresenter(
                state: state,
                bindings: bindings,
                onToggleSettings: {},
                onResetForces: {},
                onNodeTapped: { _ in }
            )
        }
    }
}

private enum KnowledgeGraphPresenterPreviewData {
    static let sampleNodes = [
        KnowledgeGraphNode(id: "1", word: "subtle", tier: "core", degree: 3),
        KnowledgeGraphNode(id: "2", word: "nuance", tier: "advanced", degree: 2),
        KnowledgeGraphNode(id: "3", word: "precise", tier: "intermediate", degree: 2)
    ]

    static let sampleEdges = [
        KnowledgeGraphEdge(id: "e1", from: "1", to: "2", kind: "confusable"),
        KnowledgeGraphEdge(id: "e2", from: "2", to: "3", kind: "shares_usage")
    ]

    static func state(showsSettings: Bool) -> KnowledgeGraphPresenter.State {
        let skin = VocabSkin.previewNeutral
        return .init(
            emptyState: nil,
            nodes: sampleNodes,
            edges: sampleEdges,
            graphTheme: KnowledgeGraphPresentation.theme(for: skin),
            forces: GraphForces(
                repel: 0.76,
                linkDistance: 120,
                linkStrength: 0.32,
                centerStrength: 0.24,
                baseNodeRadius: 4.2,
                collideRadius: 1.3,
                linkThickness: 1.1
            ),
            showsSettings: showsSettings
        )
    }

    static let emptyState = KnowledgeGraphPresenter.State(
        emptyState: .init(
            title: "知識圖譜為空",
            systemImage: "point.3.connected.trianglepath.dotted",
            description: "知識庫中尚無單字，或尚未與伺服器同步。"
        ),
        nodes: [],
        edges: [],
        graphTheme: KnowledgeGraphPresentation.theme(for: .previewNeutral),
        forces: GraphForces(
            repel: 0.76,
            linkDistance: 120,
            linkStrength: 0.32,
            centerStrength: 0.24,
            baseNodeRadius: 4.2,
            collideRadius: 1.3,
            linkThickness: 1.1
        ),
        showsSettings: false
    )
}

#Preview("Knowledge Graph / Settings") {
    AppThemeContainer {
        KnowledgeGraphPresenterPreviewHarness(
            state: KnowledgeGraphPresenterPreviewData.state(showsSettings: true)
        )
    }
}

#Preview("Knowledge Graph / Empty") {
    AppThemeContainer {
        KnowledgeGraphPresenterPreviewHarness(
            state: KnowledgeGraphPresenterPreviewData.emptyState
        )
    }
}
