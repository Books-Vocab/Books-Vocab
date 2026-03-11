import SwiftUI

struct WordEditSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Bindable var entry: VocabularyEntry

    @State private var draftTranslation = ""
    @State private var draftPronunciation = ""
    @State private var draftExplanation = ""

    var body: some View {
        NavigationStack {
            Form {
                Section(header: Text("翻譯結果".localized)) {
                    TextEditor(text: $draftTranslation)
                        .frame(minHeight: 80)
                        .scrollContentBackground(.hidden)
                }

                Section(header: Text("音標".localized)) {
                    TextField("e.g. ˈwɜːrd", text: $draftPronunciation)
                        .font(.system(.body, design: .monospaced))
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
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
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("儲存".localized) { save() }
                        .fontWeight(.semibold)
                }
            }
        }
        .onAppear {
            draftTranslation = entry.translation
            draftPronunciation = entry.pronunciation ?? ""
            draftExplanation = entry.explanation ?? ""
        }
    }

    private func save() {
        let trimmedPronunciation = draftPronunciation.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedExplanation = draftExplanation.trimmingCharacters(in: .whitespacesAndNewlines)

        entry.translation = draftTranslation.trimmingCharacters(in: .whitespacesAndNewlines)
        entry.pronunciation = trimmedPronunciation.isEmpty ? nil : trimmedPronunciation
        entry.explanation = trimmedExplanation.isEmpty ? nil : trimmedExplanation

        if entry.isSynced {
            entry.syncAction = .edit
            entry.syncState = .pending
        }

        dismiss()
    }
}
