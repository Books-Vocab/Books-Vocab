//
//  OfflineBanner.swift
//  BooksBrowser
//
//  離線狀態提示條 — 顯示在 Tab 上方，風格與 DemoBanner 一致
//

import SwiftUI

struct OfflineBanner: View {
    @Environment(\.appTheme) private var appTheme

    var body: some View {
        HStack(spacing: AppMetrics.spacingSmall) {
            Image(systemName: "wifi.slash")
                .font(AppFonts.caption(weight: .medium))
            Text("目前沒有網路連線".localized)
                .font(AppFonts.caption(weight: .medium))
            Spacer()
        }
        .foregroundStyle(appTheme.palette.warning)
        .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
        .padding(.vertical, AppMetrics.spacingSmall)
        .background(appTheme.palette.warning.opacity(AppBannerMetrics.backgroundOpacity))
        .transition(.bannerReveal)
    }
}
