//
//  PodcastSeriesActivation.swift
//  BooksBrowser
//
//  Series 卡片點選的 layout-aware 決策。
//  - regular (Mac/iPad)：`.selectInline` → BookshelfView 以 `panelWorkspace.openColumn`
//    開 series 子欄（2D workspace Miller column）。
//  - compact (iPhone)：`.push` → value-based NavigationLink push（行為不變）。
//

import Foundation

enum PodcastSeriesActivation: Equatable {
    case selectInline(seriesRemoteId: String)
    case push(route: PodcastNavRoute)

    static func activation(
        seriesRemoteId: String,
        layoutMode: LayoutMode
    ) -> PodcastSeriesActivation {
        layoutMode.usesInlineDetail
            ? .selectInline(seriesRemoteId: seriesRemoteId)
            : .push(route: .series(seriesRemoteId: seriesRemoteId))
    }
}
