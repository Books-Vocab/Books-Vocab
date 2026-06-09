#if os(iOS)
//
//  ReaderNotebookPicker.swift
//  Books & Vocab
//
//  閱讀器內選擇目標單字本 — 為當前書綁定或解除綁定 notebook

import SwiftUI
import SwiftData

struct ReaderNotebookPicker: View {
    @ObserveInjection private var inject
    @Bindable var book: Book

    @Query(
        filter: #Predicate<Notebook> { !$0.isSoftDeleted },
        sort: \Notebook.sortOrder
    )
    private var notebooks: [Notebook]

    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var modelContext
    @Environment(\.appTheme) private var theme
    @Environment(\.horizontalSizeClass) private var sizeClass

    var body: some View {
        let presentation = ReaderNotebookPickerPresentation(layoutMode: LayoutMode(horizontalSizeClass: sizeClass))

        return NavigationStack {
            List {
                // Notebook 列表（每本書必綁定恰好一本真實單字本，不提供「跟隨全域」）
                NotebookBindingList(
                    notebooks: notebooks,
                    selectedNotebookId: book.preferredNotebookId,
                    onSelect: { notebook in
                        book.preferredNotebookId = notebook.remoteId
                        persistBookBinding()
                        dismiss()
                    }
                )
            }
            .frame(maxWidth: presentation.contentMaxWidth)
            .padding(.horizontal, presentation.horizontalPadding)
            .frame(maxWidth: .infinity)
            .background(theme.palette.pageBackground.ignoresSafeArea())
            .navigationTitle("選擇單字本".localized)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成".localized) { dismiss() }
                        .font(AppFonts.subhead(weight: .semibold))
                }
            }
            .onAppear {
                sanitizeStaleBoundNotebook()
            }
        }
        .enableInjection()
    }

    /// 已刪除 notebook 防護：若綁定的 notebook 不在可用列表中，自動清除綁定
    private func sanitizeStaleBoundNotebook() {
        guard let boundId = book.preferredNotebookId else { return }
        let exists = notebooks.contains { $0.remoteId == boundId }
        if !exists {
            book.preferredNotebookId = nil
            persistBookBinding()
        }
    }

    private func persistBookBinding() {
        if modelContext.safeSave() {
            BookManifestStore().writeBestEffort(book: book)
        }
    }
}
#endif
