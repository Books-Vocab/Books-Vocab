#if os(iOS)
//
//  BookCard.swift
//  BooksBrowser
//

import SwiftUI
import Inject

// MARK: - 書籍卡片

struct BookCard: View {
    @ObserveInjection private var inject
    @Environment(\.appTheme) private var appTheme
    @Environment(\.iCloudDownloadManager) private var downloadManager
    let book: Book
    var coverHeight: CGFloat = AppBookshelfMetrics.coverHeightCompact
    @State private var decodedCoverImage: PlatformImage?

    var body: some View {
        VStack(alignment: .leading, spacing: AppSpacing.s2) {
            // 封面 — Mochi 北極星二/三：border 退場、resting 走 z0
            coverView
                .overlay(alignment: .bottomTrailing) {
                    iCloudDownloadBadge
                }
                .appElevation(.z0)

            // 進度條（封面外獨立元素，0% 時保留占位以維持卡片高度一致）
            progressBar(book.progression ?? 0)

            // 元資料
            VStack(alignment: .leading, spacing: AppSpacing.tinyGap) {
                Text(book.title)
                    .font(AppFonts.caption(weight: .medium))
                    .lineLimit(2)
                    .truncationMode(.tail)
                    .minimumScaleFactor(0.85)
                    .multilineTextAlignment(.leading)
                    .foregroundStyle(appTheme.palette.primaryText)

                Text(book.author)
                    .font(AppFonts.caption2())
                    .foregroundStyle(appTheme.palette.tertiaryText)
                    .lineLimit(1)
                    .truncationMode(.tail)

                if let dateLastRead = book.dateLastRead {
                    Text(dateLastRead.relativeShort)
                        .font(AppFonts.caption2())
                        .foregroundStyle(appTheme.palette.quaternaryText)
                }
            }
        }
        .task(id: book.coverImageData) {
            await decodeCoverImage()
        }
        .enableInjection()
    }

    @ViewBuilder
    private var coverView: some View {
        if let coverImage = decodedCoverImage {
            platformCoverImage(coverImage)
                .resizable()
                .aspectRatio(2/3, contentMode: .fill)
                .frame(height: coverHeight)
                .clipShape(
                    RoundedRectangle(
                        cornerRadius: AppBookshelfMetrics.coverCornerRadius,
                        style: .continuous
                    )
                )
                .transition(.contentSwap)
        } else {
            RoundedRectangle(
                cornerRadius: AppBookshelfMetrics.coverCornerRadius,
                style: .continuous
            )
            .fill(appTheme.palette.mutedFill)
            .frame(height: coverHeight)
            .overlay {
                VStack(spacing: AppSpacing.s2) {
                    Image(systemName: "book")
                        .font(AppFonts.h1(weight: .regular))
                        .foregroundStyle(appTheme.palette.tertiaryText)
                    Text(book.title)
                        .font(AppFonts.caption2())
                        .foregroundStyle(appTheme.palette.secondaryText)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, AppBookshelfMetrics.placeholderTitleHorizontalPadding)
                    if book.format != .epub {
                        Text(book.format.rawValue.uppercased())
                            .font(AppFonts.caption2())
                            .foregroundStyle(appTheme.palette.secondaryText)
                            .padding(.horizontal, AppSpacing.s1)
                            .padding(.vertical, AppSpacing.microGap)
                            .background(appTheme.palette.mutedFill)
                            .clipShape(RoundedRectangle(cornerRadius: AppRadius.sm))
                    }
                }
            }
        }
    }

    private func platformCoverImage(_ image: PlatformImage) -> Image {
        Image(uiImage: image)
    }

    private func decodeCoverImage() async {
        guard let coverData = book.coverImageData else {
            decodedCoverImage = nil
            return
        }
        let image = await Task.detached {
            PlatformImage(data: coverData)
        }.value
        guard !Task.isCancelled else { return }
        withAnimation(AppMotion.contentFade) {
            decodedCoverImage = image
        }
    }

    @ViewBuilder
    private var iCloudDownloadBadge: some View {
        if let state = downloadManager.state(for: book.epubFileName) {
            switch state {
            case .downloading(let progress):
                ICloudProgressBadge(progress: progress)
                    .padding(AppBookshelfMetrics.badgePadding)
            case .notDownloaded:
                cloudIconBadge
            case .current:
                EmptyView()
            }
        } else if book.needsICloudDownload {
            cloudIconBadge
        }
    }

    private var cloudIconBadge: some View {
        Image(systemName: "icloud.and.arrow.down")
            .font(AppFonts.caption2(weight: .semibold))
            .foregroundStyle(AppBookshelfMetrics.badgeForeground)
            .padding(AppBookshelfMetrics.badgePadding)
            .background(.ultraThinMaterial, in: Circle())
            .padding(AppBookshelfMetrics.badgePadding)
    }

    private func progressBar(_ progress: Double) -> some View {
        let clamped = min(max(progress, 0), 1)
        return HStack(spacing: AppBookshelfMetrics.progressBarSpacing) {
            GeometryReader { geo in
                Capsule()
                    .fill(appTheme.palette.mutedFill)
                    .overlay(alignment: .leading) {
                        Capsule()
                            .fill(appTheme.palette.accent)
                            .frame(width: geo.size.width * clamped)
                    }
            }
            .frame(height: AppBookshelfMetrics.progressBarHeight)
            .clipShape(Capsule())

            Text("\(Int(clamped * 100))%")
                .font(AppFonts.monoNumbers(size: 10))
                .foregroundStyle(appTheme.palette.tertiaryText)
                .opacity(clamped > 0 ? 1 : 0)
        }
        .accessibilityHidden(clamped <= 0)
    }
}

// MARK: - iCloud 下載進度徽章

private struct ICloudProgressBadge: View {
    let progress: Double
    private let foreground = AppBookshelfMetrics.badgeForeground

    var body: some View {
        ZStack {
            Circle()
                .stroke(foreground.opacity(0.3), lineWidth: 2.5)
            Circle()
                .trim(from: 0, to: progress)
                .stroke(foreground, style: StrokeStyle(lineWidth: 2.5, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .animation(AppMotion.progressLinear, value: progress)
            Text("\(Int(progress * 100))")
                .font(AppFonts.monoNumbers(size: 8))
                .foregroundStyle(foreground)
        }
        .frame(width: 32, height: 32)
        .background(.ultraThinMaterial, in: Circle())
    }
}

private extension Date {
    var relativeShort: String {
        LocaleAwareFormatter.shared.relativeString(for: self, relativeTo: Date(), style: .short)
    }
}
#endif
