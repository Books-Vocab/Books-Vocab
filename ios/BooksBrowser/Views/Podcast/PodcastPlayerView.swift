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
    @Environment(\.scenePhase) private var scenePhase

    @State private var viewModel: PodcastPlayerViewModel?
    @State private var translationHandler = PodcastTranslationHandler()
    @State private var lastSavedTime: TimeInterval = 0
    @State private var loadTask: Task<Void, Never>?
    @State private var loadedEpisodeId: String?
    @State private var progressRestored = false

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
        // `.task(id:)` reloads when episodeId changes; loadedEpisodeId flag
        // tracks which episode the current VM is loading so we correctly reload
        // on parent-driven id swaps (e.g. future "next episode" button).
        .task(id: episodeId) {
            guard loadedEpisodeId != episodeId else { return }
            // Cancel any in-flight load BEFORE tearing down the VM — otherwise
            // the old task can still resume after stop() and call loadEpisode()
            // on the now-detached VM, spawning a second AVPlayer.
            loadTask?.cancel()
            loadTask = nil
            viewModel?.stop()
            viewModel = nil
            loadedEpisodeId = episodeId
            progressRestored = false
            lastSavedTime = 0
            loadEpisode()
        }
        .onChange(of: viewModel?.currentTime) { _, newTime in
            guard let vm = viewModel, let newTime,
                  vm.state == .playing else { return }
            saveProgressIfNeeded(time: newTime)
        }
        .onChange(of: viewModel?.state) { _, newState in
            // Defer restoreProgress until the item is genuinely ready; seeking on
            // an un-ready AVPlayer item silently drops the target time.
            // CRITICAL: if we just restored, do NOT fall through to saveProgress —
            // vm.seek is async, currentTime is still 0 this tick, and saveProgress
            // would overwrite lastPlayedTime with 0 before the seek lands.
            if newState == .ready, !progressRestored, let vm = viewModel {
                progressRestored = true
                restoreProgress(vm: vm, episodeRemoteId: episodeId)
                return
            }
            if newState == .paused || newState == .ready {
                saveProgress()
            }
        }
        .onDisappear {
            // Save before teardown — shutdown() flips state to .idle which the
            // onChange path would otherwise skip, losing up to 10s of progress.
            saveProgress()
            loadTask?.cancel()
            loadTask = nil
            // shutdown = full teardown (session deactivate + remote commands off).
            viewModel?.shutdown()
            viewModel = nil
            loadedEpisodeId = nil
            progressRestored = false
        }
        .onChange(of: scenePhase) { _, phase in
            // App backgrounded / inactive → persist latest position; no
            // .paused / .ready transition fires for a scene-phase change alone.
            if phase != .active { saveProgress() }
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
                Button("重試") { reloadEpisode() }
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

    /// Retry helper — resets per-load flags so the retry truly starts clean
    /// (otherwise progressRestored stays true and restoreProgress never fires).
    private func reloadEpisode() {
        loadTask?.cancel()
        loadTask = nil
        viewModel?.stop()
        viewModel = nil
        progressRestored = false
        lastSavedTime = 0
        loadEpisode()
    }

    private func loadEpisode() {
        let targetId = episodeId
        let descriptor = FetchDescriptor<PodcastEpisode>(
            predicate: #Predicate { $0.remoteId == targetId }
        )
        guard let episode = try? modelContext.fetch(descriptor).first,
              let series = episode.series else { return }

        // Cancel stale task BEFORE installing the new VM so an in-flight
        // closure can't land on the fresh VM.
        loadTask?.cancel()
        loadTask = nil

        let vm = PodcastPlayerViewModel(hostNames: series.hostNames)
        viewModel = vm

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
                // Per-request 10s timeout + cancellation check so a flaky server
                // can't block audio load for 60s (default URLSession timeout).
                var subtitleContent: String?
                if let subtitleURLStr = episode.subtitleURL {
                    if let data = try? await PodcastSyncService.authedData(from: subtitleURLStr, kgService: kgService) {
                        subtitleContent = String(data: data, encoding: .utf8)
                    }
                }
                if Task.isCancelled { return }

                let episodeTitle = episode.displayTitle
                await MainActor.run {
                    vm.loadEpisode(
                        audioURL: audioURL,
                        subtitleContent: subtitleContent,
                        title: episodeTitle
                    )
                }
                // restoreProgress is now triggered by .ready state observer,
                // after AVPlayer's item has actually reached a seekable state.
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
        // Guard 1: don't write stale VM's currentTime under NEW episodeId
        // during a fast episode swap (old VM emits .paused during stop()).
        guard loadedEpisodeId == episodeId else { return }
        // Guard 2: don't overwrite a saved lastPlayedTime with 0 during the
        // window between AVPlayer reaching .ready and restoreProgress seeking
        // to the saved position — scenePhase / onDisappear may fire in that gap.
        if !progressRestored && vm.currentTime == 0 { return }
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
        do {
            try modelContext.save()
        } catch {
            AppLog.app.error("PodcastProgress save failed: \(error.localizedDescription)")
        }
    }
}
#endif
