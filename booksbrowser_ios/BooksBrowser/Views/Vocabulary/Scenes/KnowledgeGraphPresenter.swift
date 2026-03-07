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
                    Button("重設", action: onResetForces)
                        .font(vocabSkin.typography.body)
                        .foregroundStyle(vocabSkin.palette.accent)
                        .buttonStyle(.plain)
                }

                Divider().padding(.horizontal, 8)

                VStack(spacing: 0) {
                    sectionHeader("力")
                    forceRow("向心力", value: bindings.centerForce, range: 0...1, fmt: "%.2f")
                    forceRow("排斥力", value: bindings.repelForce, range: 0...1, fmt: "%.2f")
                    forceRow("連結強度", value: bindings.linkForce, range: 0...1, fmt: "%.2f")
                    forceRow("連結距離", value: bindings.linkDistance, range: 20...300, fmt: "%.0f")

                    Divider().padding(.vertical, 6)

                    sectionHeader("顯示")
                    forceRow("節點大小", value: bindings.nodeSize, range: 1...10, fmt: "%.1f")
                    forceRow("連結粗細", value: bindings.linkThickness, range: 0.5...3, fmt: "%.1f")
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

    private func forceRow(
        _ label: String,
        value: Binding<Double>,
        range: ClosedRange<Double>,
        fmt: String
    ) -> some View {
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
}
