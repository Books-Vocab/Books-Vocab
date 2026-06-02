//
//  PodcastDetailPresentation.swift
//  BooksBrowser
//
//  Podcast 集數列表的 detail 呈現分支，鏡射 NotebookDetailPresentation：
//  - inline mode（iPad / Mac regular）：右側 safeAreaInset 可拖拉 panel，
//    掛單一 PodcastPlayerView，靠其 .task(id:) swap 集數。
//  - compact（iPhone）：右欄不掛，沿用 episodesSection 的 NavigationLink push。
//
//  與 vocab 一致：inline player **不**嵌套 NavigationStack。早期 inline 為了 host
//  player 的 .topBarTrailing 設定鍵而傳 wrapInNavigation:true 自帶 NavigationStack，
//  但該內層 stack 嵌在 BookshelfView 外層 NavigationStack subtree 內，會持久破壞
//  外層 reader push（NAVDBG 坐實，Catalyst SwiftUI 缺陷）。現 player 依 layout 自判
//  chrome：inline 設定鍵走 content overlay，不再需要 nav bar / 內層 stack。
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
                                // player 不再自帶內層 NavigationStack（過去的
                                // wrapInNavigation:true 會持久破壞 BookshelfView 外層
                                // NavigationStack 的 reader push — NAVDBG 坐實）。
                                // inline 設定鍵改由 player 自身 content overlay 呈現。
                                PodcastPlayerView(episodeId: id)
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
