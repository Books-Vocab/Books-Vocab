//
//  ContentView.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI

/// 主介面 — Tab 導航
struct ContentView: View {
    var body: some View {
        TabView {
            Tab("書庫", systemImage: "books.vertical") {
                BookshelfView()
            }
            Tab("生詞庫", systemImage: "character.book.closed") {
                VocabularyListView()
            }
            Tab("Demo", systemImage: "square.grid.2x2") {
                StyleDemoView()
            }
        }
    }
}

#Preview {
    ContentView()
        .modelContainer(for: [Book.self, VocabularyEntry.self], inMemory: true)
}
