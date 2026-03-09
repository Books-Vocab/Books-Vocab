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
            } else {
                ZStack(alignment: .bottom) {
                    graphView

                    if state.showsSettings {
                        settingsOverlay
                            .transition(.move(edge: .bottom).combined(with: .opacity))
                    }
                }
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

                        Divider().padding(.horizontal, 8)

                        VStack(spacing: 0) {
                            VocabSectionHeader(title: "力")
                            VocabSliderRow(label: "向心力", value: bindings.centerForce, range: 0...1, format: "%.2f")
                            VocabSliderRow(label: "排斥力", value: bindings.repelForce, range: 0...1, format: "%.2f")
                            VocabSliderRow(label: "連結強度", value: bindings.linkForce, range: 0...1, format: "%.2f")
                            VocabSliderRow(label: "連結距離", value: bindings.linkDistance, range: 20...300, format: "%.0f")

                            Divider().padding(.vertical, 6)

                            VocabSectionHeader(title: "顯示")
                            VocabSliderRow(label: "節點大小", value: bindings.nodeSize, range: 1...10, format: "%.1f")
                            VocabSliderRow(label: "連結粗細", value: bindings.linkThickness, range: 0.5...3, format: "%.1f")
                        }
                        .padding(.horizontal, 16)
                        .padding(.bottom, 12)
                    }
        }
        .frame(maxWidth: 420)
        .padding(.horizontal, 12)
        .padding(.bottom, 8)
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
        .padding(20)
    }
}
