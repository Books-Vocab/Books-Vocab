import SwiftUI

struct TranslationPanelPresenter: View {
    @Environment(\.appTheme) private var appTheme

    let state: TranslationPanelPresenterState
    let onSpeak: () -> Void
    let onExpand: () -> Void
    let onDelete: () -> Void
    let onShowDetail: (() -> Void)?
    let onDismiss: () -> Void

    var body: some View {
        GlassEffectContainer {
            VStack(spacing: 0) {
                Capsule()
                    .fill(.quaternary)
                    .frame(
                        width: ReaderPresentationMetrics.Panel.handleWidth,
                        height: ReaderPresentationMetrics.Panel.handleHeight
                    )
                    .padding(.top, ReaderPresentationMetrics.Panel.handleTopInset)
                    .padding(.bottom, ReaderPresentationMetrics.Panel.handleBottomInset)

                VStack(alignment: .leading, spacing: ReaderPresentationMetrics.Panel.sectionSpacing) {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(state.word)
                            .font(ReaderGlassTypography.word)

                        Button(action: onSpeak) {
                            Image(systemName: "speaker.wave.2.fill")
                                .font(ReaderGlassTypography.iconTiny)
                                .foregroundStyle(appTheme.palette.secondaryText)
                                .symbolEffect(.bounce, value: state.isSpeaking)
                        }

                        Spacer()

                        if let partOfSpeech = state.partOfSpeech {
                            Text(partOfSpeech)
                                .font(ReaderGlassTypography.partOfSpeech)
                                .padding(.horizontal, ReaderPresentationMetrics.Panel.badgeHorizontalPadding)
                                .padding(.vertical, ReaderPresentationMetrics.Panel.badgeVerticalPadding)
                                .background(appTheme.palette.accent.opacity(0.12))
                                .foregroundStyle(appTheme.palette.accent)
                                .clipShape(Capsule())
                        }
                    }

                    panelBody
                }
                .padding(.horizontal, ReaderPresentationMetrics.Panel.horizontalInset)
                .padding(.bottom, ReaderPresentationMetrics.Panel.bottomInset)
            }
        }
        .glassEffect(
            in: RoundedRectangle(
                cornerRadius: ReaderPresentationMetrics.Panel.cornerRadius,
                style: .continuous
            )
        )
        .shadow(
            color: .black.opacity(ReaderPresentationMetrics.Panel.shadowOpacity),
            radius: ReaderPresentationMetrics.Panel.shadowRadius,
            y: ReaderPresentationMetrics.Panel.shadowY
        )
    }

    @ViewBuilder
    private var panelBody: some View {
        switch state.contentMode {
        case .loading:
            stateMessageContent(
                title: state.loadingTitle,
                systemImage: "translate"
            ) {
                HStack {
                    ProgressView().scaleEffect(AppMetrics.loadingIndicatorScaleMedium)
                    Spacer()
                    if let timerText = state.activeTimerText {
                        Text(timerText)
                            .font(ReaderGlassTypography.numericMono)
                            .foregroundStyle(appTheme.palette.tertiaryText)
                    }
                }
            }
            .padding(.vertical, ReaderPresentationMetrics.Panel.messageVerticalInset)
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

    private var guestModeBody: some View {
        VStack(alignment: .leading, spacing: 10) {
            stateMessageContent(
                title: state.guestMessageTitle,
                systemImage: state.guestMessageIcon,
                description: "登入後即可獲得 AI 翻譯，並同步至知識庫。"
            )
            .padding(.vertical, ReaderPresentationMetrics.Panel.statusInsetVertical)
            .padding(.horizontal, ReaderPresentationMetrics.Panel.statusInsetHorizontal)
            .background((state.isSaved ? appTheme.palette.success : appTheme.palette.accent).opacity(0.06))
            .clipShape(
                RoundedRectangle(
                    cornerRadius: ReaderPresentationMetrics.Panel.statusCornerRadius,
                    style: .continuous
                )
            )

            quotaBar
            panelToolbar(showChevron: false, timerValue: nil)
        }
    }

    private var explanationOnlyBody: some View {
        VStack(alignment: .leading, spacing: 0) {
            explanationSection

            quotaBar
            panelToolbar(showChevron: false, timerValue: state.statusTimerText)
        }
    }

    private func translationBody(_ translation: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(translation)
                .font(ReaderGlassTypography.translationTitle)

            if state.isExpanded {
                explanationSection
            }

            quotaBar
            panelToolbar(showChevron: state.showsExpandAction, timerValue: state.statusTimerText)
        }
    }

    private func translationErrorBody(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            errorStateContent(
                title: "翻譯暫時失敗",
                description: message
            )

            quotaBar
            panelToolbar(showChevron: false, timerValue: state.statusTimerText)
        }
    }

    private var emptyStateBody: some View {
        VStack(alignment: .leading, spacing: 10) {
            stateMessageContent(
                title: "尚未取得翻譯".localized,
                systemImage: "text.viewfinder",
                description: "請重新選取文字，或稍後再試一次。".localized
            )
            .padding(.vertical, ReaderPresentationMetrics.Panel.messageVerticalInset)

            quotaBar
            panelToolbar(showChevron: false, timerValue: state.statusTimerText)
        }
    }

    private var emptyExplainStateContent: some View {
        stateMessageContent(
            title: "還沒有語境解釋".localized,
            systemImage: "text.bubble",
            description: "展開後會在這裡顯示上下文說明。".localized
        )
    }

    private var explanationSection: some View {
        VStack(alignment: .leading, spacing: 0) {
            Divider()
                .padding(.vertical, ReaderPresentationMetrics.Panel.dividerInsetVertical)

            Label("語境解釋".localized, systemImage: "text.bubble")
                .font(ReaderGlassTypography.labelSmall)
                .foregroundStyle(appTheme.palette.tertiaryText)

            explanationContent
        }
    }

    @ViewBuilder
    private var explanationContent: some View {
        switch state.explanationContentMode {
        case .loading(let title):
            stateMessageContent(
                title: title,
                systemImage: "text.bubble"
            ) {
                HStack {
                    ProgressView().scaleEffect(AppMetrics.loadingIndicatorScaleSmall)
                    Spacer()
                    if let timerText = state.activeTimerText {
                        Text(timerText)
                            .font(ReaderGlassTypography.numericMono)
                            .foregroundStyle(appTheme.palette.tertiaryText)
                    }
                }
            }
            .padding(.vertical, ReaderPresentationMetrics.Panel.explanationInsetVertical)
        case .error(let errorMessage):
            errorStateContent(
                title: "語境解釋暫時無法載入".localized,
                description: errorMessage
            )
            .padding(.vertical, ReaderPresentationMetrics.Panel.explanationInsetVertical)
        case .content(let explanation):
            Text(explanation)
                .font(ReaderGlassTypography.body)
                .foregroundStyle(appTheme.palette.secondaryText)
                .lineSpacing(3)
        case .empty:
            emptyExplainStateContent
                .padding(.vertical, ReaderPresentationMetrics.Panel.explanationInsetVertical)
        }
    }

    private func errorStateContent(title: String, description: String) -> some View {
        stateMessageContent(
            title: title,
            systemImage: "exclamationmark.triangle.fill",
            description: description
        )
    }

    private func stateMessageContent<Accessory: View>(
        title: String,
        systemImage: String,
        description: String? = nil,
        @ViewBuilder accessory: () -> Accessory = { EmptyView() }
    ) -> some View {
        AppStateMessageContent(
            title: title,
            systemImage: systemImage,
            description: description
        ) {
            accessory()
        }
    }

    private var quotaBar: some View {
        QuotaBar(isLoggedIn: state.isLoggedIn)
    }

    @ViewBuilder
    private func panelToolbar(showChevron: Bool, timerValue: String?) -> some View {
        HStack(spacing: 4) {
            if state.showsSavedStatus {
                Label("已加入".localized, systemImage: "checkmark.circle.fill")
                    .font(ReaderGlassTypography.savedStatus)
                    .foregroundStyle(appTheme.palette.success)
                    .symbolEffect(.bounce, value: state.isSaved)
                    .transition(.feedbackBadge)
            }

            if let timerValue {
                Text(timerValue)
                    .font(ReaderGlassTypography.numericMono)
                    .foregroundStyle(appTheme.palette.tertiaryText)
                    .padding(.leading, state.showsSavedStatus ? AppMetrics.spacingSmall : 0)
            }

            Spacer()

            if let onShowDetail {
                panelIconButton(
                    systemImage: "rectangle.portrait.on.rectangle.portrait",
                    tone: appTheme.palette.secondaryText,
                    action: onShowDetail
                )
            }

            if showChevron {
                panelIconButton(
                    systemImage: state.isExpanded ? "chevron.up" : "chevron.down",
                    tone: appTheme.palette.secondaryText,
                    action: onExpand
                )
                .symbolEffect(.bounce, value: state.isExpanded)
            }

            if state.showsDeleteAction {
                panelIconButton(
                    systemImage: "trash",
                    tone: appTheme.palette.destructive.opacity(0.72),
                    action: onDelete
                )
            }

            panelIconButton(
                systemImage: "xmark.circle.fill",
                tone: appTheme.palette.tertiaryText,
                action: onDismiss
            )
        }
        .padding(.top, ReaderPresentationMetrics.Panel.toolbarTopInset)
    }

    private func panelIconButton(
        systemImage: String,
        tone: Color,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(ReaderGlassTypography.toolbarIcon)
                .foregroundStyle(tone)
                .frame(
                    width: ReaderPresentationMetrics.Panel.actionButtonSize,
                    height: ReaderPresentationMetrics.Panel.actionButtonSize
                )
                .contentShape(Rectangle())
                .glassEffect(.clear, in: Circle())
        }
    }
}
