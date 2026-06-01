//
//  PodcastDetailRouter.swift
//  BooksBrowser
//
//  Podcast 集數 master-detail 路由 — regular 雙欄右欄選定的 episode。
//  鏡射 DetailRouter，但僅持有 selection（player 狀態由 PodcastPlayerView
//  自身的 .task(id:) 管理，不在此）。
//

import SwiftUI

enum PodcastEpisodeActivation: Equatable {
    case inlineDetail(episodeRemoteId: String)
    case push(route: PodcastNavRoute)

    static func activation(
        episodeRemoteId: String,
        layoutMode: LayoutMode
    ) -> PodcastEpisodeActivation {
        layoutMode.usesInlineDetail
            ? .inlineDetail(episodeRemoteId: episodeRemoteId)
            : .push(route: .episode(episodeRemoteId: episodeRemoteId))
    }
}

@Observable @MainActor
final class PodcastDetailRouter {
    var selectedEpisodeRemoteId: String?

    var hasDetail: Bool { selectedEpisodeRemoteId != nil }

    func show(episodeRemoteId: String) {
        selectedEpisodeRemoteId = episodeRemoteId
    }

    func dismiss() {
        selectedEpisodeRemoteId = nil
    }
}

// MARK: - Environment Key

private struct PodcastDetailRouterKey: EnvironmentKey {
    static let defaultValue: PodcastDetailRouter? = nil
}

extension EnvironmentValues {
    var podcastDetailRouter: PodcastDetailRouter? {
        get { self[PodcastDetailRouterKey.self] }
        set { self[PodcastDetailRouterKey.self] = newValue }
    }
}
