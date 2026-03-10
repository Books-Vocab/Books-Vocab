import SwiftUI

enum HeaderState: Equatable {
    case compact
    case expanded
}

enum ReaderChromeOverlay: Equatable {
    case none
    case translation
    case settings
}

struct ReaderChromeState: Equatable {
    var header: HeaderState = .compact
    var overlay: ReaderChromeOverlay = .none

    var blocksReaderInteraction: Bool {
        overlay != .none
    }

    var showsHeader: Bool {
        overlay == .none
    }
}

struct ReaderViewPresenterState {
    let paperColor: Color
    let isWebViewReady: Bool
    let loadingPhase: String
    let underlineProgress: Double?
    let chrome: ReaderChromeState
    let totalProgression: Double
    let bookTitle: String
    let panelMode: TranslationPanelMode
}

struct ReaderViewPresenter<MainContent: View, TranslationPanelContent: View, SettingsPanelContent: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin

    let state: ReaderViewPresenterState
    let onDismiss: () -> Void
    let onShowTableOfContents: () -> Void
    let onShowReaderSettings: () -> Void
    let onExpandHeader: () -> Void
    let onCollapseHeader: () -> Void
    @ViewBuilder let mainContent: MainContent
    @ViewBuilder let translationPanel: TranslationPanelContent
    @ViewBuilder let settingsPanel: SettingsPanelContent

    init(
        state: ReaderViewPresenterState,
        onDismiss: @escaping () -> Void,
        onShowTableOfContents: @escaping () -> Void,
        onShowReaderSettings: @escaping () -> Void,
        onExpandHeader: @escaping () -> Void,
        onCollapseHeader: @escaping () -> Void,
        @ViewBuilder mainContent: () -> MainContent,
        @ViewBuilder translationPanel: () -> TranslationPanelContent,
        @ViewBuilder settingsPanel: () -> SettingsPanelContent
    ) {
        self.state = state
        self.onDismiss = onDismiss
        self.onShowTableOfContents = onShowTableOfContents
        self.onShowReaderSettings = onShowReaderSettings
        self.onExpandHeader = onExpandHeader
        self.onCollapseHeader = onCollapseHeader
        self.mainContent = mainContent()
        self.translationPanel = translationPanel()
        self.settingsPanel = settingsPanel()
    }

    var body: some View {
        ZStack {
            state.paperColor.ignoresSafeArea()

            mainContent

            if !state.isWebViewReady {
                loadingOverlay
            }

            if let progress = state.underlineProgress {
                underlineProgressOverlay(progress)
            }

            bottomOverlay
            topOverlay
        }
    }

    private var loadingOverlay: some View {
        Group {
            if state.panelMode == .vocab {
                state.paperColor.ignoresSafeArea()
                    .overlay {
                        AppSectionCard(style: .vocab(vocabSkin)) {
                            VStack(spacing: ReaderPresentationMetrics.Overlay.loadingSpacing) {
                                ProgressView()
                                    .tint(vocabSkin.palette.primaryText)
                                Text(state.loadingPhase)
                                    .font(vocabSkin.typography.body.weight(.semibold))
                                    .foregroundStyle(vocabSkin.palette.primaryText)
                                    .contentTransition(.numericText())
                                    .animation(AppMotion.loadingState, value: state.loadingPhase)
                            }
                            .padding(.horizontal, ReaderPresentationMetrics.Overlay.loadingHorizontalInset)
                            .padding(.vertical, ReaderPresentationMetrics.Overlay.loadingVerticalInset)
                        }
                        .frame(maxWidth: ReaderPresentationMetrics.Overlay.loadingMaxWidth)
                        .padding(.horizontal, ReaderPresentationMetrics.Overlay.loadingOuterInset)
                    }
            } else {
                state.paperColor.ignoresSafeArea()
                    .overlay {
                        VStack(spacing: ReaderPresentationMetrics.Overlay.loadingSpacing) {
                            ProgressView()
                                .tint(.primary)
                            Text(state.loadingPhase)
                                .font(ReaderGlassTypography.body)
                                .fontWeight(.medium)
                                .foregroundStyle(.primary)
                                .contentTransition(.numericText())
                                .animation(AppMotion.loadingState, value: state.loadingPhase)
                        }
                        .padding(.horizontal, ReaderPresentationMetrics.Overlay.loadingHorizontalInset)
                        .padding(.vertical, ReaderPresentationMetrics.Overlay.loadingVerticalInset)
                        .glassEffect(
                            .regular,
                            in: .rect(cornerRadius: ReaderPresentationMetrics.Panel.cornerRadius)
                        )
                    }
            }
        }
    }

    private func underlineProgressOverlay(_ progress: Double) -> some View {
        VStack {
            Group {
                if state.panelMode == .vocab {
                    AppSectionCard(style: .vocab(vocabSkin)) {
                        HStack(spacing: 10) {
                            ZStack(alignment: .leading) {
                                Capsule()
                                    .fill(vocabSkin.palette.mutedFill)
                                    .frame(
                                        width: ReaderPresentationMetrics.Overlay.progressBarWidth,
                                        height: ReaderPresentationMetrics.Overlay.progressBarHeight
                                    )
                                Capsule()
                                    .fill(vocabSkin.palette.accent)
                                    .frame(
                                        width: max(
                                            ReaderPresentationMetrics.Overlay.progressBarHeight,
                                            ReaderPresentationMetrics.Overlay.progressBarWidth * progress
                                        ),
                                        height: ReaderPresentationMetrics.Overlay.progressBarHeight
                                    )
                                    .animation(AppMotion.progressLinear, value: progress)
                            }
                            Text("\(Int(progress * 100))%")
                                .font(vocabSkin.typography.monoLabel)
                                .foregroundStyle(vocabSkin.palette.secondaryText)
                                .frame(width: ReaderPresentationMetrics.Overlay.progressTextWidth, alignment: .trailing)
                        }
                        .padding(.horizontal, ReaderPresentationMetrics.Overlay.progressHorizontalInset)
                        .padding(.vertical, ReaderPresentationMetrics.Overlay.progressVerticalInset)
                    }
                } else {
                    HStack(spacing: 10) {
                        ZStack(alignment: .leading) {
                            Capsule()
                                .fill(.quaternary)
                                .frame(
                                    width: ReaderPresentationMetrics.Overlay.progressBarWidth,
                                    height: ReaderPresentationMetrics.Overlay.progressBarHeight
                                )
                            Capsule()
                                .fill(Color.accentColor)
                                .frame(
                                    width: max(
                                        ReaderPresentationMetrics.Overlay.progressBarHeight,
                                        ReaderPresentationMetrics.Overlay.progressBarWidth * progress
                                    ),
                                    height: ReaderPresentationMetrics.Overlay.progressBarHeight
                                )
                                .animation(AppMotion.progressLinear, value: progress)
                        }
                        Text("\(Int(progress * 100))%")
                            .font(ReaderGlassTypography.progressText)
                            .foregroundStyle(.secondary)
                            .frame(width: ReaderPresentationMetrics.Overlay.progressTextWidth, alignment: .trailing)
                    }
                    .padding(.horizontal, ReaderPresentationMetrics.Overlay.progressHorizontalInset)
                    .padding(.vertical, ReaderPresentationMetrics.Overlay.progressVerticalInset)
                    .glassEffect(.regular, in: .capsule)
                }
            }
            .padding(.top, ReaderPresentationMetrics.Overlay.topInset)

            Spacer()
        }
        .allowsHitTesting(false)
        .transition(.overlayFade)
    }

    private var bottomOverlay: some View {
        VStack {
            Spacer()

            if state.chrome.overlay == .translation {
                translationPanel
                    .padding(.horizontal)
                    .padding(.bottom, ReaderPresentationMetrics.Overlay.bottomInset)
            } else if state.chrome.overlay == .settings && state.panelMode == .vocab {
                settingsPanel
                    .padding(.horizontal)
                    .padding(.bottom, ReaderPresentationMetrics.Overlay.bottomInset)
            }
        }
        .animation(AppMotion.panelState, value: state.chrome.overlay)
    }

    private var topOverlay: some View {
        VStack {
            if state.chrome.showsHeader {
                switch (state.panelMode, state.chrome.header) {
                case (.vocab, .expanded):
                    vocabExpandedHeader
                case (.vocab, .compact):
                    vocabCompactHeader
                case (_, .expanded):
                    glassExpandedHeader
                case (_, .compact):
                    glassCompactHeader
                }
            }

            Spacer()
        }
    }

    private var glassExpandedHeader: some View {
        GlassEffectContainer {
            HStack(spacing: 0) {
                Button(action: onDismiss) {
                    HStack(spacing: 4) {
                        Image(systemName: "chevron.left")
                            .font(ReaderGlassTypography.headerBackIcon)
                        Text("書庫")
                            .font(ReaderGlassTypography.headerBackLabel)
                    }
                    .foregroundStyle(.primary)
                    .padding(.leading, ReaderPresentationMetrics.Header.trailingInset)
                }

                Spacer()

                Text(state.bookTitle)
                    .font(ReaderGlassTypography.headerTitle)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .frame(maxWidth: ReaderPresentationMetrics.Header.titleMaxWidth)

                Spacer()

                HStack(spacing: 2) {
                    Button(action: onShowTableOfContents) {
                        Image(systemName: "list.bullet")
                            .font(ReaderGlassTypography.headerAction)
                            .foregroundStyle(.primary)
                            .frame(
                                width: ReaderPresentationMetrics.Header.buttonSize,
                                height: ReaderPresentationMetrics.Header.buttonSize
                            )
                            .contentShape(Rectangle())
                    }

                    Button(action: onShowReaderSettings) {
                        Image(systemName: "textformat.size")
                            .font(ReaderGlassTypography.headerAction)
                            .foregroundStyle(.primary)
                            .frame(
                                width: ReaderPresentationMetrics.Header.buttonSize,
                                height: ReaderPresentationMetrics.Header.buttonSize
                            )
                            .contentShape(Rectangle())
                    }

                    Button(action: onCollapseHeader) {
                        Image(systemName: "chevron.up")
                            .font(ReaderGlassTypography.headerCollapse)
                            .foregroundStyle(.primary)
                            .frame(
                                width: ReaderPresentationMetrics.Header.buttonSize,
                                height: ReaderPresentationMetrics.Header.buttonSize
                            )
                            .contentShape(Rectangle())
                    }
                }
                .padding(.trailing, ReaderPresentationMetrics.Header.trailingInset)
            }
            .padding(.horizontal, ReaderPresentationMetrics.Header.contentHorizontalInset)
            .padding(.vertical, ReaderPresentationMetrics.Header.contentVerticalInset)
        }
        .glassEffect(in: Capsule())
        .shadow(
            color: .black.opacity(ReaderPresentationMetrics.Header.shadowOpacity),
            radius: ReaderPresentationMetrics.Header.expandedShadowRadius,
            x: 0,
            y: ReaderPresentationMetrics.Header.shadowY
        )
        .padding(.horizontal, ReaderPresentationMetrics.Header.outerHorizontalInset)
        .padding(.top, ReaderPresentationMetrics.Header.outerTopInset)
        .transition(.headerSwap)
    }

    private var glassCompactHeader: some View {
        HStack(spacing: ReaderPresentationMetrics.Header.compactSpacing) {
            Spacer()

            if state.totalProgression > 0 {
                Text(String(format: "%.1f%%", state.totalProgression * 100))
                    .font(ReaderGlassTypography.progressText)
                    .foregroundStyle(.tertiary)
                    .padding(.trailing, ReaderPresentationMetrics.Header.trailingInset)
            }

            Button(action: onExpandHeader) {
                GlassEffectContainer {
                    Image(systemName: "ellipsis")
                        .font(ReaderGlassTypography.compactMenuIcon)
                        .foregroundStyle(.secondary)
                        .frame(
                            width: ReaderPresentationMetrics.Header.compactButtonSize,
                            height: ReaderPresentationMetrics.Header.compactButtonSize
                        )
                        .contentShape(Circle())
                }
                .glassEffect(in: Circle())
                .shadow(
                    color: .black.opacity(ReaderPresentationMetrics.Header.shadowOpacity),
                    radius: ReaderPresentationMetrics.Header.compactShadowRadius,
                    x: 0,
                    y: ReaderPresentationMetrics.Header.shadowY
                )
            }
        }
        .padding(.trailing, ReaderPresentationMetrics.Header.outerHorizontalInset)
        .transition(.headerSwap)
    }

    private var vocabExpandedHeader: some View {
        AppSectionCard(padding: 0, style: .vocab(vocabSkin)) {
            HStack(spacing: 10) {
                Button(action: onDismiss) {
                    HStack(spacing: 6) {
                        Image(systemName: "chevron.left")
                            .font(vocabSkin.typography.iconToolbar)
                        Text("書庫")
                            .font(vocabSkin.typography.body.weight(.semibold))
                    }
                    .foregroundStyle(vocabSkin.palette.primaryText)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)

                Spacer()

                Text(state.bookTitle)
                    .font(vocabSkin.typography.captionStrong)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
                    .lineLimit(1)
                    .frame(maxWidth: ReaderPresentationMetrics.Header.titleMaxWidth)

                Spacer()

                HStack(spacing: 6) {
                    VocabChromeIconButton(systemImage: "list.bullet", action: onShowTableOfContents)
                    VocabChromeIconButton(systemImage: "textformat.size", action: onShowReaderSettings)
                    VocabChromeIconButton(systemImage: "chevron.up", action: onCollapseHeader)
                }
            }
            .padding(.horizontal, ReaderPresentationMetrics.Header.contentHorizontalInset + 2)
            .padding(.vertical, ReaderPresentationMetrics.Header.contentVerticalInset)
        }
        .padding(.horizontal, ReaderPresentationMetrics.Header.outerHorizontalInset)
        .padding(.top, ReaderPresentationMetrics.Header.outerTopInset)
        .transition(.headerSwap)
    }

    private var vocabCompactHeader: some View {
        HStack(spacing: ReaderPresentationMetrics.Header.compactSpacing) {
            Spacer()

            if state.totalProgression > 0 {
                HStack(spacing: 6) {
                    Image(systemName: "book.closed")
                        .font(vocabSkin.typography.iconSmall)
                    Text(String(format: "%.1f%%", state.totalProgression * 100))
                        .font(vocabSkin.typography.monoLabel)
                }
                .foregroundStyle(vocabSkin.palette.secondaryText)
                .padding(.horizontal, ReaderPresentationMetrics.Header.compactProgressInsetHorizontal)
                .padding(.vertical, ReaderPresentationMetrics.Header.compactProgressInsetVertical)
                .background(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .fill(vocabSkin.palette.cardBackground)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
                )
            }

            VocabChromeIconButton(systemImage: "ellipsis", action: onExpandHeader)
        }
        .padding(.trailing, ReaderPresentationMetrics.Header.outerHorizontalInset)
        .padding(.top, ReaderPresentationMetrics.Header.outerTopInset)
        .transition(.headerSwap)
    }
}

