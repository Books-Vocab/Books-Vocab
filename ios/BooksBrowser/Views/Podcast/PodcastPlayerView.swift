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
    @Environment(\.kgService) private var kgService

    @State private var viewModel: PodcastPlayerViewModel?
    @State private var translationHandler = PodcastTranslationHandler()
    @State private var lastSavedTime: TimeInterval = 0
    @State private var loadTask: Task<Void, Never>?

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
        // `.task(id:)` reloads when episodeId changes (parent swap) and avoids
        // re-firing on every appear cycle; guard against re-runs via viewModel check.
        .task(id: episodeId) {
            guard viewModel == nil else { return }
            loadEpisode()
        }
        .onChange(of: viewModel?.currentTime) { _, newTime in
            guard let vm = viewModel, let newTime,
                  vm.state == .playing else { return }
            saveProgressIfNeeded(time: newTime)
        }
        .onChange(of: viewModel?.state) { _, newState in
            if newState == .paused || newState == .ready {
                saveProgress()
            }
        }
        .onDisappear {
            loadTask?.cancel()
            loadTask = nil
            viewModel?.stop()
            viewModel = nil
        }
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

        loadTask?.cancel()
        loadTask = Task { [weak vm] in
            guard let vm else { return }
            do {
                guard let audioURLStr = episode.audioURL,
                      let audioURL = URL(string: audioURLStr) else {
                    await MainActor.run { vm.reportError("無音訊 URL") }
                    return
                }

                await MainActor.run { vm.setLoading() }
                if Task.isCancelled { return }

                // Subtitle is best-effort — audio can play without it.
                var subtitleContent: String?
                if let subtitleURLStr = episode.subtitleURL {
                    if let data = try? await PodcastSyncService.authedData(from: subtitleURLStr, kgService: kgService) {
                        subtitleContent = String(data: data, encoding: .utf8)
                    }
                }
                if Task.isCancelled { return }

                await MainActor.run {
                    vm.loadEpisode(audioURL: audioURL, subtitleContent: subtitleContent)
                }
                if Task.isCancelled { return }

                await restoreProgress(vm: vm, episodeRemoteId: episode.remoteId)
            } catch is CancellationError {
                return
            } catch {
                await MainActor.run {
                    vm.reportError("載入失敗：\(error.localizedDescription)")
                }
            }
        }
    }

    @MainActor
    private func restoreProgress(vm: PodcastPlayerViewModel, episodeRemoteId: String) {
        let targetId = episodeRemoteId
        let descriptor = FetchDescriptor<PodcastProgress>(
            predicate: #Predicate { $0.episodeRemoteId == targetId }
        )
        if let progress = try? modelContext.fetch(descriptor).first,
           progress.lastPlayedTime > 0,
           !progress.completed {
            vm.seek(to: progress.lastPlayedTime)
        }
    }

    private func saveProgressIfNeeded(time: TimeInterval) {
        guard abs(time - lastSavedTime) > 10 else { return }
        lastSavedTime = time
        saveProgress()
    }

    private func saveProgress() {
        guard let vm = viewModel else { return }
        let targetId = episodeId
        let descriptor = FetchDescriptor<PodcastProgress>(
            predicate: #Predicate { $0.episodeRemoteId == targetId }
        )
        let progress: PodcastProgress
        if let existing = try? modelContext.fetch(descriptor).first {
            progress = existing
        } else {
            progress = PodcastProgress(episodeRemoteId: episodeId)
            modelContext.insert(progress)
        }
        progress.lastPlayedTime = vm.currentTime
        // completed must require a real duration — AVPlayer reports duration = 0
        // until async asset metadata loads, which would otherwise trip
        // `currentTime >= 0 - 1` = true and falsely mark a fresh episode complete.
        progress.completed = (
            vm.state == .ready
            && vm.duration > 0
            && vm.currentTime >= vm.duration - 1
        )
        progress.updatedAt = Date()
        try? modelContext.save()
    }
}
#endif
