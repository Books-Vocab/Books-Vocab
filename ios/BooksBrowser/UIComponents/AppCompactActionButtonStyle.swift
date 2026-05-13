//
//  AppCompactActionButtonStyle.swift
//  BooksBrowser
//
//  Inline 小尺寸主行動按鈕（不撐滿寬度，配 capsule 形狀），
//  取代散落各處的 `.buttonStyle(.borderedProminent).controlSize(.small)`，
//  讓 design system 對「小型主 CTA」也有單一入口。
//
//  與 `AppActionButtonStyle(.primary)` 的差別：
//    - AppAction        → 全寬主按鈕（Login / 主畫面 CTA）
//    - AppCompactAction → inline 小按鈕（banner、card 內、toolbar）
//

import SwiftUI

struct AppCompactActionButtonStyle: ButtonStyle {
    @Environment(\.appTheme) private var appTheme
    let tone: AppActionTone

    func makeBody(configuration: Configuration) -> some View {
        let palette = stylePalette

        configuration.label
            .font(AppFonts.caption(weight: .semibold))
            .foregroundStyle(palette.foreground)
            .padding(.horizontal, AppSpacing.s3)
            .padding(.vertical, AppSpacing.s2)
            .background(
                Capsule(style: .continuous).fill(palette.background)
            )
            .overlay(
                Capsule(style: .continuous).stroke(palette.border, lineWidth: 1)
            )
            .opacity(configuration.isPressed ? AppMotion.TapFeedback.opacityDip : 1)
            .scaleEffect(configuration.isPressed ? AppMotion.TapFeedback.scaleDown : 1)
            .animation(AppMotion.TapFeedback.animation, value: configuration.isPressed)
    }

    private var stylePalette: (foreground: Color, background: Color, border: Color) {
        switch tone {
        case .primary:
            return (.white, appTheme.palette.accentHero, appTheme.palette.accentHero)
        case .neutral:
            return (
                appTheme.palette.primaryText,
                appTheme.palette.cardBackground,
                appTheme.palette.cardBorder
            )
        case .outline:
            return (
                appTheme.palette.primaryText,
                .clear,
                appTheme.palette.borderStrong
            )
        case .destructive:
            return (
                appTheme.palette.destructive,
                appTheme.palette.destructiveBg,
                appTheme.palette.destructive.opacity(0.32)
            )
        }
    }
}

extension ButtonStyle where Self == AppCompactActionButtonStyle {
    static func appCompactAction(_ tone: AppActionTone = .primary) -> AppCompactActionButtonStyle {
        AppCompactActionButtonStyle(tone: tone)
    }
}

#Preview("AppCompactActionButtonStyle") {
    AppThemeContainer {
        VStack(spacing: AppSpacing.s3) {
            Button {} label: {
                Label("開始複習（42）", systemImage: "play.fill")
            }
            .buttonStyle(.appCompactAction(.primary))

            Button {} label: {
                Label("到期複習", systemImage: "clock.badge")
            }
            .buttonStyle(.appCompactAction(.neutral))

            Button {} label: {
                Label("外框操作", systemImage: "circle")
            }
            .buttonStyle(.appCompactAction(.outline))

            Button {} label: {
                Label("刪除", systemImage: "trash")
            }
            .buttonStyle(.appCompactAction(.destructive))
        }
        .padding(AppSpacing.s5)
    }
}
