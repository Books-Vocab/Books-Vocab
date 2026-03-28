import SwiftUI

struct WordEditSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var modelContext
    @Bindable var entry: VocabularyEntry

    @State private var draftTranslation = ""
    @State private var draftExplanation = ""
    @State private var isSaving = false
    @State private var saveError: String?

    var body: some View {
        NavigationStack {
            Form {
                if let saveError {
                    Section {
                        AppBanner(
                            message: saveError,
                            systemImage: "exclamationmark.triangle",
                            onRetry: { save() },
                            onDismiss: { self.saveError = nil }
                        )
                    }
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)
                }

                Section(header: Text("翻譯結果".localized)) {
                    TextEditor(text: $draftTranslation)
                        .frame(minHeight: 80)
                        .scrollContentBackground(.hidden)
                }

                Section(header: Text("教學筆記".localized)) {
                    TextEditor(text: $draftExplanation)
                        .frame(minHeight: 80)
                        .scrollContentBackground(.hidden)
                }
            }
            .navigationTitle(entry.word)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消".localized) { dismiss() }
                        .disabled(isSaving)
                }
                ToolbarItem(placement: .confirmationAction) {
                    if isSaving {
                        ProgressView()
                            .controlSize(.small)
                    } else {
                        Button("儲存".localized) { save() }
                            .fontWeight(.semibold)
                    }
                }
            }
        }
        .onAppear {
            draftTranslation = entry.translation
            draftExplanation = entry.explanation ?? ""
        }
    }

    private func save() {
        isSaving = true
        saveError = nil

        let trimmedExplanation = draftExplanation.trimmingCharacters(in: .whitespacesAndNewlines)

        entry.translation = draftTranslation.trimmingCharacters(in: .whitespacesAndNewlines)
        entry.explanation = trimmedExplanation.isEmpty ? nil : trimmedExplanation

        if entry.isSynced {
            entry.syncAction = .edit
            entry.syncState = .pending
        }

        do {
            try modelContext.save()
            dismiss()
        } catch {
            saveError = "儲存失敗，請再試一次".localized
            isSaving = false
        }
    }
}
