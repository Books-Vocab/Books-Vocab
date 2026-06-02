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
        // Phase 3 接 podcast；Phase 4 接 vocab。骨架先回 placeholder 確保編譯。
        default:
            Color.clear
        }
    }
}
