import SwiftUI

struct KnowledgeGraphPresenter: View {
    @ObserveInjection private var inject
    struct ForceBindings {
        let centerForce: Binding<Double>
        let repelForce: Binding<Double>
        let linkForce: Binding<Double>
        let linkDistance: Binding<Double>
        let nodeSize: Binding<Double>
        let linkThickness: Binding<Double>
        let showsIsolatedNodes: Binding<Bool>
    }

    struct State {
        struct EmptyState {
            let title: String
            let systemImage: String
            let description: String
            let action: AppEmptyStateAction?

            init(title: String, systemImage: String, description: String, action: AppEmptyStateAction? = nil) {
                self.title = title
                self.systemImage = systemImage
                self.description = description
                self.action = action
            }
        }

        let emptyState: EmptyState?
        let nodes: [KnowledgeGraphNode]
        let edges: [KnowledgeGraphEdge]
        let graphTheme: KnowledgeGraphTheme
        let forces: GraphForces
        let showsSettings: Bool
    }

    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.appSkin) private var appSkin

    let state: State
    let bindings: ForceBindings
    let onToggleSettings: () -> Void
    let onResetForces: () -> Void
    let onNodeTapped: (String) -> Void

    var body: some View {
        VocabSceneShell(phase: graphScenePhase) {
            ZStack {
                appSkin.palette.pageBackground.ignoresSafeArea()

                ZStack(alignment: .bottom) {
                    graphView

                    VStack {
                        HStack {
                            Spacer()
                            graphLegend
                                .padding(.trailing, appSkin.metrics.overlayDrawerHorizontalInset)
                                .padding(.top, appSkin.spacing.microGap)
                        }
                        Spacer()
                    }

                    if state.showsSettings {
                        settingsOverlay
                            .transition(.readerPanelReveal)
                    }
                }
                .animateSpring(state.showsSettings)
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button(action: onToggleSettings) {
                            VocabToolbarGlyph(
                                systemImage: state.showsSettings ? "xmark.circle.fill" : "slider.horizontal.3"
                            )
                        }
                    }
                }
            }
        }
        .animation(AppMotion.contentFade, value: state.emptyState == nil)
        .enableInjection()
    }

    private var graphScenePhase: VocabScenePhase {
        if let emptyState = state.emptyState {
            return .empty(
                title: emptyState.title,
                systemImage: emptyState.systemImage,
                description: emptyState.description,
                action: emptyState.action
            )
        }
        return .content
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
                    title: KnowledgeGraphCopy.settingsTitle,
                    systemImage: "point.3.connected.trianglepath.dotted",
                    onClose: onToggleSettings,
                    leadingAccessory: {
                        VocabInlineActionButton(title: KnowledgeGraphCopy.resetTitle, action: onResetForces)
                    }
                )

                Divider().padding(.horizontal, appSkin.metrics.overlayCompactDividerInset)

                VStack(spacing: 0) {
                    VStack(spacing: 0) {
                        VocabSectionHeader(title: KnowledgeGraphCopy.forcesSectionTitle)
                            .padding(.bottom, appSkin.spacing.microGap)
                        VocabSliderRow(label: KnowledgeGraphCopy.centerForceTitle, value: bindings.centerForce, range: 0...1, format: "%.2f")
                        VocabSliderRow(label: KnowledgeGraphCopy.repelForceTitle, value: bindings.repelForce, range: 0...1, format: "%.2f")
                        VocabSliderRow(label: KnowledgeGraphCopy.linkForceTitle, value: bindings.linkForce, range: 0...1, format: "%.2f")
                        VocabSliderRow(label: KnowledgeGraphCopy.linkDistanceTitle, value: bindings.linkDistance, range: 20...300, format: "%.0f")
                    }

                    CardSectionDivider(horizontalPadding: 0)
                        .padding(.vertical, appSkin.spacing.sectionGap)

                    VStack(spacing: 0) {
                        VocabSectionHeader(title: KnowledgeGraphCopy.displaySectionTitle)
                            .padding(.bottom, appSkin.spacing.microGap)
                        VocabSliderRow(label: KnowledgeGraphCopy.nodeSizeTitle, value: bindings.nodeSize, range: 1...10, format: "%.1f")
                        VocabSliderRow(label: KnowledgeGraphCopy.linkThicknessTitle, value: bindings.linkThickness, range: 0.5...3, format: "%.1f")

                        Toggle(isOn: bindings.showsIsolatedNodes) {
                            Text(KnowledgeGraphCopy.isolatedNodesTitle)
                                .font(appSkin.typography.caption)
                                .foregroundStyle(appSkin.palette.primaryText)
                        }
                        .toggleStyle(.switch)
                        .tint(appSkin.palette.accent)
                        .padding(.top, appSkin.spacing.microGap)
                    }
                }
                .padding(.horizontal, appSkin.metrics.listRowHorizontalInset)
                .padding(.bottom, appSkin.metrics.graphDrawerBottomInset)
            }
        }
        .frame(maxWidth: 420)
        .padding(.horizontal, appSkin.metrics.overlayDrawerHorizontalInset)
        .padding(.bottom, appSkin.metrics.overlayDrawerBottomInset)
    }

    private var graphLegend: some View {
        VStack(alignment: .trailing, spacing: appSkin.spacing.tinyGap) {
            ReviewGradientBar()
                .frame(width: 100, height: 5)
                .clipShape(Capsule(style: .continuous))

            HStack(spacing: 0) {
                Text(KnowledgeGraphCopy.safeTitle)
                    .foregroundStyle(ReviewGradient.color(for: 0))
                Spacer()
                Text(KnowledgeGraphCopy.dueTitle)
                    .foregroundStyle(ReviewGradient.color(for: 1.0))
                Spacer()
                Text(KnowledgeGraphCopy.overdueTitle)
                    .foregroundStyle(ReviewGradient.color(for: 2.5))
            }
            .font(appSkin.typography.monoLabel)
            .frame(width: 100)

            HStack(spacing: appSkin.spacing.tinyGap) {
                Circle()
                    .fill(appSkin.palette.quaternaryText.opacity(0.5))
                    .frame(width: 6, height: 6)
                Text(KnowledgeGraphCopy.unlearnedArchivedTitle)
                    .font(appSkin.typography.monoLabel)
                    .foregroundStyle(appSkin.palette.quaternaryText)
            }
        }
        .padding(.horizontal, appSkin.spacing.inlineGap)
        .padding(.vertical, appSkin.spacing.microGap)
        .background(
            RoundedRectangle(cornerRadius: appSkin.radii.chip, style: .continuous)
                .fill(appSkin.palette.cardBackground.opacity(0.85))
                .overlay(
                    RoundedRectangle(cornerRadius: appSkin.radii.chip, style: .continuous)
                        .stroke(appSkin.palette.cardBorder, lineWidth: 1)
                )
        )
    }

}

