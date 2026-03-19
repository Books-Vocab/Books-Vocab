//
//  AppBanner.swift
//  BooksBrowser
//
//  統一提示條：取代 ErrorBannerView、SyncErrorBanner、OfflineBanner
//  支援可選 retry / dismiss 按鈕，icon 可自訂
//

import SwiftUI

struct AppBanner: View {
    @Environment(\.appTheme) private var appTheme
    let message: String
    var systemImage: String = "wifi.exclamationmark"
    var onRetry: (() -> Void)? = nil
    var onDismiss: (() -> Void)? = nil

    var body: some View {
        HStack(spacing: AppBannerMetrics.spacing) {
            Image(systemName: systemImage)
                .font(AppFonts.caption(weight: .semibold))
                .foregroundStyle(appTheme.palette.warning)

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
            }

            if let dismiss = onDismiss {
                Button(action: dismiss) {
                    Image(systemName: "xmark")
                        .font(AppFonts.caption2())
                        .foregroundStyle(appTheme.palette.tertiaryText)
                }
            }
        }
        .padding(.horizontal, AppBannerMetrics.horizontalPadding)
        .padding(.vertical, AppBannerMetrics.verticalPadding)
        .background(appTheme.palette.warning.opacity(AppBannerMetrics.backgroundOpacity))
        .overlay(
            Rectangle()
                .frame(height: AppMetrics.dividerStandard)
                .foregroundStyle(appTheme.palette.warning.opacity(AppBannerMetrics.borderOpacity)),
            alignment: .bottom
        )
        .transition(.bannerReveal)
    }
}
