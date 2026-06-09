//
//  NotebookFilterChip.swift
//  Books & Vocab
//
//  單字本篩選 chip — 複習和統計頁共用

import SwiftUI
import SwiftData
import Inject

struct NotebookFilterChip: View {
    @ObserveInjection private var inject
    @Binding var filter: NotebookFilter
    @Query(sort: \Notebook.sortOrder) private var notebooks: [Notebook]
    @Environment(\.appSkin) private var skin

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
                in: Capsule()
            )
        }
        .toastSheet(isPresented: $showPicker) {
            NotebookFilterPickerSheet(
                filter: $filter,
                notebooks: notebooks.filter { !$0.isSoftDeleted }
            )
        }
        .enableInjection()
    }

    private var chipLabel: String {
        if !filter.isFiltered {
            return L10n.string("全部單字本")
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

struct NotebookFilterPickerSheet: View {
    @ObserveInjection private var inject
    @Binding var filter: NotebookFilter
    let notebooks: [Notebook]

    @Environment(\.dismiss) private var dismiss
    @Environment(\.appSkin) private var skin

    var body: some View {
        NavigationStack {
            List {
                Button {
                    filter.selectedIds = []
                    filter.save()
                } label: {
                    HStack {
                        Text(L10n.string("全部單字本"))
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
                                    .fill(Color(hex: hex) ?? skin.palette.accent) // token-allow: user notebook data color
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
            .navigationTitle(L10n.string("篩選單字本"))
            .inlineNavigationBarTitle()
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button(L10n.string("完成")) { dismiss() }
                }
            }
        }
        .appSheet(.medium)
        .enableInjection()
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

#Preview("NotebookFilterChip") {
    @Previewable @State var filter = NotebookFilter()

    return AppThemeContainer {
        VStack(spacing: AppSpacing.s4) {
            NotebookFilterChip(filter: $filter)
            NotebookFilterChip(filter: .constant(NotebookFilter(selectedIds: ["nb-1", "nb-2"])))
        }
        .padding()
    }
    .environmentObject(AppAppearanceStore.preview)
    .modelContainer(for: [Notebook.self], inMemory: true)
}
