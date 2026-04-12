#if os(iOS)
//
//  PodcastPlayerView.swift
//  BooksBrowser
//
//  Podcast 播放器主頁面：載入 episode → 字幕 + 控制面板 + 翻譯面板
//

import SwiftUI
import SwiftData

struct PodcastPlayerView: View {
    let episodeId: String
    @Environment(\.vocabSkin) private var skin
    @Environment(\.appTheme) private var theme
    @Environment(\.modelContext) private var modelContext

    @State private var viewModel: PodcastPlayerViewModel?
    @State private var translationHandler = PodcastTranslationHandler()

    var body: some View {
        Group {
            if let vm = viewModel {
                playerContent(vm)
            } else {
                ProgressView("載入中…")
            }
        }
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.hidden, for: .tabBar)
        .task { loadEpisode() }
    }

    @ViewBuilder
    private func playerContent(_ vm: PodcastPlayerViewModel) -> some View {
        switch vm.state {
        case .idle, .loading:
            VStack(spacing: skin.spacing.sectionGap) {
                ProgressView()
                Text("載入音訊…")
                    .font(skin.typography.caption)
                    .foregroundStyle(skin.palette.secondaryText)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

        case .error(let msg):
            VStack(spacing: skin.spacing.sectionGap) {
                Image(systemName: "xmark.octagon")
                    .font(skin.typography.symbolHero)
                    .foregroundStyle(skin.palette.destructive)
                Text("音訊載入失敗")
                    .font(skin.typography.sectionTitle)
                Text(msg)
                    .font(skin.typography.caption)
                    .foregroundStyle(skin.palette.secondaryText)
                Button("重試") { loadEpisode() }
                    .buttonStyle(.borderedProminent)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

        case .ready, .playing, .paused:
            VStack(spacing: 0) {
                PodcastSubtitleView(viewModel: vm)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)

                PodcastControlsView(viewModel: vm)
                    .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                    .padding(.bottom, AppShellMetrics.pageBottomPadding)
            }
            .background(theme.palette.pageBackground)
            .overlay(alignment: .bottom) {
                if translationHandler.wordSelection != nil {
                    TranslationPanel(
                        word: translationHandler.wordSelection!.word,
                        result: translationHandler.translationResult,
                        isLoading: translationHandler.isTranslating,
                        isSaved: translationHandler.isSaved,
                        isLoggedIn: true,
                        isExpanded: false,
                        explanation: nil,
                        isLoadingExplanation: false,
                        statusMessage: nil,
                        isExplanationOnly: false,
                        translationErrorMessage: translationHandler.translationErrorMessage,
                        explanationErrorMessage: nil,
                        onExpand: {},
                        onDelete: {},
                        onShowDetail: nil,
                        onDismiss: { translationHandler.dismiss() }
                    )
                    .transition(.readerPanelReveal)
                }
            }
            .onChange(of: vm.activeWordSelection?.word) { _, newWord in
                guard let selection = vm.activeWordSelection else { return }
                translationHandler.handleWordTap(word: selection.word, context: selection.context)
            }
        }
    }

    private func loadEpisode() {
        let targetId = episodeId
        let descriptor = FetchDescriptor<PodcastEpisode>(
            predicate: #Predicate { $0.remoteId == targetId }
        )
        guard let episode = try? modelContext.fetch(descriptor).first,
              let series = episode.series else { return }

        let vm = PodcastPlayerViewModel(hostNames: series.hostNames)
        viewModel = vm

        // Resolve audio URL: try local path first, fall back to bundle resource
        let audioURL: URL
        if let audioPath = episode.localAudioPath, let url = URL(string: audioPath),
           FileManager.default.fileExists(atPath: url.path) {
            audioURL = url
        } else if let bundleURL = Bundle.main.url(forResource: "debug_podcast", withExtension: "mp3") {
            audioURL = bundleURL
        } else {
            vm.reportError("音訊檔案不存在")
            return
        }

        // Resolve subtitle content
        let subtitleContent: String?
        if let srtPath = episode.localSubtitlePath, let srtURL = URL(string: srtPath),
           let content = try? String(contentsOf: srtURL, encoding: .utf8) {
            subtitleContent = content
        } else if let bundleSRT = Bundle.main.url(forResource: "debug_podcast", withExtension: "srt"),
                  let content = try? String(contentsOf: bundleSRT, encoding: .utf8) {
            subtitleContent = content
        } else {
            subtitleContent = nil
        }

        vm.loadEpisode(audioURL: audioURL, subtitleContent: subtitleContent)
    }
}
#endif
