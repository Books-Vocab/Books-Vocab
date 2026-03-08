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
}

struct ReaderViewPresenter<MainContent: View, TranslationPanelContent: View>: View {
    let state: ReaderViewPresenterState
    let onDismiss: () -> Void
    let onShowTableOfContents: () -> Void
    let onShowReaderSettings: () -> Void
    let onExpandHeader: () -> Void
    let onCollapseHeader: () -> Void
    @ViewBuilder let mainContent: MainContent
    @ViewBuilder let translationPanel: TranslationPanelContent

    init(
        state: ReaderViewPresenterState,
        onDismiss: @escaping () -> Void,
        onShowTableOfContents: @escaping () -> Void,
        onShowReaderSettings: @escaping () -> Void,
        onExpandHeader: @escaping () -> Void,
        onCollapseHeader: @escaping () -> Void,
        @ViewBuilder mainContent: () -> MainContent,
        @ViewBuilder translationPanel: () -> TranslationPanelContent
    ) {
        self.state = state
        self.onDismiss = onDismiss
        self.onShowTableOfContents = onShowTableOfContents
        self.onShowReaderSettings = onShowReaderSettings
        self.onExpandHeader = onExpandHeader
        self.onCollapseHeader = onCollapseHeader
        self.mainContent = mainContent()
        self.translationPanel = translationPanel()
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

    private func underlineProgressOverlay(_ progress: Double) -> some View {
        VStack {
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
            }
        }
    }

    private var topOverlay: some View {
        VStack {
            if state.chrome.showsHeader {
                switch state.chrome.header {
                case .expanded:
                    expandedHeader
                case .compact:
                    compactHeader
                }
            }

            Spacer()
        }
    }

    private var expandedHeader: some View {
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

    private var compactHeader: some View {
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
}
