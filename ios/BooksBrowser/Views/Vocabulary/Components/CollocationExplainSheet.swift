import SwiftUI

struct CollocationExplainSheet: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.dismiss) private var dismiss

    let collocation: String
    let context: String
    let existingExplanation: String?
    let onSave: (String) -> Void
    let onDelete: () -> Void

    @State private var phase: Phase = .idle
    @State private var explanation: String = ""

    enum Phase {
        case idle
        case loading
        case loaded
        case error(String)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(collocation)
                .font(vocabSkin.typography.detailWord)
                .foregroundStyle(vocabSkin.palette.primaryText)

            CardSectionDivider(horizontalPadding: 0)

            contentSection

            Spacer()

            footerToolbar
        }
        .padding(.horizontal, vocabSkin.metrics.readerPanelHorizontalInset)
        .padding(.top, 20)
        .padding(.bottom, vocabSkin.metrics.readerPanelBottomInset)
        .task { await loadIfNeeded() }
    }

    @ViewBuilder
    private var contentSection: some View {
        switch phase {
        case .idle:
            EmptyView()
        case .loading:
            VocabStateMessageCard(title: "正在解釋…".localized, systemImage: "text.bubble") {
                ProgressView().scaleEffect(AppMetrics.loadingIndicatorScaleSmall)
            }
        case .loaded:
            Text(explanation)
                .font(vocabSkin.typography.body)
                .foregroundStyle(vocabSkin.palette.secondaryText)
                .fixedSize(horizontal: false, vertical: true)
                .lineSpacing(3)
        case .error(let message):
            VocabStateMessageCard(
                title: "解釋失敗".localized,
                systemImage: "exclamationmark.triangle.fill",
                description: message
            )
        }
    }

    private var footerToolbar: some View {
        HStack(spacing: 4) {
            if case .loaded = phase, existingExplanation == nil {
                Button {
                    onSave(explanation)
                    dismiss()
                } label: {
                    Label("儲存".localized, systemImage: "checkmark.circle")
                        .font(vocabSkin.typography.captionStrong)
                }
                .buttonStyle(.plain)
                .foregroundStyle(vocabSkin.palette.success)
            }

            Spacer()

            if existingExplanation != nil {
                VocabChromeIconButton(
                    systemImage: "trash",
                    tone: vocabSkin.palette.destructive,
                    action: {
                        onDelete()
                        dismiss()
                    }
                )
            }

            VocabChromeIconButton(systemImage: "xmark", action: {
                dismiss()
            })
        }
    }

    private func loadIfNeeded() async {
        if let existing = existingExplanation {
            explanation = existing
            phase = .loaded
            return
        }
        phase = .loading
        do {
            let service = TranslationService()
            let (result, _) = try await service.fetchExplanation(
                word: collocation,
                context: context
            )
            explanation = result
            phase = .loaded
        } catch {
            phase = .error(error.localizedDescription)
        }
    }
}
