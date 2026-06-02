//
//  PodcastDetailRouter.swift
//  BooksBrowser
//
//  Podcast 路由 activation 決策。
//
//  episode-list → player 曾在 regular layout 走右欄 inline detail（雙欄）；
//  該分支已收斂成單欄 push：tap episode 一律把 `PodcastPlayerView` push 上
//  BookshelfView 的 NavigationStack（`PodcastNavRoute.episode`），所有 layout
//  皆然。`PodcastEpisodeActivation.activation` 因此恆回 `.push`，inline 分支、
//  其驅動的 `PodcastDetailRouter` selection state、`PodcastDetailPresentation`
//  右欄 modifier 一併移除。
//
//  Series-layer 路由（`PodcastSeriesActivation`）維持原狀 — regular 下 series
//  仍以 root-level overlay master pane 呈現（見 BookshelfView `selectedSeriesRemoteId`），
//  不在本次收斂範圍。
//

import SwiftUI

enum PodcastEpisodeActivation: Equatable {
    case push(route: PodcastNavRoute)

    static func activation(
        episodeRemoteId: String,
        layoutMode: LayoutMode
    ) -> PodcastEpisodeActivation {
        .push(route: .episode(episodeRemoteId: episodeRemoteId))
    }
}

/// Series-layer activation, mirroring `PodcastEpisodeActivation`.
///
/// regular (Mac/iPad) does **not** push the episode list onto BookshelfView's
/// NavigationStack — instead `.selectInline` drives a `@State` selection that
/// renders `PodcastEpisodeListView` as a root-level master pane (depth=0), so
/// the trailing `safeAreaInset` player it carries can no longer remount/pop the
/// way a depth=1 push entry did (runtime-confirmed root cause; mirrors Notebook
/// `selectInline`). compact (iPhone) keeps the existing value-based push.
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
