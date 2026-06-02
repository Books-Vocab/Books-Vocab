//
//  BookshelfWorkspaceSection.swift
//  BooksBrowser
//
//  Catalyst/iPad section wrapper — 在 container 層持有 PanelWorkspace 並注入 env，
//  讓 BookshelfView（root master）與 podcast panel 子欄（sibling）共享同一 workspace。
//  僅由 ContentView 的 NavigationSplitView detail 分支（Catalyst）使用；compact
//  (iPhone) 的 TabView 直接用 BookshelfView，panelWorkspace 為 nil（走既有 push）。
//

import SwiftUI

struct BookshelfWorkspaceSection: View {
    @Environment(\.horizontalSizeClass) private var sizeClass
    @State private var workspace = PanelWorkspace()

    private var layoutMode: LayoutMode { LayoutMode(horizontalSizeClass: sizeClass) }

    var body: some View {
        PanelWorkspaceContainer(workspace: workspace, layoutMode: layoutMode) {
            BookshelfView()
        }
        .environment(\.panelWorkspace, workspace)
    }
}
