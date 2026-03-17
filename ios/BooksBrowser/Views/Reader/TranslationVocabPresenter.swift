//
//  TranslationVocabPresenter.swift
//  BooksBrowser
//
//  TranslationPanel 的 Vocab-style 渲染器。
//  與 Glass presenter 共用相同的內容狀態與操作語意，
//  僅切換卡片視覺與字體 / 色彩 token。
//

import SwiftUI

struct TranslationVocabPresenter: View {
    @Environment(\.vocabSkin) private var vocabSkin

    let state: TranslationPanelPresenterState
    let onSpeak: () -> Void
    let onExpand: () -> Void
    let onDelete: () -> Void
    let onShowDetail: (() -> Void)?
    let onDismiss: () -> Void

    var body: some View {
        VocabCard(padding: 0) {
            VStack(spacing: 0) {
                Capsule(style: .continuous)
                    .fill(vocabSkin.palette.quaternaryText.opacity(vocabSkin.metrics.panelHandleOpacity))
                    .frame(
                        width: vocabSkin.metrics.readerPanelHandleWidth,
                        height: vocabSkin.metrics.readerPanelHandleHeight
                    )
                    .padding(.top, vocabSkin.metrics.readerPanelHandleTopInset)
                    .padding(.bottom, vocabSkin.metrics.readerPanelHandleBottomInset)

                VStack(alignment: .leading, spacing: 12) {
                    heroSection
                    panelBody
                }
                .padding(.horizontal, vocabSkin.metrics.readerPanelHorizontalInset)
                .padding(.bottom, vocabSkin.metrics.readerPanelBottomInset)
            }
        }
        .shadow(
            color: vocabSkin.palette.shadow.opacity(vocabSkin.metrics.readerPanelShadowOpacity),
            radius: vocabSkin.metrics.readerPanelShadowRadius,
            y: vocabSkin.metrics.readerPanelShadowY
        )
    }

    private var heroSection: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(state.word)
                .font(state.word.count > 12
                      ? vocabSkin.typography.translationTitle
                      : vocabSkin.typography.detailWord)
                .foregroundStyle(vocabSkin.palette.primaryText)

            Button(action: onSpeak) {
                Image(systemName: "speaker.wave.2")
                    .font(vocabSkin.typography.iconTiny)
                    .foregroundStyle(vocabSkin.palette.secondaryText)
                    .symbolEffect(.bounce, value: state.isSpeaking)
            }
            .buttonStyle(.plain)

            Spacer()

