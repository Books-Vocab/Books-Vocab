import SwiftUI
import SwiftData

struct NotebookPickerSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.vocabSkin) private var vocabSkin
    @Query(sort: \Notebook.sortOrder) private var notebooks: [Notebook]

    let excludeNotebookId: String
    let onPick: (Notebook) -> Void

    @State private var errorMessage: String?

    private var availableNotebooks: [Notebook] {
        notebooks.filter { !$0.isDeleted && $0.remoteId != excludeNotebookId }
    }

    var body: some View {
        NavigationStack {
            Group {
                if let errorMessage {
                    VStack {
                        Spacer()
                        VocabStateMessageCard(
                            title: "發生錯誤".localized,
                            systemImage: "exclamationmark.triangle",
                            description: errorMessage
                        ) {
                            Button("重試".localized) {
                                self.errorMessage = nil
                            }
                            .buttonStyle(.vocabAction())
                        }
                        Spacer()
                    }
                    .padding(vocabSkin.metrics.cardBlockPadding)
                } else if availableNotebooks.isEmpty {
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
                            pickNotebook(notebook)
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

    private func pickNotebook(_ notebook: Notebook) {
        guard notebook.remoteId != excludeNotebookId, !notebook.isDeleted else {
            errorMessage = "此單字本無法使用".localized
            return
        }
        onPick(notebook)
        dismiss()
    }
}
