//
//  PodcastPlayerView.swift
//  BooksBrowser
//
//  Podcast 播放器主頁面：載入 episode → 字幕 + 控制面板
//

import SwiftUI
import SwiftData

struct PodcastPlayerView: View {
    let episodeId: String
    @Environment(\.vocabSkin) private var skin
    @Environment(\.appTheme) private var theme
    @Environment(\.modelContext) private var modelContext

    @State private var viewModel: PodcastPlayerViewModel?

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

        guard let audioPath = episode.localAudioPath,
              let audioURL = URL(string: audioPath) else {
            vm.state = .error("音訊檔案不存在")
            return
        }

        let subtitleContent: String?
        if let srtPath = episode.localSubtitlePath,
           let srtURL = URL(string: srtPath) {
            subtitleContent = try? String(contentsOf: srtURL, encoding: .utf8)
        } else {
            subtitleContent = nil
        }

        vm.loadEpisode(audioURL: audioURL, subtitleContent: subtitleContent)
    }
}