            if let pos = state.partOfSpeech {
                VocabToneChip(text: pos, tone: vocabSkin.palette.accent)
            }
        }
    }

    @ViewBuilder
    private var panelBody: some View {
        switch state.contentMode {
        case .loading:
            loadingSection
        case .guest:
            guestModeBody
        case .explanationOnly:
            explanationOnlyBody
        case .translation(let translation):
            translationBody(translation)
        case .translationError(let message):
            translationErrorBody(message)
        case .empty:
            emptyStateBody
        }
    }

    private var loadingSection: some View {
        VocabStateMessageCard(
            title: state.loadingTitle,
            systemImage: "translate"
        ) {
            HStack {
                ProgressView().scaleEffect(AppMetrics.loadingIndicatorScaleMedium)
                Spacer()
                if let timerText = state.activeTimerText {
                    Text(timerText)
                        .font(vocabSkin.typography.monoLabel)
                        .foregroundStyle(vocabSkin.palette.quaternaryText)
                }
            }
        }
    }

    private var guestModeBody: some View {
        VStack(alignment: .leading, spacing: 10) {
            VocabStateMessageCard(
                title: state.guestMessageTitle,
                systemImage: state.guestMessageIcon,
                description: "登入後即可獲得 AI 翻譯，並同步至知識庫。"
            )

            footerToolbar(showChevron: false, timerValue: nil)
        }
    }

    private var explanationOnlyBody: some View {
        VStack(alignment: .leading, spacing: 0) {
            explanationSection

            footerToolbar(showChevron: false, timerValue: state.statusTimerText)
        }
    }

    private func translationBody(_ translation: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(translation)
                .font(vocabSkin.typography.translationTitle)
                .foregroundStyle(vocabSkin.palette.translationText)

            if state.isExpanded {
                explanationSection
            }

            footerToolbar(showChevron: state.showsExpandAction, timerValue: state.statusTimerText)
        }
    }

    private func translationErrorBody(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            VocabStateMessageCard(
                title: "翻譯暫時失敗".localized,
                systemImage: "exclamationmark.triangle.fill",
                description: message
            )

            footerToolbar(showChevron: false, timerValue: state.statusTimerText)
        }
    }

    private var emptyStateBody: some View {
        VStack(alignment: .leading, spacing: 10) {
            VocabStateMessageCard(
                title: "尚未取得翻譯".localized,
                systemImage: "text.viewfinder",
                description: "請重新選取文字，或稍後再試一次。".localized
            )

            footerToolbar(showChevron: false, timerValue: state.statusTimerText)
        }
    }

    private var emptyExplainStateCard: some View {
        VocabStateMessageCard(
            title: "還沒有語境解釋".localized,
            systemImage: "text.bubble",
            description: "展開後會在這裡顯示上下文說明。".localized
        )
    }

    private var explanationSection: some View {
        VStack(alignment: .leading, spacing: 0) {
            CardSectionDivider(horizontalPadding: 0)
                .padding(.vertical, 2)

            Label("語境解釋".localized, systemImage: "text.bubble")
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.quaternaryText)

            explanationContent
        }
    }

    @ViewBuilder
    private var explanationContent: some View {
        switch state.explanationContentMode {
        case .loading(let title):
            VocabStateMessageCard(
                title: title,
                systemImage: "text.bubble"
            ) {
                HStack {
                    ProgressView().scaleEffect(AppMetrics.loadingIndicatorScaleSmall)
                    Spacer()
                    if let timerText = state.activeTimerText {
                        Text(timerText)
                            .font(vocabSkin.typography.monoLabel)
                            .foregroundStyle(vocabSkin.palette.quaternaryText)
                    }
                }
            }
            .padding(.vertical, vocabSkin.spacing.tinyGap)
        case .error(let errorMessage):
            VocabStateMessageCard(
                title: "語境解釋暫時無法載入".localized,
                systemImage: "exclamationmark.triangle.fill",
                description: errorMessage
            )
            .padding(.vertical, vocabSkin.spacing.tinyGap)
        case .content(let explanation):
            Text(explanation)
                .font(vocabSkin.typography.body)
                .foregroundStyle(vocabSkin.palette.secondaryText)
                .fixedSize(horizontal: false, vertical: true)
                .lineSpacing(3)
        case .empty:
            emptyExplainStateCard
                .padding(.vertical, vocabSkin.spacing.tinyGap)
        }
    }

    @ViewBuilder
    private func footerToolbar(showChevron: Bool, timerValue: String?) -> some View {
        HStack(spacing: 4) {
            if state.showsSavedStatus {
                Label("已加入".localized, systemImage: "checkmark.circle.fill")
                    .font(vocabSkin.typography.captionStrong)
                    .foregroundStyle(vocabSkin.palette.success)
                    .symbolEffect(.bounce, value: state.isSaved)
                    .transition(.feedbackBadge)
            }

            if let timerValue {
                Text(timerValue)
                    .font(vocabSkin.typography.monoLabel)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
                    .padding(.leading, state.showsSavedStatus ? vocabSkin.spacing.inlineGap : 0)
            }

            Spacer()

            if let onShowDetail {
                VocabChromeIconButton(
                    systemImage: "rectangle.portrait.on.rectangle.portrait",
                    action: onShowDetail
                )
            }

            if showChevron {
                VocabChromeIconButton(
                    systemImage: state.isExpanded ? "chevron.up" : "chevron.down",
                    action: onExpand
                )
            }

            if state.showsDeleteAction {
                VocabChromeIconButton(
                    systemImage: "trash",
                    tone: vocabSkin.palette.destructive,
                    action: onDelete
                )
            }

            VocabChromeIconButton(systemImage: "xmark", action: onDismiss)
        }
        .padding(.top, vocabSkin.spacing.tinyGap)
    }
}

#Preview("Translation Vocab / Full Result") {
    AppThemeContainer {
        VStack {
            Spacer()
            TranslationVocabPresenter(
                state: TranslationPanelPreviewData.fullTranslation,
                onSpeak: {}, onExpand: {}, onDelete: {}, onShowDetail: nil, onDismiss: {}
            )
            .padding()
        }
    }
}

#Preview("Translation Vocab / Explanation Error") {
    AppThemeContainer {
        VStack {
            Spacer()
            TranslationVocabPresenter(
                state: TranslationPanelPreviewData.explanationError,
                onSpeak: {}, onExpand: {}, onDelete: {}, onShowDetail: nil, onDismiss: {}
            )
            .padding()
        }
    }
}