struct KnowledgeGraphPresenterPreviewHarness: View {
    @State private var centerForce = 0.24
    @State private var repelForce = 0.76
    @State private var linkForce = 0.32
    @State private var linkDistance = 120.0
    @State private var nodeSize = 4.2
    @State private var linkThickness = 1.1
    @State private var showsIsolatedNodes = false

    let state: KnowledgeGraphPresenter.State

    private var bindings: KnowledgeGraphPresenter.ForceBindings {
        .init(
            centerForce: $centerForce,
            repelForce: $repelForce,
            linkForce: $linkForce,
            linkDistance: $linkDistance,
            nodeSize: $nodeSize,
            linkThickness: $linkThickness,
            showsIsolatedNodes: $showsIsolatedNodes
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

enum KnowledgeGraphPresenterPreviewData {
    static let sampleNodes = [
        KnowledgeGraphNode(id: "1", word: "subtle", tier: "gradient", colorHex: ReviewGradient.cssHex(for: 0.2), ratio: 0.2, degree: 3),
        KnowledgeGraphNode(id: "2", word: "nuance", tier: "gradient", colorHex: ReviewGradient.cssHex(for: 2.0), ratio: 2.0, degree: 2),
        KnowledgeGraphNode(id: "3", word: "precise", tier: "gradient", colorHex: ReviewGradient.cssHex(for: 0.7), ratio: 0.7, degree: 2)
    ]

    static let sampleEdges = [
        KnowledgeGraphEdge(id: "e1", from: "1", to: "2", kind: "contrasts_with"),
        KnowledgeGraphEdge(id: "e2", from: "2", to: "3", kind: "shares_usage")
    ]

    static func state(showsSettings: Bool) -> KnowledgeGraphPresenter.State {
        let skin = AppSkin.previewNeutral
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
            title: KnowledgeGraphCopy.emptyGraphTitle,
            systemImage: "point.3.connected.trianglepath.dotted",
            description: KnowledgeGraphCopy.emptyGraphDescription
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

    static let noLinksState = KnowledgeGraphPresenter.State(
        emptyState: .init(
            title: KnowledgeGraphCopy.noLinksTitle,
            systemImage: "point.3.connected.trianglepath.dotted",
            description: KnowledgeGraphCopy.noLinksDescription
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
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("Knowledge Graph / Empty") {
    AppThemeContainer {
        KnowledgeGraphPresenterPreviewHarness(
            state: KnowledgeGraphPresenterPreviewData.emptyState
        )
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("Knowledge Graph / No Links") {
    AppThemeContainer {
        KnowledgeGraphPresenterPreviewHarness(
            state: KnowledgeGraphPresenterPreviewData.noLinksState
        )
    }
    .environmentObject(AppAppearanceStore.preview)
}
