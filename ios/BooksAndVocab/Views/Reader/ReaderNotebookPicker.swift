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
                // 跟隨全域設定
                Section {
                    followGlobalRow
                }

                // Notebook 列表
                Section {
                    ForEach(notebooks) { notebook in
                        notebookRow(notebook)
                    }
                } header: {
                    Text("單字本".localized)
                        .font(AppFonts.caption(weight: .medium))
                }
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

    private var followGlobalRow: some View {
        Button {
            book.preferredNotebookId = nil
            persistBookBinding()
            dismiss()
        } label: {
            HStack(spacing: AppSpacing.s2) {
                Image(systemName: "globe")
                    .font(AppFonts.subhead())
                    .foregroundStyle(theme.palette.secondaryText)
                    .frame(width: AppSpacing.s6)

                VStack(alignment: .leading, spacing: AppSpacing.microGap) {
                    Text("跟隨全域設定".localized)
                        .font(AppFonts.body())
                        .foregroundStyle(theme.palette.primaryText)
                        .lineLimit(1)
                        .truncationMode(.tail)

                    Text("使用目前選定的單字本".localized)
                        .font(AppFonts.caption())
                        .foregroundStyle(theme.palette.tertiaryText)
                        .lineLimit(1)
                        .truncationMode(.tail)
                }

                Spacer()

                selectionCheckmark(isSelected: book.preferredNotebookId == nil)
            }
            .contentShape(Rectangle())
        }
    }

    private func notebookRow(_ notebook: Notebook) -> some View {
        Button {
            book.preferredNotebookId = notebook.remoteId
            persistBookBinding()
            dismiss()
        } label: {
            HStack(spacing: AppSpacing.s2) {
                RoundedRectangle(cornerRadius: AppRadius.xs)
                    .fill(notebook.color.flatMap { Color(hex: $0) } ?? theme.palette.accent) // token-allow: user notebook data color
                    .frame(width: 4, height: AppSpacing.s7)

                VStack(alignment: .leading, spacing: AppSpacing.microGap) {
                    Text(notebook.name)
                        .font(AppFonts.body())
                        .foregroundStyle(theme.palette.primaryText)
                        .lineLimit(1)
                        .truncationMode(.tail)

                    if notebook.isDefault {
                        Text("預設".localized)
                            .font(AppFonts.caption())
                            .foregroundStyle(theme.palette.tertiaryText)
                    }
                }

                Spacer()

                selectionCheckmark(isSelected: book.preferredNotebookId == notebook.remoteId)
            }
            .contentShape(Rectangle())
        }
    }

    @ViewBuilder
    private func selectionCheckmark(isSelected: Bool) -> some View {
        if isSelected {
            Image(systemName: "checkmark")
                .font(AppFonts.subhead(weight: .semibold))
                .foregroundStyle(theme.palette.accent)
        }
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
