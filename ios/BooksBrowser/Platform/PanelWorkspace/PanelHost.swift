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

        case .wordDetail(let entryID), .linkedWord(let entryID):
            // entry-id 反查 live VocabularyEntry（由 vocab section wrapper 注入 entries）。
            // BlockChrome 提供 ✕；showsInlineChrome:false 不重複 header。
            if let entry = entries.first(where: { $0.id == entryID }) {
                WordDetailSheet(
                    entry: entry,
                    allEntries: entries,
                    wrapInNavigation: false,
                    showsInlineChrome: false,
                    onClose: { proxy.closeSelf() }
                )
            } else {
                Color.clear   // entry 已刪 → fallback
            }

        case .reviewSession(let entryIDs):
            ReviewPanel(
                entryIDs: entryIDs,
                allEntries: entries,
                currentUserID: authManager.userId,
                onClose: { proxy.closeSelf() }
            )
        }
    }
}
