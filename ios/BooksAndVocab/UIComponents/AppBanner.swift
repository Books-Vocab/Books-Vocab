//
//  AppBanner.swift
//  Books & Vocab
//
//  統一提示條：取代 ErrorBannerView、SyncErrorBanner、OfflineBanner
//  支援可選 retry / dismiss 按鈕，icon 可自訂
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

    private var toneColor: Color {
        switch tone {
        case .warning: return appTheme.palette.warning
        case .success: return appTheme.palette.success
        }
    }

    var body: some View {
        HStack(spacing: AppBannerMetrics.spacing) {
            Image(systemName: systemImage)
                .font(AppFonts.caption(weight: .semibold))
                .foregroundStyle(toneColor)

            Text(message.localized)
                .font(AppFonts.caption())
                .foregroundStyle(appTheme.palette.secondaryText)
                .lineLimit(2)

            Spacer()

            if let retry = onRetry {
                Button(action: retry) {
                    Image(systemName: "arrow.clockwise")
                        .font(AppFonts.caption())
                        .foregroundStyle(appTheme.palette.accent)
                }
                .accessibilityLabel(L10n.string("banner.action.retry"))
            }

            if let dismiss = onDismiss {
                Button(action: dismiss) {
                    Image(systemName: "xmark")
                        .font(AppFonts.caption2())
                        .foregroundStyle(appTheme.palette.tertiaryText)
                }
                .accessibilityLabel(L10n.string("banner.action.dismiss"))
            }
        }
        .padding(.horizontal, AppBannerMetrics.horizontalPadding)
        .padding(.vertical, AppBannerMetrics.verticalPadding)
        .background(toneColor.opacity(AppBannerMetrics.backgroundOpacity))
        .overlay(
            Rectangle()
                .frame(height: AppMetrics.dividerStandard)
                .foregroundStyle(toneColor.opacity(AppBannerMetrics.borderOpacity)),
            alignment: .bottom
        )
        .transition(.bannerReveal)
    }
}

#Preview("AppBanner") {
    AppThemeContainer {
        VStack(spacing: AppSpacing.s4) {
            AppBanner(message: "目前無網路連線，部分功能暫不可用。")
            AppBanner(
                message: "同步失敗，請稍後再試。",
                systemImage: "exclamationmark.icloud",
                onRetry: {},
                onDismiss: {}
            )
            Spacer()
        }
        .padding(.top, AppSpacing.s4)
    }
    .environmentObject(AppAppearanceStore.preview)
}
