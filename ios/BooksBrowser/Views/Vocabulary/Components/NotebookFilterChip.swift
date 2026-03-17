//
//  NotebookFilterChip.swift
//  BooksBrowser
//
//  單字本篩選 chip — 複習和統計頁共用

import SwiftUI
import SwiftData

struct NotebookFilterChip: View {
    @Binding var filter: NotebookFilter
    @Query(sort: \Notebook.sortOrder) private var notebooks: [Notebook]
    @Environment(\.vocabSkin) private var skin

    @State private var showPicker = false

    var body: some View {
        Button {
            showPicker = true
        } label: {
            HStack(spacing: skin.spacing.microGap) {
                Image(systemName: filter.isFiltered ? "line.3.horizontal.decrease.circle.fill" : "line.3.horizontal.decrease.circle")
                    .font(skin.typography.caption)
                Text(chipLabel)
                    .font(skin.typography.caption)
            }
            .foregroundStyle(filter.isFiltered ? skin.palette.accent : skin.palette.secondaryText)
            .padding(.horizontal, skin.spacing.chipHorizontalPadding)
            .padding(.vertical, skin.spacing.chipVerticalPadding)
            .background(
                filter.isFiltered ? skin.palette.accent.opacity(0.12) : skin.palette.mutedFill,
                in: RoundedRectangle(cornerRadius: skin.radii.chip)
            )
        }
        .sheet(isPresented: $showPicker) {
            NotebookPickerSheet(
                filter: $filter,
                notebooks: notebooks.filter { !$0.isDeleted }
            )
        }
    }

    private var chipLabel: String {
        if !filter.isFiltered {
            return "全部單字本".localized
        }
        let count = filter.selectedIds.count
        if count == 1, let id = filter.selectedIds.first,
           let nb = notebooks.first(where: { $0.remoteId == id }) {
            return nb.name
        }
        return L10n.format("已選 %@ 本", "\(count)")
    }
}

// MARK: - Picker Sheet

struct NotebookPickerSheet: View {
    @Binding var filter: NotebookFilter
    let notebooks: [Notebook]

    @Environment(\.dismiss) private var dismiss
    @Environment(\.vocabSkin) private var skin

    var body: some View {
        NavigationStack {
            List {
                Button {
                    filter.selectedIds = []
                    filter.save()
                } label: {
                    HStack {
                        Text("全部單字本".localized)
                            .foregroundStyle(skin.palette.primaryText)
                        Spacer()
                        if !filter.isFiltered {
                            Image(systemName: "checkmark")
                                .foregroundStyle(skin.palette.accent)
                        }
                    }
                }

                ForEach(notebooks) { notebook in
                    Button {
                        toggleNotebook(notebook.remoteId)
                    } label: {
                        HStack {
                            if let hex = notebook.color {
                                Circle()
                                    .fill(Color(hex: hex) ?? skin.palette.accent)
                                    .frame(width: 12, height: 12)
                            }
                            Text(notebook.name)
                                .foregroundStyle(skin.palette.primaryText)
                            Spacer()
                            if filter.selectedIds.contains(notebook.remoteId) {
                                Image(systemName: "checkmark")
                                    .foregroundStyle(skin.palette.accent)
                            }
                        }
                    }
                }
            }
            .navigationTitle("篩選單字本".localized)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完成".localized) { dismiss() }
                }
            }
        }
        .presentationDetents([.medium])
    }

    private func toggleNotebook(_ id: String) {
        if filter.selectedIds.contains(id) {
            filter.selectedIds.remove(id)
        } else {
            filter.selectedIds.insert(id)
        }
        filter.save()
    }
}
