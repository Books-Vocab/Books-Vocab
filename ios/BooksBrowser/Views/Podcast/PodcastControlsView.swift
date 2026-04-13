//
//  PodcastControlsView.swift
//  BooksBrowser
//
//  Podcast 播放控制：seek bar、播放/暫停、快進快退、字幕模式、播放速率
//

import SwiftUI

struct PodcastControlsView: View {
    let viewModel: PodcastPlayerViewModel
    @Environment(\.vocabSkin) private var skin

    @State private var isDragging = false
    @State private var dragTime: TimeInterval = 0

    var body: some View {
        VStack(spacing: skin.spacing.sectionGap) {
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
            HStack(spacing: skin.spacing.controlGap) {
                Button { viewModel.skip(seconds: -15) } label: {
                    Image(systemName: "gobackward.15")
                        .font(skin.typography.symbolLarge)
                }
                Button { viewModel.togglePlayPause() } label: {
                    Image(systemName: viewModel.state == .playing ? "pause.circle.fill" : "play.circle.fill")
                        .font(skin.typography.symbolPlayback)
                }
                Button { viewModel.skip(seconds: 15) } label: {
                    Image(systemName: "goforward.15")
                        .font(skin.typography.symbolLarge)
                }
            }
            .foregroundStyle(skin.palette.accent)

            HStack {
                Spacer()
                Button { viewModel.cycleRate() } label: {
                    Text(viewModel.rateDisplayText)
                        .font(skin.typography.monoLabel)
                        .padding(.horizontal, skin.spacing.chipHorizontalPadding)
                        .padding(.vertical, skin.spacing.chipVerticalPadding)
                        .background(skin.palette.mutedFill, in: Capsule())
                }
                .foregroundStyle(skin.palette.primaryText)
            }
        }
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
                Capsule()
                    .fill(skin.palette.accent)
                    .frame(width: progressWidth(in: w), height: PodcastPlayerMetrics.seekBarTrackHeight)
                Circle()
                    .fill(skin.palette.cardBackground)
                    .frame(
                        width: PodcastPlayerMetrics.seekBarThumbSize,
                        height: PodcastPlayerMetrics.seekBarThumbSize
                    )
                    .shadow(
                        color: skin.palette.shadow.opacity(PodcastPlayerMetrics.seekBarThumbShadowOpacity),
                        radius: PodcastPlayerMetrics.seekBarThumbShadowRadius,
                        y: PodcastPlayerMetrics.seekBarThumbShadowY
                    )
                    .offset(x: max(0, progressWidth(in: w) - PodcastPlayerMetrics.seekBarThumbOffset))
                    .gesture(
                        DragGesture(minimumDistance: 0)
                            .onChanged { v in
                                // Block scrubbing until AVPlayer reports duration;
                                // dragging earlier silently resolves to seek(0).
                                guard viewModel.duration > 0 else { return }
                                isDragging = true
                                dragTime = max(0, min(viewModel.duration, Double(v.location.x / w) * viewModel.duration))
                            }
                            .onEnded { _ in
                                guard viewModel.duration > 0, isDragging else { return }
                                isDragging = false
                                viewModel.seek(to: dragTime)
                            }
                    )
            }
        }
        .frame(height: PodcastPlayerMetrics.seekBarHitArea)
        .animation(AppMotion.swipeTrackingSpring, value: isDragging)
    }

    private func progressWidth(in totalWidth: CGFloat) -> CGFloat {
        guard viewModel.duration > 0 else { return 0 }
        return CGFloat(activeTime / viewModel.duration) * totalWidth
    }

    private func formatTime(_ t: TimeInterval) -> String {
        guard t.isFinite, !t.isNaN else { return "--:--" }
        let m = Int(t) / 60, s = Int(t) % 60
        return String(format: "%02d:%02d", m, s)
    }
}
