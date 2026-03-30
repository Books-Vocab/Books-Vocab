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
            .sheet(isPresented: $coordinator.showSyncView) {
                SyncView()
            }
            .sheet(isPresented: $coordinator.showSettings) {
                SettingsView()
            }
            .sheet(item: $coordinator.exportURL) { url in
                ShareSheet(url: url)
            }
            .sheet(item: $coordinator.selectedEntry) { entry in
                WordDetailSheet(entry: entry, allEntries: allEntries)
                    .appSheet(.large)
            }
            .fullScreenCover(item: Binding(
                get: { sizeClass == .compact ? coordinator.activeReviewSession : nil },
                set: { coordinator.activeReviewSession = $0 }
            )) { session in
                TodayReviewView(
                    entries: session.entries,
                    allEntries: allEntries,
                    currentUserID: AuthManager.shared.userId,
                    onClose: { coordinator.activeReviewSession = nil }
                )
            }
            .sheet(item: Binding(
                get: { sizeClass == .regular ? coordinator.activeReviewSession : nil },
                set: { coordinator.activeReviewSession = $0 }
            )) { session in
                TodayReviewView(
                    entries: session.entries,
                    allEntries: allEntries,
                    currentUserID: AuthManager.shared.userId,
                    onClose: { coordinator.activeReviewSession = nil }
                )
                .appSheet(.large)
            }
    }
}

// MARK: - ShareSheet

struct ShareSheet: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: [url], applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}

// MARK: - URL Identifiable

extension URL: @retroactive Identifiable {
    public var id: String { absoluteString }
}
