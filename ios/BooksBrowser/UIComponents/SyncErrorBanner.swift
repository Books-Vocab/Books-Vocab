//
//  SyncErrorBanner.swift
//  BooksBrowser
//
//  背景同步失敗提示條 — 可關閉，風格複用 ErrorBannerView 模式
//

import SwiftUI

struct SyncErrorBanner: View {
    @Environment(\.appTheme) private var appTheme
    let message: String
    let onDismiss: () -> Void

    var body: some View {
        HStack(spacing: AppBannerMetrics.spacing) {
            Image(systemName: "arrow.triangle.2.circlepath.circle")
                .font(AppFonts.caption(weight: .semibold))
                .foregroundStyle(appTheme.palette.warning)

            Text(message.localized)
                .font(AppFonts.caption())
                .foregroundStyle(appTheme.palette.secondaryText)
                .lineLimit(2)

            Spacer()

            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .font(AppFonts.caption2())
                    .foregroundStyle(appTheme.palette.tertiaryText)
            }
        }
        .padding(.horizontal, AppBannerMetrics.horizontalPadding)
        .padding(.vertical, AppBannerMetrics.verticalPadding)
        .background(appTheme.palette.warning.opacity(AppBannerMetrics.backgroundOpacity))
        .transition(.bannerReveal)
    }
}
