//
//  NotebookDetailPresentation.swift
//  BooksBrowser
//
//  NotebookListView 的 detail/review 呈現分支 — 唯一的 today-review
//  呈現入口（見 TodayReviewPhaseView 註解）。
//  - inline mode（iPad / Mac）：右側 safeAreaInset 可拖拉 panel
//  - sheet mode（iPhone）：toastSheet + platformFullScreenCover
//

import SwiftUI

struct NotebookDetailPresentation: ViewModifier {
    let detailState: DetailRouter
    let layoutMode: LayoutMode
    let allEntries: [VocabularyEntry]
    let currentUserID: String?
    @Binding var isEditingDetailEntry: Bool
    @Binding var navigationPath: NavigationPath

    @AppStorage("kg_detail_panel_width") private var panelWidth: Double = Double(MacDetailPanelMetrics.defaultWidth)
    @State private var dragWidth: CGFloat?
    @State private var containerWidth: CGFloat = 800

    private var effectivePanelWidth: CGFloat {
        let desired = CGFloat(panelWidth)
        let maxAllowed = containerWidth - MacDetailPanelMetrics.leftMinWidth
        return min(desired, max(maxAllowed, MacDetailPanelMetrics.minWidth))
    }

    func body(content: Content) -> some View {
        Group {
            if layoutMode.usesInlineDetail {
                content
                    .safeAreaInset(edge: .trailing, spacing: 0) {
                        if detailState.hasDetail {
                            HStack(spacing: 0) {
                                DraggableDivider(
                                    panelWidth: Binding(
                                        get: { CGFloat(panelWidth) },
                                        set: { panelWidth = Double($0) }
                                    ),
                                    dragWidth: $dragWidth,
                                    containerWidth: containerWidth,
                                    onDoubleClick: {
                                        withAnimation(AppMotion.standardSpring) {
                                            panelWidth = Double(MacDetailPanelMetrics.defaultWidth)
                                        }
                                    }
                                )
                                inlineDetailPanel
                                    .frame(width: dragWidth ?? effectivePanelWidth)
                            }
                            .transition(.drawerReveal)
                        }
                    }
                    .animation(AppMotion.standardSpring, value: detailState.hasDetail)
                    .onGeometryChange(for: CGFloat.self) { geo in
                        geo.size.width
                    } action: { newWidth in
                        containerWidth = newWidth
                    }
                    .onAppear { dragWidth = nil }
                    .onChange(of: navigationPath) { _, path in
                        if path.isEmpty { detailState.dismiss() }
                    }
                    .onChange(of: detailState.selectedEntry?.id) { _, entryID in
                        if entryID == nil { isEditingDetailEntry = false }
                    }
                    .toastSheet(isPresented: Binding(
                        get: { isEditingDetailEntry && detailState.selectedEntry != nil },
                        set: { isEditingDetailEntry = $0 }
                    )) {
                        if let entry = detailState.selectedEntry {
                            WordEditSheet(entry: entry)
                        }
                    }
            } else {
                content
                    .toastSheet(item: Binding(
                        get: { detailState.selectedEntry },
                        set: { if $0 == nil { detailState.dismiss() } }
                    )) { entry in
                        WordDetailSheet(entry: entry, allEntries: detailState.contextEntries)
                            .appSheet(.large)
                    }
                    .platformFullScreenCover(item: Binding(
                        get: { detailState.activeReviewSession },
                        set: { if $0 == nil { detailState.dismiss() } }
                    )) { session in
                        TodayReviewPhaseView(
                            session: session,
                            allEntries: detailState.contextEntries.isEmpty ? allEntries : detailState.contextEntries,
                            currentUserID: currentUserID,
                            onClose: { detailState.dismiss() }
                        )
                        .toastOverlay()
                    }
            }
        }
        .onChange(of: layoutMode) { _, newMode in
            if !newMode.usesInlineDetail {
                detailState.dismiss()
                isEditingDetailEntry = false
            }
        }
    }

    @ViewBuilder
    private var inlineDetailPanel: some View {
        if let session = detailState.activeReviewSession {
            TodayReviewPhaseView(
                session: session,
                allEntries: detailState.contextEntries.isEmpty ? allEntries : detailState.contextEntries,
                currentUserID: currentUserID,
                onClose: { detailState.dismiss() }
            )
        } else if let entry = detailState.selectedEntry {
            VStack(spacing: 0) {
                VocabOverlayHeader(
                    title: entry.word,
                    systemImage: "character.book.closed",
                    onClose: { detailState.dismiss() },
                    trailing: {
                        VocabChromeIconButton(
                            systemImage: "pencil",
                            label: "編輯".localized,
                            action: { isEditingDetailEntry = true }
                        )
                    }
                )
                WordDetailSheet(
                    entry: entry,
                    allEntries: detailState.contextEntries,
                    wrapInNavigation: false,
                    showsInlineChrome: false
                )
            }
        }
    }
}
