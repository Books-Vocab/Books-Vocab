//
//  AppSkeleton.swift
//  Books & Vocab
//
//  Loading state skeleton primitives — 取代裸 `ProgressView()`，
//  讓 list / card / row 在資料載入時有結構化骨架而非空白旋轉。
//
//  變體：
//    - AppLoadingStateCard / AppLoadingProgressBar — 共用 loading/status surface
//    - AppSkeletonLine — 單行 line / label 骨架
//    - AppSkeletonCard — 卡片區塊骨架（標題+多行內文）
//
//  動畫採 opacity pulse（pulsing 0.08 ↔ 0.18），低耗能、無漸層遮罩，
//  避免在 long-lived view 持續消耗 GPU。caller 應於 .onAppear 觸發、
//  view disappear 時 SwiftUI 自動停止。
//

import SwiftUI

enum AppLoadingIndicator: Equatable {
    case spinner
    case progress(Double)

    var normalizedProgress: Double? {
        guard case .progress(let value) = self, value.isFinite else {
            return self == .spinner ? nil : 0
        }
        return min(max(value, 0), 1)
    }
}

/// Shared iOS 26 loading/status surface. Use the same card for reader overlays,
/// catalog states and vocabulary scene states; only the skin
/// and indicator differ. This keeps loading from becoming a collection of
/// one-off cards with subtly different padding and motion.
struct AppLoadingStateCard: View {
    enum VisualStyle {
        case app
        case vocab
    }

    @Environment(\.appTheme) private var appTheme
    @Environment(\.appSkin) private var appSkin

    let title: String
    let systemImage: String
    let description: String?
    let indicator: AppLoadingIndicator
    let visualStyle: VisualStyle

    init(
        title: String,
        systemImage: String,
        description: String? = nil,
        indicator: AppLoadingIndicator = .spinner,
        visualStyle: VisualStyle = .app
    ) {
        self.title = title
        self.systemImage = systemImage
        self.description = description
        self.indicator = indicator
        self.visualStyle = visualStyle
    }

    var body: some View {
        AppStateMessageCard(
            title: title,
            systemImage: systemImage,
            description: description,
            style: messageStyle
        ) {
            switch indicator {
            case .spinner:
                ProgressView()
                    .controlSize(.small)
            case .progress(let value):
                AppLoadingProgressBar(
                    progress: value,
                    tint: messageAccent
                )
                .frame(width: 120)
            }
        }
    }

    private var messageStyle: AppStateMessageStyle {
        switch visualStyle {
        case .app: return .themed(appTheme)
        case .vocab: return .vocab(appSkin)
        }
    }

    private var messageAccent: Color {
        switch visualStyle {
        case .app: return appTheme.palette.accent
        case .vocab: return appSkin.palette.accent
        }
    }
}

/// Native linear progress treatment shared by loading cards and transient
/// reader/sync progress overlays. `ProgressView` owns the iOS 26 surface;
/// callers only provide semantic tint and value.
struct AppLoadingProgressBar: View {
    let progress: Double
    let tint: Color
    let accessibilityLabel: String?

    init(progress: Double, tint: Color, accessibilityLabel: String? = nil) {
        self.progress = progress
        self.tint = tint
        self.accessibilityLabel = accessibilityLabel
    }

    var body: some View {
        ProgressView(value: normalizedProgress)
            .progressViewStyle(.linear)
            .tint(tint)
            .accessibilityElement()
            .accessibilityLabel(Text(accessibilityLabel ?? L10n.string("app.loading.progress")))
            .accessibilityValue(Text(verbatim: "\(Int(normalizedProgress * 100))%"))
            .animation(AppMotion.progressLinear, value: normalizedProgress)
    }

    private var normalizedProgress: Double {
        AppLoadingIndicator.progress(progress).normalizedProgress ?? 0
    }
}

struct AppSkeletonLine: View {
    @Environment(\.appTheme) private var appTheme
    @State private var pulse = false

    var width: CGFloat?
    var height: CGFloat = 12

    init(width: CGFloat? = nil, height: CGFloat = 12) {
        self.width = width
        self.height = height
    }

    var body: some View {
        // 用 primaryText.opacity 直接給顯式 alpha：
        // - light mode primaryText 偏黑，0.06-0.14 在白底清楚可見
        // - dark mode primaryText 偏白，0.06-0.14 在暗底清楚可見
        // 在兩 mode 自動 invert 對比，pulse 振幅一致。
        AppRoundedRect(roundness: AppRoundness.pill)
            .fill(appTheme.palette.primaryText.opacity(pulse ? 0.14 : 0.06))
            .frame(width: width, height: height)
            .frame(maxWidth: width == nil ? .infinity : nil, alignment: .leading)
            .animation(AppMotion.subtleBreath, value: pulse)
            .onAppear { pulse = true }
    }
}

struct AppSkeletonCard: View {
    @Environment(\.appTheme) private var appTheme

    var titleWidth: CGFloat? = 180
    var lineCount: Int = 3
    var showAvatar: Bool = false

    var body: some View {
        HStack(alignment: .top, spacing: AppSpacing.s3) {
            if showAvatar {
                AppRoundedRect(roundness: AppRoundness.icon)
                    .fill(appTheme.palette.mutedFill)
                    .frame(width: 44, height: 44)
            }

            VStack(alignment: .leading, spacing: AppSpacing.s2) {
                AppSkeletonLine(width: titleWidth, height: 14)
                ForEach(0..<lineCount, id: \.self) { _ in
                    AppSkeletonLine(height: 10)
                }
            }
        }
        .padding(AppSpacing.cardOuterPadding)
        .background(AppRoundedRect(roundness: AppRoundness.card).fill(appTheme.palette.cardBackground))
        .clipShape(AppRoundedRect(roundness: AppRoundness.card))
        .appElevation(.z0)
    }
}

#Preview("AppSkeleton") {
    AppThemeContainer {
        VStack(spacing: AppSpacing.s4) {
            AppSkeletonLine(width: 200)
            AppSkeletonLine()
            AppSkeletonCard()
            AppSkeletonCard(showAvatar: true)
        }
        .padding(AppSpacing.s5)
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("AppLoadingState") {
    AppThemeContainer {
        VStack(spacing: AppSpacing.s4) {
            AppLoadingStateCard(
                title: L10n.string("載入中"),
                systemImage: "arrow.triangle.2.circlepath",
                description: L10n.string("正在整理資料。"),
                visualStyle: .app
            )
            AppLoadingStateCard(
                title: L10n.string("同步中…"),
                systemImage: "arrow.triangle.2.circlepath",
                indicator: .progress(0.58),
                visualStyle: .vocab
            )
        }
        .padding(AppSpacing.s5)
    }
    .environmentObject(AppAppearanceStore.preview)
}
