import SwiftUI

struct WordEditSheet: View {
    @ObserveInjection private var inject
    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var modelContext
    @Environment(\.appSkin) private var appSkin
    @Bindable var entry: VocabularyEntry

    @State private var draftTranslation = ""
    @State private var draftExplanation = ""
    @State private var isSaving = false
    @State private var saveError: String?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
                    if let saveError {
                        AppBanner(
                            message: saveError,
                            systemImage: "exclamationmark.triangle",
                            onRetry: { save() },
                            onDismiss: { self.saveError = nil }
                        )
                    }

                    editSection(title: "翻譯結果".localized, text: $draftTranslation)
                    editSection(title: "教學筆記".localized, text: $draftExplanation)
                }
                .padding(appSkin.spacing.cardPadding)
            }
            .vocabCanvasBackground()
            .navigationTitle(entry.word)
            .inlineNavigationBarTitle()
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
        .enableInjection()
    }

    private func editSection(title: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.inlineGap) {
            Text(title)
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.secondaryText)

            TextEditor(text: text)
                .font(appSkin.typography.body)
                .foregroundStyle(appSkin.palette.primaryText)
                .scrollContentBackground(.hidden)
                .padding(appSkin.spacing.inlineGap)
                .frame(minHeight: 80)
                .background(
                    RoundedRectangle(cornerRadius: AppShellMetrics.cardCornerRadius, style: .continuous)
                        .fill(appSkin.palette.cardBackground)
                        .overlay(
                            RoundedRectangle(cornerRadius: AppShellMetrics.cardCornerRadius, style: .continuous)
                                .stroke(appSkin.palette.cardBorder.opacity(0.5), lineWidth: 1)
                        )
                )
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
