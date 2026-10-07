import SwiftUI

struct WordEditSheet: View {
    @ObserveInjection private var inject
    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var modelContext
    @Environment(\.appSkin) private var appSkin
    @Environment(\.toastCoordinator) private var toastCoordinator
    @Bindable var entry: VocabularyEntry
    var onSaved: (() -> Void)? = nil

    @State private var draftTranslation = ""
    @State private var draftExplanation = ""
    @State private var isSaving = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
                    editSection(
                        title: "翻譯結果".localized,
                        text: $draftTranslation,
                        accessibilityIdentifier: "wordDetail.edit.translation"
                    )
                    editSection(
                        title: "教學筆記".localized,
                        text: $draftExplanation,
                        accessibilityIdentifier: "wordDetail.edit.explanation"
                    )
                }
                .padding(appSkin.spacing.cardPadding)
            }
            .vocabCanvasBackground()
            .navigationTitle(entry.word)
            .inlineNavigationBarTitle()
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消".localized) { dismiss() }
                        .accessibilityIdentifier("wordDetail.edit.cancel")
                        .disabled(isSaving)
                }
                ToolbarItem(placement: .confirmationAction) {
                    if isSaving {
                        ProgressView()
                            .controlSize(.small)
                    } else {
                        Button("儲存".localized) { save() }
                            .accessibilityIdentifier("wordDetail.edit.save")
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

    private func editSection(
        title: String,
        text: Binding<String>,
        accessibilityIdentifier: String
    ) -> some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.inlineGap) {
            Text(title)
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.secondaryText)

            TextEditor(text: text)
                .font(appSkin.typography.body)
                .foregroundStyle(appSkin.palette.primaryText)
                .accessibilityIdentifier(accessibilityIdentifier)
                .scrollContentBackground(.hidden)
                .padding(appSkin.spacing.inlineGap)
                .frame(minHeight: 80)
                .background(
                    AppRoundedRect(roundness: AppShellMetrics.cardRoundness)
                        .fill(appSkin.palette.cardBackground)
                        .overlay(
                            AppRoundedRect(roundness: AppShellMetrics.cardRoundness)
                                .stroke(appSkin.palette.cardBorder.opacity(0.5), lineWidth: 1)
                        )
                )
        }
    }

    private func save() {
        isSaving = true

        let trimmedExplanation = draftExplanation.trimmingCharacters(in: .whitespacesAndNewlines)

        entry.translation = draftTranslation.trimmingCharacters(in: .whitespacesAndNewlines)
        entry.explanation = trimmedExplanation.isEmpty ? nil : trimmedExplanation

        if entry.isSynced {
            entry.syncAction = .edit
            entry.syncState = .pending
        }

        do {
            try modelContext.save()
            onSaved?()
            dismiss()
        } catch {
            // 一次性失敗通知走頂端 pill；重試入口就是工具列上的「儲存」，草稿仍保留在表單裡，
            // 不需要另開面板。
            toastCoordinator.error(L10n.string("儲存失敗，請再試一次"))
            isSaving = false
        }
    }
}
