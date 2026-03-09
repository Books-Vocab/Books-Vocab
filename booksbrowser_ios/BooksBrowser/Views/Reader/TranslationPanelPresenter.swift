import SwiftUI

struct TranslationPanelPresenterState {
    let word: String
    let pronunciation: String?
    let partOfSpeech: String?
    let translation: String?
    let isLoading: Bool
    let isSaved: Bool
    let isLoggedIn: Bool
    let isExpanded: Bool
    let explanation: String?
    let isLoadingExplanation: Bool
    let statusMessage: String?
    let isExplanationOnly: Bool
    let timerText: String
    let isSpeaking: Bool
}

enum TranslationPanelContentMode: Equatable {
    case loading
    case guest
    case explanationOnly
    case translation(String)
    case empty
}

extension TranslationPanelPresenterState {
    var contentMode: TranslationPanelContentMode {
        if isLoading {
            return .loading
        }
        if !isLoggedIn {
            return .guest
        }
        if isExplanationOnly {
            return .explanationOnly
        }
        if let translation {
            return .translation(translation)
        }
        return .empty
    }

    var activeTimerText: String? {
        guard !timerText.isEmpty, isLoading || isLoadingExplanation else { return nil }
        return timerText
    }

    var statusTimerText: String? {
        timerText.isEmpty ? nil : timerText
    }

    var showsExpandAction: Bool {
        isLoggedIn && translation != nil && !isExplanationOnly
    }

    var showsSavedStatus: Bool {
        isSaved && isLoggedIn
    }

    var showsDeleteAction: Bool {
        isSaved
    }
}

struct TranslationPanelPresenter: View {
    @Environment(\.colorScheme) private var colorScheme

    let state: TranslationPanelPresenterState
    let onSpeak: () -> Void
    let onExpand: () -> Void
    let onDelete: () -> Void
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

                        if let pronunciation = state.pronunciation {
                            Text(pronunciation)
                                .font(ReaderGlassTypography.pronunciation)
                                .foregroundStyle(.secondary)
                        }

                        Button(action: onSpeak) {
                            Image(systemName: "speaker.wave.2.fill")
                                .font(ReaderGlassTypography.iconTiny)
                                .foregroundStyle(.secondary)
                                .symbolEffect(.bounce, value: state.isSpeaking)
                        }

                        Spacer()

