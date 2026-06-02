//
//  PanelHost.swift
//  BooksBrowser
//
//  集中 resolver — PanelKind 封閉 enum → 引擎 core 不 import feature view。
//  vocab 分支(Phase 4)經 env 注入的 entries 反查 live VocabularyEntry;
//  podcast 分支(Phase 3)經既有 service env 以 remoteId 反查。
//

import SwiftUI

struct PanelHost: View {
    let kind: PanelKind
    let proxy: PanelProxy

    @Environment(\.panelVocabEntries) private var entries
    @Environment(\.authManager) private var authManager

    var body: some View {
        switch kind {
        case .podcastSeries(let remoteID):
            // 集數列表（list-only）。NavigationStack 為 depth-0 host(follow toggle toolbar)，
            // 永不 push(集數 tap 開 sibling 子欄)→ 不重現 413912b3 remount。
            NavigationStack {
                PodcastEpisodeListView(
                    seriesId: remoteID,
                    onSelectEpisode: { proxy.openChildColumn(.podcastEpisode(remoteID: $0)) }
                )
            }
        case .podcastEpisode(let remoteID):
            PodcastPlayerView(episodeId: remoteID, wrapInNavigation: true)

        // Phase 4 接 vocab。
        default:
            Color.clear
        }
    }
}
