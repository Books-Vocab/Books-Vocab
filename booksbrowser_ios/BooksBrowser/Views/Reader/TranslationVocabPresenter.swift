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
    let onDismiss: () -> Void

    var body: some View {
        VocabCard(padding: 0) {
            VStack(spacing: 0) {
                Capsule(style: .continuous)
                    .fill(vocabSkin.palette.quaternaryText.opacity(0.24))
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

            if let pronunciation = state.pronunciation {
                Text(pronunciation)
                    .font(vocabSkin.typography.monoBody)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
            }

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
        case .empty:
            EmptyView()
        }
    }

    private var loadingSection: some View {
        VocabStateMessageCard(
            title: state.statusMessage ?? "翻譯中...",
            systemImage: "translate"
        ) {
            HStack {
                ProgressView().scaleEffect(0.8)
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
                title: state.isSaved ? "已加入待收錄" : "正在記錄…",
                systemImage: state.isSaved ? "checkmark.circle.fill" : "clock",
                description: "登入後即可獲得 AI 翻譯，並同步至知識庫。"
            )

            footerToolbar(showChevron: false, timerValue: nil)
        }
    }

    private var explanationOnlyBody: some View {
        VStack(alignment: .leading, spacing: 0) {
            CardSectionDivider(horizontalPadding: 0)
                .padding(.vertical, 2)

            Label("語境解釋", systemImage: "text.bubble")
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.quaternaryText)

            if state.isLoadingExplanation {
                VocabStateMessageCard(
                    title: state.statusMessage ?? "載入解釋...",
                    systemImage: "text.bubble"
                ) {
                    HStack {
                        ProgressView().scaleEffect(0.7)
                        Spacer()
                        if let timerText = state.activeTimerText {
                            Text(timerText)
                                .font(vocabSkin.typography.monoLabel)
                                .foregroundStyle(vocabSkin.palette.quaternaryText)
                        }
                    }
                }
                .padding(.vertical, 4)
            } else if let explanation = state.explanation {
                Text(explanation)
                    .font(vocabSkin.typography.body)
                    .foregroundStyle(vocabSkin.palette.secondaryText)
                    .fixedSize(horizontal: false, vertical: true)
                    .lineSpacing(3)
            }

            footerToolbar(showChevron: false, timerValue: state.statusTimerText)
        }
    }

    private func translationBody(_ translation: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(translation)
                .font(vocabSkin.typography.translationTitle)
                .foregroundStyle(vocabSkin.palette.translationText)

            if state.isExpanded {
                CardSectionDivider(horizontalPadding: 0)
                    .padding(.vertical, 2)

                Label("語境解釋", systemImage: "text.bubble")
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)

                if state.isLoadingExplanation {
                    VocabStateMessageCard(
                        title: state.statusMessage ?? "載入解釋...",
                        systemImage: "text.bubble"
                    ) {
                        HStack {
                            ProgressView().scaleEffect(0.7)
                            Spacer()
                            if let timerText = state.activeTimerText {
                                Text(timerText)
                                    .font(vocabSkin.typography.monoLabel)
                                    .foregroundStyle(vocabSkin.palette.quaternaryText)
                            }
                        }
                    }
                    .padding(.vertical, 4)
                } else if let explanation = state.explanation {
                    Text(explanation)
                        .font(vocabSkin.typography.body)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                        .fixedSize(horizontal: false, vertical: true)
                        .lineSpacing(3)
                }
            }

            footerToolbar(showChevron: state.showsExpandAction, timerValue: state.statusTimerText)
        }
    }

    @ViewBuilder
    private func footerToolbar(showChevron: Bool, timerValue: String?) -> some View {
        HStack(spacing: 4) {
            if state.showsSavedStatus {
                Label("已加入", systemImage: "checkmark.circle.fill")
                    .font(vocabSkin.typography.captionStrong)
                    .foregroundStyle(vocabSkin.palette.success)
                    .symbolEffect(.bounce, value: state.isSaved)
                    .transition(.feedbackBadge)
            }

            if let timerValue {
                Text(timerValue)
                    .font(vocabSkin.typography.monoLabel)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
                    .padding(.leading, state.showsSavedStatus ? 8 : 0)
            }

            Spacer()

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
        .padding(.top, 4)
    }
}