private struct ReaderChromePreviewScene: View {
    let state: ReaderViewPresenterState

    var body: some View {
        ReaderViewPresenter(
            state: state,
            onDismiss: {},
            onShowTableOfContents: {},
            onShowReaderSettings: {},
            onExpandHeader: {},
            onCollapseHeader: {}
        ) {
            ZStack {
                LinearGradient(
                    colors: [
                        state.paperColor.opacity(0.96),
                        state.paperColor.opacity(0.88),
                        Color.brown.opacity(0.08)
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )

                VStack(alignment: .leading, spacing: ReaderPresentationMetrics.Preview.blockSpacing) {
                    ForEach(0..<8, id: \.self) { index in
                        RoundedRectangle(cornerRadius: ReaderPresentationMetrics.Preview.blockCornerRadius, style: .continuous)
                            .fill(Color.primary.opacity(index == 2 ? 0.22 : 0.12))
                            .frame(height: index.isMultiple(of: 3) ? 12 : 10)
                            .padding(.trailing, CGFloat(index % 3) * ReaderPresentationMetrics.Preview.trailingStep)
                    }
                    Spacer()
                }
                .padding(.top, ReaderPresentationMetrics.Preview.topInset)
                .padding(.horizontal, ReaderPresentationMetrics.Preview.horizontalInset)
                .padding(.bottom, ReaderPresentationMetrics.Preview.bottomInset)
            }
            .ignoresSafeArea()
        } translationPanel: {
            TranslationPanel(
                word: "resilient",
                result: TranslationResult(
                    translation: "有韌性的；能快速恢復的",
                    partOfSpeech: "adj.",
                    pronunciation: nil,
                    explanation: nil
                ),
                pronunciation: "/rɪˈzɪljənt/",
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
                onDismiss: {}
            )
        } settingsPanel: {
            EmptyView()
        }
    }
}

#Preview("Reader Chrome / Loading") {
    ReaderChromePreviewScene(
        state: .init(
            paperColor: Color(red: 0.96, green: 0.93, blue: 0.87),
            isWebViewReady: false,
            loadingPhase: "渲染頁面…",
            underlineProgress: 0.42,
            chrome: .init(header: .compact, overlay: .none),
            totalProgression: 0.18,
            bookTitle: "The Left Hand of Darkness",
            panelMode: .glass
        )
    )
}

