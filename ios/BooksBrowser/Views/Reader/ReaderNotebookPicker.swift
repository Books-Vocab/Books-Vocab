#if os(iOS)
//
//  ReaderNotebookPicker.swift
//  BooksBrowser
//
//  閱讀器內選擇目標單字本 — 為當前書綁定或解除綁定 notebook

import SwiftUI
import SwiftData

struct ReaderNotebookPicker: View {
    @Bindable var book: Book

    @Query(
        filter: #Predicate<Notebook> { !$0.isDeleted },
        sort: \Notebook.sortOrder
    )
    private var notebooks: [Notebook]

    @Environment(\.dismiss) private var dismiss
    @Environment(\.appTheme) private var theme

    var body: some View {
        NavigationStack {
            List {
                // 跟隨全域設定
                Section {
                    Button {
                        book.preferredNotebookId = nil
                        dismiss()
                    } label: {
                        HStack(spacing: AppMetrics.spacingSmall) {
                            Image(systemName: "globe")
                                .font(AppFonts.subhead())
                                .foregroundStyle(theme.palette.secondaryText)
                                .frame(width: AppMetrics.spacingLarge)

                            VStack(alignment: .leading, spacing: AppMetrics.spacingMicro) {
                                Text("跟隨全域設定".localized)
                                    .font(AppFonts.body())
                                    .foregroundStyle(theme.palette.primaryText)

                                Text("使用目前選定的單字本".localized)
                                    .font(AppFonts.caption())
                                    .foregroundStyle(theme.palette.tertiaryText)
                            }

                            Spacer()

                            if book.preferredNotebookId == nil {
                                Image(systemName: "checkmark")
                                    .font(AppFonts.subhead(weight: .semibold))
                                    .foregroundStyle(theme.palette.accent)
                            }
                        }
                        .contentShape(Rectangle())
                    }
                }

                // Notebook 列表
                Section {
                    ForEach(notebooks) { notebook in
                        Button {
                            book.preferredNotebookId = notebook.remoteId
                            dismiss()
                        } label: {
                            HStack(spacing: AppMetrics.spacingSmall) {
                                RoundedRectangle(cornerRadius: AppMetrics.spacingMicro)
                                    .fill(notebook.color.flatMap { Color(hex: $0) } ?? theme.palette.accent)
                                    .frame(width: 4, height: AppMetrics.spacingExtraLarge)

                                VStack(alignment: .leading, spacing: AppMetrics.spacingMicro) {
                                    Text(notebook.name)
                                        .font(AppFonts.body())
                                        .foregroundStyle(theme.palette.primaryText)

                                    if notebook.isDefault {
                                        Text("預設".localized)
                                            .font(AppFonts.caption())
                                            .foregroundStyle(theme.palette.tertiaryText)
                                    }
                                }

                                Spacer()

                                if book.preferredNotebookId == notebook.remoteId {
                                    Image(systemName: "checkmark")
                                        .font(AppFonts.subhead(weight: .semibold))
                                        .foregroundStyle(theme.palette.accent)
                                }
                            }
                            .contentShape(Rectangle())
                        }
                    }
                } header: {
                    Text("單字本".localized)
                        .font(AppFonts.caption(weight: .medium))
                }
            }
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
    }

    /// 已刪除 notebook 防護：若綁定的 notebook 不在可用列表中，自動清除綁定
    private func sanitizeStaleBoundNotebook() {
        guard let boundId = book.preferredNotebookId else { return }
        let exists = notebooks.contains { $0.remoteId == boundId }
        if !exists {
            book.preferredNotebookId = nil
        }
    }
}
#endif
