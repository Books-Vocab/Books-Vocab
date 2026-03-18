import SwiftUI
import SwiftData

struct NotebookPickerSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.vocabSkin) private var vocabSkin
    @Query(sort: \Notebook.sortOrder) private var notebooks: [Notebook]

    let excludeNotebookId: String
    let onPick: (Notebook) -> Void

    private var availableNotebooks: [Notebook] {
        notebooks.filter { !$0.isDeleted && $0.remoteId != excludeNotebookId }
    }

    var body: some View {
        NavigationStack {
            Group {
                if availableNotebooks.isEmpty {
                    VStack {
                        Spacer()
                        VocabEmptyStateCard(
                            title: "沒有其他單字本".localized,
                            systemImage: "folder.badge.questionmark",
                            description: "請先建立新的單字本。".localized
                        )
                        Spacer()
                    }
                    .padding(vocabSkin.metrics.cardBlockPadding)
                } else {
                    List(availableNotebooks) { notebook in
                        Button {
                            onPick(notebook)
                            dismiss()
                        } label: {
                            HStack {
                                if let color = notebook.color {
                                    Circle()
                                        .fill(Color(hex: color) ?? vocabSkin.palette.accent)
                                        .frame(width: 12, height: 12)
                                }
                                Text(notebook.name)
                                    .font(vocabSkin.typography.body)
                                    .foregroundStyle(vocabSkin.palette.primaryText)
                                Spacer()
                            }
                        }
                    }
                    .listStyle(.plain)
                }
            }
            .navigationTitle("移動到...".localized)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消".localized) { dismiss() }
                }
            }
        }
    }
}