#Preview("Reader Chrome / Compact") {
    ReaderChromePreviewScene(
        state: .init(
            paperColor: Color(red: 0.97, green: 0.95, blue: 0.9),
            isWebViewReady: true,
            loadingPhase: "開啟書本…",
            underlineProgress: nil,
            chrome: .init(header: .compact, overlay: .none),
            totalProgression: 0.37,
            bookTitle: "The Left Hand of Darkness",
            panelMode: .glass
        )
    )
}

#Preview("Reader Chrome / Expanded") {
    ReaderChromePreviewScene(
        state: .init(
            paperColor: Color(red: 0.97, green: 0.95, blue: 0.9),
            isWebViewReady: true,
            loadingPhase: "開啟書本…",
            underlineProgress: nil,
            chrome: .init(header: .expanded, overlay: .none),
            totalProgression: 0.37,
            bookTitle: "The Left Hand of Darkness",
            panelMode: .glass
        )
    )
}

#Preview("Reader Chrome / Translation") {
    ReaderChromePreviewScene(
        state: .init(
            paperColor: Color(red: 0.95, green: 0.92, blue: 0.86),
            isWebViewReady: true,
            loadingPhase: "開啟書本…",
            underlineProgress: nil,
            chrome: .init(header: .compact, overlay: .translation),
            totalProgression: 0.37,
            bookTitle: "The Left Hand of Darkness",
            panelMode: .glass
        )
    )
}
