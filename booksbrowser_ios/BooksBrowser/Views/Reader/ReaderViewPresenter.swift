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
                            VStack(spacing: 14) {
                                ProgressView()
                                    .tint(vocabSkin.palette.primaryText)
                                Text(state.loadingPhase)
                                    .font(vocabSkin.typography.body.weight(.semibold))
                                    .foregroundStyle(vocabSkin.palette.primaryText)
                                    .contentTransition(.numericText())
                                    .animation(.default, value: state.loadingPhase)
                            }
                            .padding(.horizontal, 28)
                            .padding(.vertical, 20)
                        }
                        .frame(maxWidth: 320)
                        .padding(.horizontal, 20)
                    }
            } else {
                state.paperColor.ignoresSafeArea()
                    .overlay {
                        VStack(spacing: 14) {
                            ProgressView()
                                .tint(.primary)
                            Text(state.loadingPhase)
                                .font(.subheadline)
                                .fontWeight(.medium)
                                .foregroundStyle(.primary)
                                .contentTransition(.numericText())
                                .animation(.default, value: state.loadingPhase)
                        }
                        .padding(.horizontal, 28)
                        .padding(.vertical, 20)
                        .glassEffect(.regular, in: .rect(cornerRadius: 20))
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
                                    .frame(width: 80, height: 3)
                                Capsule()
                                    .fill(vocabSkin.palette.accent)
                                    .frame(width: max(3, 80 * progress), height: 3)
                                    .animation(.linear(duration: 0.1), value: progress)
                            }
                            Text("\(Int(progress * 100))%")
                                .font(vocabSkin.typography.monoLabel)
                                .foregroundStyle(vocabSkin.palette.secondaryText)
                                .frame(width: 30, alignment: .trailing)
                        }
                        .padding(.horizontal, 16)
                        .padding(.vertical, 10)
                    }
                } else {
                    HStack(spacing: 10) {
                        ZStack(alignment: .leading) {
                            Capsule()
                                .fill(.quaternary)
                                .frame(width: 80, height: 3)
                            Capsule()
                                .fill(Color.accentColor)
                                .frame(width: max(3, 80 * progress), height: 3)
                                .animation(.linear(duration: 0.1), value: progress)
                        }
                        Text("\(Int(progress * 100))%")
                            .font(.system(size: 11, weight: .medium, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .frame(width: 30, alignment: .trailing)
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 10)
                    .glassEffect(.regular, in: .capsule)
                }
            }
            .padding(.top, 8)

            Spacer()
        }
        .allowsHitTesting(false)
        .transition(.opacity)
    }

    private var bottomOverlay: some View {
        VStack {
            Spacer()

            if state.chrome.overlay == .translation {
                translationPanel
                    .padding(.horizontal)
                    .padding(.bottom, 8)
            } else if state.chrome.overlay == .settings && state.panelMode == .vocab {
                settingsPanel
                    .padding(.horizontal)
                    .padding(.bottom, 8)
            }
        }
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
                            .font(.system(size: 15, weight: .semibold))
                        Text("書庫")
                            .font(.system(size: 15))
                    }
                    .foregroundStyle(.primary)
                    .padding(.leading, 4)
                }

                Spacer()

                Text(state.bookTitle)
                    .font(.caption)
                    .fontWeight(.medium)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .frame(maxWidth: 160)

                Spacer()

                HStack(spacing: 2) {
                    Button(action: onShowTableOfContents) {
                        Image(systemName: "list.bullet")
                            .font(.system(size: 15))
                            .foregroundStyle(.primary)
                            .frame(width: 34, height: 34)
                            .contentShape(Rectangle())
                    }

                    Button(action: onShowReaderSettings) {
                        Image(systemName: "textformat.size")
                            .font(.system(size: 15))
                            .foregroundStyle(.primary)
                            .frame(width: 34, height: 34)
                            .contentShape(Rectangle())
                    }

                    Button(action: onCollapseHeader) {
                        Image(systemName: "chevron.up")
                            .font(.system(size: 14, weight: .semibold))
                            .foregroundStyle(.primary)
                            .frame(width: 34, height: 34)
                            .contentShape(Rectangle())
                    }
                }
                .padding(.trailing, 4)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
        }
        .glassEffect(in: Capsule())
        .shadow(color: .black.opacity(0.08), radius: 16, x: 0, y: 4)
        .padding(.horizontal, 20)
        .padding(.top, 8)
        .transition(.scale(scale: 0.8, anchor: .topTrailing).combined(with: .opacity))
    }

    private var glassCompactHeader: some View {
        HStack(spacing: 8) {
            Spacer()

            if state.totalProgression > 0 {
                Text(String(format: "%.1f%%", state.totalProgression * 100))
                    .font(.system(size: 11, weight: .light, design: .monospaced))
                    .foregroundStyle(.tertiary)
                    .padding(.trailing, 4)
            }

            Button(action: onExpandHeader) {
                GlassEffectContainer {
                    Image(systemName: "ellipsis")
                        .font(.system(size: 18, weight: .medium))
                        .foregroundStyle(.secondary)
                        .frame(width: 44, height: 44)
                        .contentShape(Circle())
                }
                .glassEffect(in: Circle())
                .shadow(color: .black.opacity(0.08), radius: 10, x: 0, y: 4)
            }
        }
        .padding(.trailing, 20)
        .transition(.scale(scale: 0.8, anchor: .topTrailing).combined(with: .opacity))
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
                    .frame(maxWidth: 160)

                Spacer()

                HStack(spacing: 6) {
                    VocabChromeIconButton(systemImage: "list.bullet", action: onShowTableOfContents)
                    VocabChromeIconButton(systemImage: "textformat.size", action: onShowReaderSettings)
                    VocabChromeIconButton(systemImage: "chevron.up", action: onCollapseHeader)
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
        }
        .padding(.horizontal, 20)
        .padding(.top, 8)
        .transition(.scale(scale: 0.8, anchor: .topTrailing).combined(with: .opacity))
    }

    private var vocabCompactHeader: some View {
        HStack(spacing: 8) {
            Spacer()

            if state.totalProgression > 0 {
                HStack(spacing: 6) {
                    Image(systemName: "book.closed")
                        .font(vocabSkin.typography.iconSmall)
                    Text(String(format: "%.1f%%", state.totalProgression * 100))
                        .font(vocabSkin.typography.monoLabel)
                }
                .foregroundStyle(vocabSkin.palette.secondaryText)
                .padding(.horizontal, 10)
                .padding(.vertical, 8)
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
        .padding(.trailing, 20)
        .padding(.top, 8)
        .transition(.scale(scale: 0.8, anchor: .topTrailing).combined(with: .opacity))
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

                VStack(alignment: .leading, spacing: 18) {
                    ForEach(0..<8, id: \.self) { index in
                        RoundedRectangle(cornerRadius: 4, style: .continuous)
                            .fill(Color.primary.opacity(index == 2 ? 0.22 : 0.12))
                            .frame(height: index.isMultiple(of: 3) ? 12 : 10)
                            .padding(.trailing, CGFloat((index % 3) * 28))
                    }
                    Spacer()
                }
                .padding(.top, 120)
                .padding(.horizontal, 28)
                .padding(.bottom, 60)
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