                        if let partOfSpeech = state.partOfSpeech {
                            Text(partOfSpeech)
                                .font(ReaderGlassTypography.partOfSpeech)
                                .padding(.horizontal, ReaderPresentationMetrics.Panel.badgeHorizontalPadding)
                                .padding(.vertical, ReaderPresentationMetrics.Panel.badgeVerticalPadding)
                                .background(AppColors.accent(colorScheme).opacity(0.12))
                                .foregroundStyle(AppColors.accent(colorScheme))
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
                title: state.statusMessage ?? "翻譯中...",
                systemImage: "translate"
            ) {
                HStack {
                    ProgressView().scaleEffect(0.8)
                    Spacer()
                    if let timerText = state.activeTimerText {
                        Text(timerText)
                            .font(ReaderGlassTypography.numericMono)
                            .foregroundStyle(.tertiary)
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
        case .empty:
            EmptyView()
        }
    }

    private var guestModeBody: some View {
        VStack(alignment: .leading, spacing: 10) {
            stateMessageContent(
                title: state.isSaved ? "已加入待收錄" : "正在記錄…",
                systemImage: state.isSaved ? "checkmark.circle.fill" : "clock",
                description: "登入後即可獲得 AI 翻譯，並同步至知識庫。"
            )
            .padding(.vertical, ReaderPresentationMetrics.Panel.statusInsetVertical)
            .padding(.horizontal, ReaderPresentationMetrics.Panel.statusInsetHorizontal)
            .background((state.isSaved ? AppColors.saved(colorScheme) : AppColors.accent(colorScheme)).opacity(0.06))
            .clipShape(
                RoundedRectangle(
                    cornerRadius: ReaderPresentationMetrics.Panel.statusCornerRadius,
                    style: .continuous
                )
            )

            panelToolbar(showChevron: false, timerValue: nil)
        }
    }

    private var explanationOnlyBody: some View {
        VStack(alignment: .leading, spacing: 0) {
            Divider()
                .padding(.vertical, ReaderPresentationMetrics.Panel.dividerInsetVertical)

            Label("語境解釋", systemImage: "text.bubble")
                .font(ReaderGlassTypography.labelSmall)
                .foregroundStyle(.tertiary)

            if state.isLoadingExplanation {
                stateMessageContent(
                    title: state.statusMessage ?? "載入解釋...",
                    systemImage: "text.bubble"
                ) {
                    HStack {
                        ProgressView().scaleEffect(0.7)
                        Spacer()
                        Text(state.timerText)
                            .font(ReaderGlassTypography.numericMono)
                            .foregroundStyle(.tertiary)
                    }
                }
                .padding(.vertical, ReaderPresentationMetrics.Panel.explanationInsetVertical)
            } else if let explanation = state.explanation {
                Text(explanation)
                    .font(ReaderGlassTypography.body)
                    .foregroundStyle(.secondary)
                    .lineSpacing(3)
            }

            panelToolbar(showChevron: false, timerValue: state.statusTimerText)
        }
    }

    private func translationBody(_ translation: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(translation)
                .font(ReaderGlassTypography.translationTitle)

            if state.isExpanded {
                Divider()
                    .padding(.vertical, ReaderPresentationMetrics.Panel.dividerInsetVertical)

                Label("語境解釋", systemImage: "text.bubble")
                    .font(ReaderGlassTypography.labelSmall)
                    .foregroundStyle(.tertiary)

                if state.isLoadingExplanation {
                    stateMessageContent(
                        title: state.statusMessage ?? "載入解釋...",
                        systemImage: "text.bubble"
                    ) {
                        HStack {
                            ProgressView().scaleEffect(0.7)
                            Spacer()
                            Text(state.timerText)
                                .font(ReaderGlassTypography.numericMono)
                                .foregroundStyle(.tertiary)
                        }
                    }
                    .padding(.vertical, ReaderPresentationMetrics.Panel.explanationInsetVertical)
                } else if let explanation = state.explanation {
                    Text(explanation)
                        .font(ReaderGlassTypography.body)
                        .foregroundStyle(.secondary)
                        .lineSpacing(3)
                }
            }

            panelToolbar(showChevron: state.showsExpandAction, timerValue: state.statusTimerText)
        }
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

    @ViewBuilder
    private func panelToolbar(showChevron: Bool, timerValue: String?) -> some View {
        HStack(spacing: 4) {
            if state.showsSavedStatus {
                Label("已加入", systemImage: "checkmark.circle.fill")
                    .font(ReaderGlassTypography.savedStatus)
                    .foregroundStyle(AppColors.saved(colorScheme))
                    .symbolEffect(.bounce, value: state.isSaved)
                    .transition(.feedbackBadge)
            }

            if let timerValue {
                Text(timerValue)
                    .font(ReaderGlassTypography.numericMono)
                    .foregroundStyle(.tertiary)
                    .padding(.leading, state.showsSavedStatus ? 8 : 0)
            }

            Spacer()

            if showChevron {
                Button(action: onExpand) {
                    Image(systemName: state.isExpanded ? "chevron.up" : "chevron.down")
                        .font(ReaderGlassTypography.toolbarIcon)
                        .foregroundStyle(.secondary)
                        .frame(
                            width: ReaderPresentationMetrics.Panel.actionButtonSize,
                            height: ReaderPresentationMetrics.Panel.actionButtonSize
                        )
                        .contentShape(Rectangle())
                        .symbolEffect(.bounce, value: state.isExpanded)
                        .glassEffect(.clear, in: Circle())
                }
            }

            if state.showsDeleteAction {
                Button(action: onDelete) {
                    Image(systemName: "trash")
                        .font(ReaderGlassTypography.toolbarIcon)
                        .foregroundStyle(AppColors.destructive(colorScheme).opacity(0.65))
                        .frame(
                            width: ReaderPresentationMetrics.Panel.actionButtonSize,
                            height: ReaderPresentationMetrics.Panel.actionButtonSize
                        )
                        .contentShape(Rectangle())
                        .glassEffect(.clear, in: Circle())
                }
            }

            Button(action: onDismiss) {
                Image(systemName: "xmark.circle.fill")
                    .font(ReaderGlassTypography.toolbarIcon)
                    .foregroundStyle(.tertiary)
                    .frame(
                        width: ReaderPresentationMetrics.Panel.actionButtonSize,
                        height: ReaderPresentationMetrics.Panel.actionButtonSize
                    )
                    .contentShape(Rectangle())
                    .glassEffect(.clear, in: Circle())
            }
        }
        .padding(.top, ReaderPresentationMetrics.Panel.toolbarTopInset)
    }
}
