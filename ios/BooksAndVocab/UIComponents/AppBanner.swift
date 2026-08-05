//
//  AppBanner.swift
//  Books & Vocab
//
//  統一提示條：取代 ErrorBannerView、SyncErrorBanner、OfflineBanner
//  支援可選 retry / dismiss 按鈕，icon 可自訂
//
//  視覺契約（2026-08 重新設計）：
//  banner 出現在**內容流裡** —— 單字本清單頂端、sheet 表單上方，左右鄰居都是圓角
//  卡片。舊版把它畫成整條方角色塊 + 底部一條 hairline：那是 chrome 的語彙，違反
//  Mochi 北極星 1（單色頁面、無 chrome 分隔）與 2（border 退場、divider 進場），
//  夾在圓角卡片之間像另一個 app 掉進來的元件。現在它跟鄰居講同一種話：
//    - 連續圓角，半徑取 App Shell 的 `AppShellMetrics.cardCornerRadius`
//    - 背景走語意 token `successBg` / `warningBg`（本身已是疊在 pageBackground 上的
//      低濃度 tint），不再自行乘 opacity 生一個 off-token 的顏色
//    - 文字用 `primaryText` —— 沿用 `AppOfflineBanner` 已驗證的對比結論（tint 底 +
//      灰階前景 ≈ AAA）；tone 色只留給 icon 表達語氣，不拿去染文字
//    - `.appElevation(.z0)`：靠背景分層、不加陰影（北極星 3）
//    - action 是 44pt tap target，不再是 caption 大小的裸 glyph
//
//  本元件屬 App Shell 層，因此只吃 `AppTheme` / `AppFonts` / `AppMetrics`，
//  不碰 Vocabulary 層的 `appSkin`（見 docs/sop/ui-design.md 分層表）。
//

import SwiftUI

struct AppBanner: View {
    enum Tone {
        case warning
        case success
    }

    @Environment(\.appTheme) private var appTheme
    let message: String
    var systemImage: String = "wifi.exclamationmark"
    var tone: Tone = .warning
    var onRetry: (() -> Void)? = nil
    var onDismiss: (() -> Void)? = nil

    /// 語氣色 —— 只用於 icon。文字一律 `primaryText`，見檔頭視覺契約。
    private var toneColor: Color {
        switch tone {
        case .warning: return appTheme.palette.warning
        case .success: return appTheme.palette.success
        }
    }

    /// 語意背景 token（已是低濃度 tint over pageBackground）。
    private var toneBackground: Color {
        switch tone {
        case .warning: return appTheme.palette.warningBg
        case .success: return appTheme.palette.successBg
        }
    }

    var body: some View {
        HStack(spacing: AppBannerMetrics.spacing) {
            Image(systemName: systemImage)
                .font(AppFonts.caption(weight: .semibold))
                .foregroundStyle(toneColor)
                .accessibilityHidden(true)

            Text(message.localized)
                .font(AppFonts.caption(weight: .medium))
                .foregroundStyle(appTheme.palette.primaryText)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)

            Spacer(minLength: AppBannerMetrics.spacing)

            if let retry = onRetry {
                action(
                    systemImage: "arrow.clockwise",
                    tint: appTheme.palette.accent,
                    label: L10n.string("banner.action.retry"),
                    handler: retry
                )
            }

            if let dismiss = onDismiss {
                action(
                    systemImage: "xmark",
                    tint: appTheme.palette.tertiaryText,
                    label: L10n.string("banner.action.dismiss"),
                    handler: dismiss
                )
            }
        }
        .padding(.leading, AppBannerMetrics.horizontalPadding)
        .padding(.trailing, AppBannerMetrics.trailingPadding(
            hasActions: onRetry != nil || onDismiss != nil
        ))
        .padding(.vertical, AppBannerMetrics.verticalPadding)
        .frame(minHeight: AppBannerMetrics.minHeight)
        .background(toneBackground)
        .clipShape(
            RoundedRectangle(
                cornerRadius: AppShellMetrics.cardCornerRadius,
                style: .continuous
            )
        )
        .appElevation(.z0)
        .transition(.bannerReveal)
    }

    /// Action glyph with a real hit target. The glyph stays caption-sized so the
    /// banner keeps its quiet weight, but the tappable area is a full control —
    /// the previous bare `Image` button was roughly a 12pt target.
    @ViewBuilder
    private func action(
        systemImage: String,
        tint: Color,
        label: String,
        handler: @escaping () -> Void
    ) -> some View {
        Button(action: handler) {
            Image(systemName: systemImage)
                .font(AppFonts.caption(weight: .semibold))
                .foregroundStyle(tint)
                .frame(
                    width: AppBannerMetrics.actionHitTarget,
                    height: AppBannerMetrics.actionHitTarget
                )
                .contentShape(Rectangle())
        }
        .buttonStyle(.pressable)
        .accessibilityLabel(label)
    }
}

#Preview("AppBanner") {
    AppThemeContainer {
        VStack(spacing: AppSpacing.s3) {
            AppBanner(
                message: "單字庫已更新",
                systemImage: "checkmark.circle.fill",
                tone: .success,
                onDismiss: {}
            )
            AppBanner(message: "目前無網路連線，部分功能暫不可用。")
            AppBanner(
                message: "同步失敗，請稍後再試。",
                systemImage: "exclamationmark.icloud",
                onRetry: {},
                onDismiss: {}
            )
            Spacer()
        }
        .padding(AppSpacing.s4)
    }
    .environmentObject(AppAppearanceStore.preview)
}
