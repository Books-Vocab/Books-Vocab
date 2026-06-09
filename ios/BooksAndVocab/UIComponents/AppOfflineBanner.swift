//
//  AppOfflineBanner.swift
//  Books & Vocab
//
//  全 app 持久離線指示 banner — 訂閱 NetworkMonitor.shared.isConnected，
//  斷線時於畫面頂部顯示薄 banner，恢復連線時自動消失。
//
//  使用方式：在 root tab shell 或主 ContentView 套用 `.appOfflineBanner()`：
//      ContentView()
//          .appOfflineBanner()
//
//  視覺設計：
//    - 細高度（24pt）避免侵佔主內容
//    - destructive bg 提供錯誤色調；前景用 primaryText（灰階高對比），
//      非 destructive 紅字。primaryText 疊在 destructiveBg（destructive
//      10~14% tint 疊於 pageBackground）上實測 light ~9.85:1 / dark ~11.6:1，
//      ✓ WCAG AAA。若改用 destructive 紅字當前景則 light 僅 ~4.49:1（勉強 AA）
//      且語意混淆，故維持 primaryText。
//    - 進場走 `AnyTransition.bannerReveal`、進出走 `AppMotion.emphasizedDecelerate`
//

import SwiftUI

struct AppOfflineBanner: View {
    @Environment(\.appTheme) private var appTheme

    var body: some View {
        HStack(spacing: AppSpacing.s2) {
            Image(systemName: "wifi.slash")
                .font(AppFonts.caption(weight: .semibold))
            Text("目前無網路連線".localized)
                .font(AppFonts.caption(weight: .semibold))
        }
        .foregroundStyle(appTheme.palette.primaryText)
        .padding(.horizontal, AppSpacing.s4)
        .padding(.vertical, AppSpacing.s2)
        .frame(maxWidth: .infinity)
        .background(appTheme.palette.destructiveBg)
    }
}

private struct AppOfflineBannerModifier: ViewModifier {
    @State private var monitor = NetworkMonitor.shared

    func body(content: Content) -> some View {
        content
            .safeAreaInset(edge: .top, spacing: 0) {
                if !monitor.isConnected {
                    AppOfflineBanner()
                        .transition(.bannerReveal)
                }
            }
            .animation(AppMotion.emphasizedDecelerate, value: monitor.isConnected)
    }
}

extension View {
    /// 套在 root 層（ContentView / 主 tab shell），自動感知 NetworkMonitor 狀態。
    func appOfflineBanner() -> some View {
        modifier(AppOfflineBannerModifier())
    }
}

#Preview("Offline Banner") {
    AppThemeContainer {
        VStack {
            AppOfflineBanner()
            Spacer()
        }
    }
    .environmentObject(AppAppearanceStore.preview)
}
