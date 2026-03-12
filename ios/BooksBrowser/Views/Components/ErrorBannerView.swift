//
//  ErrorBannerView.swift
//  BooksBrowser
//
//  統一錯誤提示條：從頂部滑入，非阻斷式
//

import SwiftUI

struct ErrorBannerView: View {
    @Environment(\.appTheme) private var appTheme
    let message: String
    var onDismiss: (() -> Void)? = nil
    var onRetry: (() -> Void)? = nil

    var body: some View {
        HStack(spacing: AppBannerMetrics.spacing) {
            Image(systemName: "exclamationmark.triangle.fill")
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
