#if os(iOS)
import SwiftUI

struct ReaderChromePreviewScene: View {
    let state: ReaderViewPresenterState
    let showsErrorCard: Bool

    var body: some View {
        ReaderViewPresenter(
            state: state,
            onDismiss: {},
            onShowTableOfContents: {},
            onShowReaderSettings: {},
            onShowNotebookPicker: {},
            onExpandHeader: {},
            onCollapseHeader: {}
        ) {
            ZStack {
                if showsErrorCard {
                    errorPreviewContent
                } else {
                    readingPreviewContent
                }
            }
            .ignoresSafeArea()
        } translationPanel: {
            TranslationPanel(
                word: "resilient",
                result: TranslationResult(
                    translation: "有韌性的；能快速恢復的",
                    partOfSpeech: "adj.",
                    explanation: nil
                ),
                isLoading: false,
                isSaved: true,
                isLoggedIn: true,
                isExpanded: true,
                explanation: "在這段語境中指角色面對壓力後仍能迅速回到穩定狀態。",
                isLoadingExplanation: false,
                statusMessage: nil,
                isExplanationOnly: false,
                translationErrorMessage: nil,
                explanationErrorMessage: nil,
                onExpand: {},
                onDelete: {},
                onShowDetail: nil,
                onDismiss: {},
                isPanelLarge: false,
                onToggleHeight: {}
            )
        } settingsPanel: {
            EmptyView()
        }
    }

    private var readingPreviewContent: some View {
        ZStack {
            LinearGradient(
                colors: [
                    state.paperColor.opacity(ReaderPresentationMetrics.Preview.paperOpacityTop),
                    state.paperColor.opacity(ReaderPresentationMetrics.Preview.paperOpacityMid),
                    AppColors.warmNeutral.opacity(ReaderPresentationMetrics.Preview.paperOpacityFloor)
                ],
                startPoint: .top,
                endPoint: .bottom
            )

            VStack(alignment: .leading, spacing: ReaderPresentationMetrics.Preview.blockSpacing) {
                ForEach(0..<8, id: \.self) { index in
                    RoundedRectangle(cornerRadius: ReaderPresentationMetrics.Preview.blockCornerRadius, style: .continuous)
                        .fill(Color.primary.opacity(index == 2 ? ReaderPresentationMetrics.Preview.textBlockEmphasisOpacity : ReaderPresentationMetrics.Preview.textBlockBaseOpacity))
                        .frame(height: index.isMultiple(of: 3) ? ReaderPresentationMetrics.Preview.blockHeightTall : ReaderPresentationMetrics.Preview.blockHeightShort)
                        .padding(.trailing, CGFloat(index % 3) * ReaderPresentationMetrics.Preview.trailingStep)
                }
                Spacer()
            }
            .padding(.top, ReaderPresentationMetrics.Preview.topInset)
            .padding(.horizontal, ReaderPresentationMetrics.Preview.horizontalInset)
            .padding(.bottom, ReaderPresentationMetrics.Preview.bottomInset)
        }
    }

    private var errorPreviewContent: some View {
        VStack {
            Spacer(minLength: ReaderPresentationMetrics.Preview.topInset)

            AppEmptyStateCard(
                title: "無法開啟書籍",
                systemImage: "exclamationmark.triangle",
                description: "Reader publication 載入失敗。請確認檔案是否完整，或稍後重新下載。"
            )
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)

            Spacer(minLength: ReaderPresentationMetrics.Preview.bottomInset)
        }
        .background(state.paperColor)
    }
}

#Preview("Reader Chrome / Loading") {
    ReaderChromePreviewScene(
        state: .init(
            paperColor: AppColors.paperSepiaDeep,
            isWebViewReady: false,
            loadingPhase: "渲染頁面…",
            underlineProgress: 0.42,
            chrome: .init(header: .compact, overlay: .none),
            totalProgression: 0.18,
            bookTitle: "The Left Hand of Darkness",
        ),
        showsErrorCard: false
    )
}

#Preview("Reader Chrome / Loading Vocab") {
    ReaderChromePreviewScene(
        state: .init(
            paperColor: AppColors.paperSepia,
            isWebViewReady: false,
            loadingPhase: "標記生字…",
            underlineProgress: 0.68,
            chrome: .init(header: .compact, overlay: .none),
            totalProgression: 0.18,
            bookTitle: "The Left Hand of Darkness",
        ),
        showsErrorCard: false
    )
}

#Preview("Reader Chrome / Compact") {
    ReaderChromePreviewScene(
        state: .init(
            paperColor: AppColors.paperSepia,
            isWebViewReady: true,
            loadingPhase: "開啟書本…",
            underlineProgress: nil,
            chrome: .init(header: .compact, overlay: .none),
            totalProgression: 0.37,
            bookTitle: "The Left Hand of Darkness",
        ),
        showsErrorCard: false
    )
}

#Preview("Reader Chrome / Expanded") {
    ReaderChromePreviewScene(
        state: .init(
            paperColor: AppColors.paperSepia,
            isWebViewReady: true,
            loadingPhase: "開啟書本…",
            underlineProgress: nil,
            chrome: .init(header: .expanded, overlay: .none),
            totalProgression: 0.37,
            bookTitle: "The Left Hand of Darkness",
        ),
        showsErrorCard: false
    )
}

#Preview("Reader Chrome / Translation") {
    ReaderChromePreviewScene(
        state: .init(
            paperColor: AppColors.paperSepiaDeep,
            isWebViewReady: true,
            loadingPhase: "開啟書本…",
            underlineProgress: nil,
            chrome: .init(header: .compact, overlay: .translation),
            totalProgression: 0.37,
            bookTitle: "The Left Hand of Darkness",
        ),
        showsErrorCard: false
    )
}

#Preview("Reader Chrome / Error") {
    ReaderChromePreviewScene(
        state: .init(
            paperColor: AppColors.paperSepiaDeep,
            isWebViewReady: true,
            loadingPhase: "開啟書本…",
            underlineProgress: nil,
            chrome: .init(header: .compact, overlay: .none),
            totalProgression: 0,
            bookTitle: "The Left Hand of Darkness",
        ),
        showsErrorCard: true
    )
}

#Preview("Reader Chrome / Underline Progress") {
    ReaderChromePreviewScene(
        state: .init(
            paperColor: AppColors.paperSepia,
            isWebViewReady: true,
            loadingPhase: "標記生字…",
            underlineProgress: 0.55,
            chrome: .init(header: .compact, overlay: .none),
            totalProgression: 0.22,
            bookTitle: "The Left Hand of Darkness",
        ),
        showsErrorCard: false
    )
}
#endif
