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
                #if os(iOS)
                ShareSheet(url: url)
                #elseif os(macOS)
                ShareLink(item: url)
                    .padding()
                #endif
            }
            // macOS: selectedEntry/review 透過 onChange → macInspector 上浮到 NotebookListView 的 inspector
            #if os(iOS)
            .toastSheet(item: $coordinator.selectedEntry) { entry in
                WordDetailSheet(entry: entry, allEntries: allEntries)
                    .appSheet(.large)
            }
            .platformFullScreenCover(item: Binding(
                get: { sizeClass == .compact ? coordinator.activeReviewSession : nil },
                set: { coordinator.activeReviewSession = $0 }
            )) { session in
                TodayReviewView(
                    entries: session.entries,
                    allEntries: allEntries,
                    currentUserID: AuthManager.shared.userId,
                    onClose: { coordinator.activeReviewSession = nil }
                )
                .toastOverlay()
            }
            .toastSheet(item: Binding(
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
            #endif
    }
}

// MARK: - ShareSheet

#if os(iOS)
struct ShareSheet: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: [url], applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}
#endif

// MARK: - URL Identifiable

extension URL: @retroactive Identifiable {
    public var id: String { absoluteString }
}
