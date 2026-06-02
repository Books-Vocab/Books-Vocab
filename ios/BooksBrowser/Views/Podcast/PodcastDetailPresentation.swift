//
//  PodcastDetailPresentation.swift
//  BooksBrowser
//
//  Podcast 集數列表的 detail 呈現分支，鏡射 NotebookDetailPresentation：
//  - inline mode（iPad / Mac regular）：右側 safeAreaInset 可拖拉 panel，
//    掛單一 PodcastPlayerView，靠其 .task(id:) swap 集數。
//  - compact（iPhone）：右欄不掛，沿用 episodesSection 的 NavigationLink push。
//
//  刻意偏離 vocab（後者用 WordDetailSheet wrapInNavigation:false + 自製 header，
//  不嵌套 NavigationStack）：此處為 host player 既有 ToolbarItem(.topBarTrailing)
//  設定鍵，傳 wrapInNavigation:true，由 player 自帶 NavigationStack。
//

import SwiftUI

struct PodcastDetailPresentation: ViewModifier {
    let router: PodcastDetailRouter
    let layoutMode: LayoutMode

    @AppStorage("kg_podcast_panel_width") private var panelWidth: Double = Double(MacDetailPanelMetrics.defaultWidth)
    @State private var dragWidth: CGFloat?
    @State private var containerWidth: CGFloat = 800

    private var effectivePanelWidth: CGFloat {
        let desired = CGFloat(panelWidth)
        let maxAllowed = containerWidth - MacDetailPanelMetrics.leftMinWidth
        return min(desired, max(maxAllowed, MacDetailPanelMetrics.minWidth))
    }

    func body(content: Content) -> some View {
        Group {
            if layoutMode.usesInlineDetail {
                content
                    .safeAreaInset(edge: .trailing, spacing: 0) {
                        if router.hasDetail, let id = router.selectedEpisodeRemoteId {
                            HStack(spacing: 0) {
                                DraggableDivider(
                                    panelWidth: Binding(
                                        get: { CGFloat(panelWidth) },
                                        set: { panelWidth = Double($0) }
                                    ),
                                    dragWidth: $dragWidth,
                                    containerWidth: containerWidth,
                                    onDoubleClick: {
                                        withAnimation(AppMotion.standardSpring) {
                                            panelWidth = Double(MacDetailPanelMetrics.defaultWidth)
                                        }
                                    }
                                )
                                PodcastPlayerView(episodeId: id, wrapInNavigation: true)  // 唯一傳 true 處
                                    .frame(width: dragWidth ?? effectivePanelWidth)
                            }
                            .transition(.drawerReveal)
                        }
                    }
                    .animation(AppMotion.standardSpring, value: router.hasDetail)
                    .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { containerWidth = $0 }
                    .onAppear { dragWidth = nil }
            } else {
                content  // compact：右欄不掛，沿用 NavigationLink push
            }
        }
        .onChange(of: layoutMode) { _, newMode in
            if !newMode.usesInlineDetail { router.dismiss() }
        }
    }
}

extension View {
    func podcastDetailPresentation(router: PodcastDetailRouter, layoutMode: LayoutMode) -> some View {
        modifier(PodcastDetailPresentation(router: router, layoutMode: layoutMode))
    }
}
