import SwiftUI
import SwiftData
import Inject

struct PodcastEpisodeRow: View {
    @ObserveInjection private var inject
    let episode: PodcastEpisode
    let progress: PodcastProgress?
    @Environment(\.appSkin) private var skin
    @Environment(\.kgService) private var kgService
    #if os(iOS)
    @State private var downloadManager = PodcastDownloadManager.shared
    #endif

    init(episode: PodcastEpisode, progress: PodcastProgress? = nil) {
        self.episode = episode
        self.progress = progress
    }

    private var isCompleted: Bool { progress?.completed == true }
    #if os(iOS)
    private var downloadProgress: Double? { downloadManager.progress[episode.remoteId] }
    private var isDownloaded: Bool {
        guard let path = episode.localAudioPath else { return false }
        return FileManager.default.fileExists(atPath: path)
    }
    #endif
    private var hasProgress: Bool {
        guard let p = progress else { return false }
        return !p.completed && p.lastPlayedTime > 0 && episode.durationSec > 0
    }
    private var progressFraction: Double {
        guard hasProgress, let p = progress else { return 0 }
        return min(1, p.lastPlayedTime / episode.durationSec)
    }

    var body: some View {
        // 對齊單字 WordRow 的列節奏：水平 wordRowHorizontalGap、垂直 wordRowVerticalGap、
        // metadata monoLabel、compactRowVerticalPadding（皆與 WordRow 一致）。標題刻意保留
        // serif sectionTitle —— WordRow 的 rowWord 是 systemMono（適合單字 token），但 episode
        // 標題為散文，套 mono 反而視覺退步，故只對齊版面節奏不對齊標題字體。
        HStack(alignment: .top, spacing: skin.spacing.wordRowHorizontalGap) {
            VStack(alignment: .leading, spacing: skin.spacing.wordRowVerticalGap) {
                Text(episode.title)
                    .font(skin.typography.sectionTitle)
                    .foregroundStyle(episode.audioAvailable ? skin.palette.primaryText : skin.palette.tertiaryText)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)

                metadataLine

                if hasProgress {
                    ProgressCapsule(
                        progress: progressFraction,
                        label: nil,
                        fillColor: skin.palette.accent,
                        trackColor: skin.palette.progressBarBackground,
                        height: 3
                    )
                    .padding(.top, skin.spacing.tinyGap)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            trailingAccessory
                .padding(.top, skin.spacing.compactRowAccessoryTopInset)
        }
        .padding(.vertical, skin.spacing.compactRowVerticalPadding)
        .padding(.horizontal, skin.spacing.cardPadding)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        #if os(iOS)
        .contextMenu { downloadMenuItems }
        #endif
        .enableInjection()
    }

    #if os(iOS)
    @ViewBuilder
    private var downloadMenuItems: some View {
        if !episode.audioAvailable {
            EmptyView()
        } else if downloadProgress != nil {
            Button(role: .destructive) {
                downloadManager.cancel(remoteId: episode.remoteId)
            } label: {
                Label(L10n.string("取消下載"), systemImage: "xmark.circle")
            }
        } else if isDownloaded {
            Button(role: .destructive) {
                downloadManager.deleteLocal(episode: episode)
            } label: {
                Label(L10n.string("移除下載"), systemImage: "trash")
            }
        } else {
            Button {
                Task {
                    guard let token = try? await kgService.currentAuthToken() else { return }
                    downloadManager.startDownload(episode: episode, authToken: token)
                }
            } label: {
                Label(L10n.string("下載供離線播放"), systemImage: "arrow.down.circle")
            }
        }
    }
    #endif

    private var metadataLine: some View {
        HStack(spacing: skin.spacing.metadataGap) {
            Text("Ep \(episode.episodeNumber)")
                .font(skin.typography.monoLabel)
                .foregroundStyle(skin.palette.secondaryText)

            Text("·")
                .font(skin.typography.monoLabel)
                .foregroundStyle(skin.palette.quaternaryText)

            Text(formatDate(episode.createdAt))
                .font(skin.typography.monoLabel)
                .foregroundStyle(skin.palette.tertiaryText)

            Text("·")
                .font(skin.typography.monoLabel)
                .foregroundStyle(skin.palette.quaternaryText)

            Text(formatDuration(episode.durationSec))
                .font(skin.typography.monoLabel)
                .foregroundStyle(skin.palette.tertiaryText)

            if episode.subtitleAvailable {
                Image(systemName: "captions.bubble.fill")
                    .font(skin.typography.iconTiny)
                    .foregroundStyle(skin.palette.success)
                    .accessibilityLabel(L10n.string("podcast.episodeRow.subtitleAvailable"))
            }

            #if os(iOS)
            downloadIndicator
            #endif
        }
    }

    #if os(iOS)
    @ViewBuilder
    private var downloadIndicator: some View {
        if let frac = downloadProgress {
            // Active download — compact progress ring.
            ZStack {
                Circle()
                    .stroke(skin.palette.progressBarBackground, lineWidth: 1.5)
                Circle()
                    .trim(from: 0, to: frac)
                    .stroke(skin.palette.accent, style: StrokeStyle(lineWidth: 1.5, lineCap: .round))
                    .rotationEffect(.degrees(-90))
            }
            .frame(width: 11, height: 11)
            .animation(.easeOut(duration: 0.2), value: frac)
            .accessibilityLabel(L10n.string("podcast.episodeRow.downloading"))
            .accessibilityValue("\(Int((frac * 100).rounded()))%")
        } else if isDownloaded {
            Image(systemName: "arrow.down.circle.fill")
                .font(skin.typography.iconTiny)
                .foregroundStyle(skin.palette.success)
                .accessibilityLabel(L10n.string("podcast.episodeRow.downloaded"))
        }
    }
    #endif

    @ViewBuilder
    private var trailingAccessory: some View {
        if isCompleted {
            Image(systemName: "checkmark.circle.fill")
                .font(skin.typography.iconSmall)
                .foregroundStyle(skin.palette.success)
                .accessibilityLabel(L10n.string("podcast.episodeRow.listened"))
        } else if !episode.audioAvailable {
            Image(systemName: "icloud.slash")
                .font(skin.typography.iconSmall)
                .foregroundStyle(skin.palette.quaternaryText)
                .accessibilityLabel(L10n.string("podcast.episodeRow.unavailable"))
        } else {
            Image(systemName: "play.circle.fill")
                .font(skin.typography.iconSmall)
                .foregroundStyle(skin.palette.accent)
                .accessibilityHidden(true)
        }
    }

    private func formatDuration(_ sec: Double) -> String {
        guard sec.isFinite, sec >= 0 else { return "--:--" }
        let total = Int(sec)
        return String(format: "%d:%02d", total / 60, total % 60)
    }

    private func formatDate(_ date: Date) -> String {
        let cal = Calendar.current
        if cal.isDateInToday(date) { return L10n.string("今天") }
        if cal.isDateInYesterday(date) { return L10n.string("昨天") }
        let sameYear = cal.isDate(date, equalTo: Date(), toGranularity: .year)
        // template → ICU 給各 locale 最佳化:
        // sameYear: en="May 22" / ja="5月22日" / zh-Hant="5月22日" / ko="5월 22일"
        // crossYear: en="May 22, 2025" / ja="2025年5月22日" / zh-Hant="2025/5/22"
        let template = sameYear ? "Md" : "yMd"
        return LocaleAwareFormatter.shared.string(from: date, template: template)
    }
}
