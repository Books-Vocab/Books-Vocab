import SwiftUI

struct TranslationPanelPresenterState {
    let word: String
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
    let translationErrorMessage: String?
    let explanationErrorMessage: String?
    let timerText: String
    let isSpeaking: Bool
}

enum TranslationPanelContentMode: Equatable {
    case loading
    case guest
    case explanationOnly
    case translation(String)
    case translationError(String)
    case empty
}

enum TranslationExplanationContentMode: Equatable {
    case loading(String)
    case error(String)
    case content(String)
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
        if let translationErrorMessage {
            return .translationError(translationErrorMessage)
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

    var loadingTitle: String {
        statusMessage ?? "翻譯中..."
    }

    var guestMessageTitle: String {
        isSaved ? "已加入待收錄" : "正在記錄…"
    }

    var guestMessageIcon: String {
        isSaved ? "checkmark.circle.fill" : "clock"
    }

    var explanationLoadingTitle: String {
        statusMessage ?? "載入解釋...".localized
    }

    var explanationContentMode: TranslationExplanationContentMode {
        if isLoadingExplanation {
            return .loading(explanationLoadingTitle)
        }
        if let explanationErrorMessage {
            return .error(explanationErrorMessage)
        }
        if let explanation {
            return .content(explanation)
        }
        return .empty
    }
}

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
                    ProgressView().scaleEffect(0.8)
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
                    ProgressView().scaleEffect(0.7)
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

// MARK: - Preview Data

enum TranslationPanelPreviewData {
    static let loading = TranslationPanelPresenterState(
        word: "ephemeral", partOfSpeech: nil,
        translation: nil, isLoading: true, isSaved: false,
        isLoggedIn: true, isExpanded: false, explanation: nil,
        isLoadingExplanation: false, statusMessage: nil,
        isExplanationOnly: false, translationErrorMessage: nil, explanationErrorMessage: nil,
        timerText: "", isSpeaking: false
    )

    static let guest = TranslationPanelPresenterState(
        word: "serendipity", partOfSpeech: "noun",
        translation: "意外發現美好事物的能力", isLoading: false, isSaved: true,
        isLoggedIn: false, isExpanded: false, explanation: nil,
        isLoadingExplanation: false, statusMessage: "登入以同步詞彙",
        isExplanationOnly: false, translationErrorMessage: nil, explanationErrorMessage: nil,
        timerText: "", isSpeaking: false
    )

    static let fullTranslation = TranslationPanelPresenterState(
        word: "ubiquitous", partOfSpeech: "adjective",
        translation: "無處不在的", isLoading: false, isSaved: true,
        isLoggedIn: true, isExpanded: true,
        explanation: "Something that is ubiquitous seems to be everywhere at the same time. For example, smartphones have become ubiquitous in modern life.",
        isLoadingExplanation: false, statusMessage: nil,
        isExplanationOnly: false, translationErrorMessage: nil, explanationErrorMessage: nil,
        timerText: "3s", isSpeaking: false
    )

    static let explanationOnlyLoading = TranslationPanelPresenterState(
        word: "ameliorate", partOfSpeech: nil,
        translation: nil, isLoading: false, isSaved: false,
        isLoggedIn: true, isExpanded: true, explanation: nil,
        isLoadingExplanation: true, statusMessage: nil,
        isExplanationOnly: true, translationErrorMessage: nil, explanationErrorMessage: nil,
        timerText: "", isSpeaking: false
    )

    static let translationError = TranslationPanelPresenterState(
        word: "oblique", partOfSpeech: "adjective",
        translation: nil, isLoading: false, isSaved: false,
        isLoggedIn: true, isExpanded: false, explanation: nil,
        isLoadingExplanation: false, statusMessage: nil,
        isExplanationOnly: false, translationErrorMessage: "服務暫時沒有回應，請稍後再試。".localized, explanationErrorMessage: nil,
        timerText: "", isSpeaking: false
    )

    static let explanationError = TranslationPanelPresenterState(
        word: "lucid", partOfSpeech: "adjective",
        translation: "清晰的", isLoading: false, isSaved: true,
        isLoggedIn: true, isExpanded: true, explanation: nil,
        isLoadingExplanation: false, statusMessage: nil,
        isExplanationOnly: false, translationErrorMessage: nil, explanationErrorMessage: "目前無法產生語境解釋。".localized,
        timerText: "2s", isSpeaking: false
    )

    static let empty = TranslationPanelPresenterState(
        word: "quixotic", partOfSpeech: nil,
        translation: nil, isLoading: false, isSaved: false,
        isLoggedIn: true, isExpanded: false, explanation: nil,
        isLoadingExplanation: false, statusMessage: nil,
        isExplanationOnly: false, translationErrorMessage: nil, explanationErrorMessage: nil,
        timerText: "", isSpeaking: false
    )
}

private struct TranslationPanelPreviewSurface<Content: View>: View {
    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        ZStack {
            AppColors.paperSepiaDeep.ignoresSafeArea()
            VStack {
                Spacer()
                content
            }
        }
    }
}

// MARK: - Previews

#Preview("Translation / Loading") {
    TranslationPanelPreviewSurface {
        TranslationPanelPresenter(
            state: TranslationPanelPreviewData.loading,
            onSpeak: {}, onExpand: {}, onDelete: {}, onShowDetail: nil, onDismiss: {}
        )
    }
}

#Preview("Translation / Guest") {
    TranslationPanelPreviewSurface {
        TranslationPanelPresenter(
            state: TranslationPanelPreviewData.guest,
            onSpeak: {}, onExpand: {}, onDelete: {}, onShowDetail: nil, onDismiss: {}
        )
    }
}

#Preview("Translation / Full Result") {
    TranslationPanelPreviewSurface {
        TranslationPanelPresenter(
            state: TranslationPanelPreviewData.fullTranslation,
            onSpeak: {}, onExpand: {}, onDelete: {}, onShowDetail: nil, onDismiss: {}
        )
    }
}

#Preview("Translation / Explanation Only Loading") {
    TranslationPanelPreviewSurface {
        TranslationPanelPresenter(
            state: TranslationPanelPreviewData.explanationOnlyLoading,
            onSpeak: {}, onExpand: {}, onDelete: {}, onShowDetail: nil, onDismiss: {}
        )
    }
}

#Preview("Translation / Error") {
    TranslationPanelPreviewSurface {
        TranslationPanelPresenter(
            state: TranslationPanelPreviewData.translationError,
            onSpeak: {}, onExpand: {}, onDelete: {}, onShowDetail: nil, onDismiss: {}
        )
    }
}

#Preview("Translation / Explanation Error") {
    TranslationPanelPreviewSurface {
        TranslationPanelPresenter(
            state: TranslationPanelPreviewData.explanationError,
            onSpeak: {}, onExpand: {}, onDelete: {}, onShowDetail: nil, onDismiss: {}
        )
    }
}

#Preview("Translation / Empty") {
    TranslationPanelPreviewSurface {
        TranslationPanelPresenter(
            state: TranslationPanelPreviewData.empty,
            onSpeak: {}, onExpand: {}, onDelete: {}, onShowDetail: nil, onDismiss: {}
        )
    }
}
