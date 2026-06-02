//
//  VocabWorkspaceSection.swift
//  BooksBrowser
//
//  Catalyst/iPad section wrapper — 在 container 層持 PanelWorkspace + 注入 live
//  entries（panel 是 NotebookListView root 的 sibling，讀不到其 @Query）。
//  allEntries predicate 與 NotebookListView 一致（knowledge entries）。
//  compact (iPhone) 走 ContentView 的 TabView 直接用 NotebookListView，不經此。
//

import SwiftUI
import SwiftData

struct VocabWorkspaceSection: View {
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Query private var allEntries: [VocabularyEntry]

    @State private var workspace = PanelWorkspace()

    init() {
        // predicate 在 init 內建（鏡射 NotebookListView）避免 @Query 屬性 inline
        // #Predicate 的型別檢查爆炸。
        let knowledgePredicate = #Predicate<VocabularyEntry> {
            $0.syncStatus == 1 && $0.actionType != "delete" && $0.isArchived == false
        }
        _allEntries = Query(filter: knowledgePredicate, sort: \.dateAdded, order: .reverse)
    }

    private var layoutMode: LayoutMode { LayoutMode(horizontalSizeClass: sizeClass) }

    var body: some View {
        PanelWorkspaceContainer(workspace: workspace, layoutMode: layoutMode) {
            NotebookListView()
        }
        .environment(\.panelVocabEntries, allEntries)
        .environment(\.panelWorkspace, workspace)
    }
}
