//
//  VocabularyListView+Sheets.swift
//  BooksBrowser
//

import SwiftUI

struct VocabularyListSheets: ViewModifier {
    @Bindable var coordinator: VocabularyListCoordinator
    let allEntries: [VocabularyEntry]
    let sizeClass: UserInterfaceSizeClass?

    func body(content: Content) -> some View {
        content
            .toastSheet(isPresented: $coordinator.showSyncView) {
                SyncView()
            }
            .toastSheet(isPresented: $coordinator.showSettings) {
                SettingsView()
            }
            .toastSheet(item: $coordinator.exportURL) { url in
                PlatformShareView(url: url)
            }
    }
}

// MARK: - URL Identifiable

extension URL: @retroactive Identifiable {
    public var id: String { absoluteString }
}
