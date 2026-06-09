//
//  PodcastControlsView.swift
//  Books & Vocab
//
//  Podcast 播放控制：seek bar、播放/暫停、快進快退、字幕模式、播放速率
//

import SwiftUI

struct PodcastControlsView: View {
    @ObserveInjection private var inject
    let viewModel: PodcastPlayerViewModel
    @Environment(\.appSkin) private var skin

    @State private var isDragging = false
    @State private var dragTime: TimeInterval = 0

    var body: some View {
        VStack(spacing: PodcastPlayerMetrics.controlsClusterSpacing) {
            seekBar
            HStack {
                Text(formatTime(activeTime))
                    .font(skin.typography.monoLabel)
                    .foregroundStyle(skin.palette.tertiaryText)
                Spacer()
                Text(formatTime(viewModel.duration))
                    .font(skin.typography.monoLabel)
                    .foregroundStyle(skin.palette.tertiaryText)
            }
            ZStack {
                HStack(spacing: skin.spacing.controlGap) {
                    // 15s 跳轉：ghost 風格（primaryText icon，無背景）— 次級操作
                    Button { viewModel.skip(seconds: -15) } label: {
                        Image(systemName: "gobackward.15")
                            .font(skin.typography.symbolLarge)
                            .foregroundStyle(skin.palette.primaryText)
                            .frame(minWidth: 44, minHeight: 44)
                            .contentShape(Rectangle())
                    }
                    .accessibilityLabel(L10n.string("podcast.controls.rewind15"))
                    .accessibilityIdentifier("podcast.player.rewind15Button")

                    // 主 play／pause：brandHero 奶黃 capsule CTA — 對齊整體設計語言
                    Button { viewModel.togglePlayPause() } label: {
                        Image(systemName: viewModel.state == .playing ? "pause.fill" : "play.fill")
                            .font(skin.typography.symbolLarge)
                            .foregroundStyle(AppColors.onBrandHero)
                            .frame(width: 56, height: 56)
                            .background(skin.palette.brandHero, in: Circle())
                    }
                    .accessibilityLabel(L10n.string(viewModel.state == .playing ? "podcast.controls.playpause.pause" : "podcast.controls.playpause.play"))
                    .accessibilityIdentifier("podcast.player.playPauseButton")

                    Button { viewModel.skip(seconds: 15) } label: {
                        Image(systemName: "goforward.15")
                            .font(skin.typography.symbolLarge)
                            .foregroundStyle(skin.palette.primaryText)
                            .frame(minWidth: 44, minHeight: 44)
                            .contentShape(Rectangle())
                    }
                    .accessibilityLabel(L10n.string("podcast.controls.forward15"))
                    .accessibilityIdentifier("podcast.player.forward15Button")
                }

                HStack {
                    Spacer()
                    // 速度切換：套既有 .appCompactAction(.neutral) capsule pill
                    Button { viewModel.cycleRate() } label: {
                        Text(viewModel.rateDisplayText)
                    }
                    .buttonStyle(.appCompactAction(.neutral))
                    .accessibilityLabel(L10n.string("podcast.controls.cycleRate"))
                    .accessibilityValue(viewModel.rateDisplayText)
                    .accessibilityIdentifier("podcast.player.rateButton")
                }
            }
        }
        .enableInjection()
    }

    private var activeTime: TimeInterval {
        isDragging ? dragTime : viewModel.currentTime
    }

    @ViewBuilder
    private var seekBar: some View {
        GeometryReader { geo in
            let w = geo.size.width
            ZStack(alignment: .leading) {
                Capsule()
                    .fill(skin.palette.progressBarBackground)
                    .frame(height: PodcastPlayerMetrics.seekBarTrackHeight)
                // Buffered overlay — sits between background and accent so it
                // reads as "已下載但未播" (industry-standard YouTube/Spotify
                // pattern). Uses the accent color at low opacity to stay
                // visually subordinate to the actual progress.
                Capsule()
                    .fill(skin.palette.accent.opacity(0.25))
                    .frame(width: bufferedWidth(in: w), height: PodcastPlayerMetrics.seekBarTrackHeight)
                    // Non-bouncy token: springs wobble on frequent KVO updates
                    // from loadedTimeRanges.
                    .animation(AppMotion.controlEaseOut, value: viewModel.bufferedEnd)
                Capsule()
                    .fill(skin.palette.accent)
                    .frame(width: progressWidth(in: w), height: PodcastPlayerMetrics.seekBarTrackHeight)
                Circle()
                    .fill(skin.palette.cardBackground)
                    .frame(
                        width: PodcastPlayerMetrics.seekBarThumbSize,
                        height: PodcastPlayerMetrics.seekBarThumbSize
                    )
                    .appElevation(.z1)
                    .offset(x: max(0, progressWidth(in: w) - PodcastPlayerMetrics.seekBarThumbOffset))
            }
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { v in
                        // Block scrubbing until AVPlayer reports duration;
                        // dragging earlier silently resolves to seek(0).
                        guard viewModel.duration > 0 else { return }
                        isDragging = true
                        dragTime = PodcastSeekBarGeometry.time(
                            locationX: v.location.x,
                            width: w,
                            duration: viewModel.duration
                        )
                    }
                    .onEnded { _ in
                        guard viewModel.duration > 0, isDragging else { return }
                        isDragging = false
                        viewModel.seek(to: dragTime)
                    }
            )
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(L10n.string("podcast.controls.seek"))
            .accessibilityValue("\(formatTime(activeTime)) / \(formatTime(viewModel.duration))")
        }
        .frame(height: PodcastPlayerMetrics.seekBarHitArea)
        .animation(AppMotion.swipeTrackingSpring, value: isDragging)
    }

    private func progressWidth(in totalWidth: CGFloat) -> CGFloat {
        PodcastSeekBarGeometry.progressWidth(
            time: activeTime,
            duration: viewModel.duration,
            totalWidth: totalWidth
        )
    }

    private func bufferedWidth(in totalWidth: CGFloat) -> CGFloat {
        PodcastSeekBarGeometry.bufferedWidth(
            bufferedEnd: viewModel.bufferedEnd,
            duration: viewModel.duration,
            totalWidth: totalWidth
        )
    }

    private func formatTime(_ t: TimeInterval) -> String {
        guard t.isFinite, !t.isNaN else { return "--:--" }
        let m = Int(t) / 60, s = Int(t) % 60
        return String(format: "%02d:%02d", m, s)
    }
}
