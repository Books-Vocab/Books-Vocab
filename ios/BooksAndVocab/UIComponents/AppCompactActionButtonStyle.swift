//
//  AppCompactActionButtonStyle.swift
//  Books & Vocab
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

enum AppCompactActionSurface: Equatable {
    case solid
    case glass
}

private enum AppCompactActionMetrics {
    static let hitTarget: CGFloat = 44
}

struct AppCompactActionButtonStyle: ButtonStyle {
    @Environment(\.appTheme) private var appTheme
    let tone: AppActionTone

    func makeBody(configuration: Configuration) -> some View {
        let palette = stylePalette
        let shape = AppRoundedRect(roundness: AppRoundness.pill)

        let label = configuration.label
            .font(AppFonts.caption(weight: .semibold))
            .foregroundStyle(palette.foreground)
            .padding(.horizontal, AppSpacing.s3)
            .padding(.vertical, AppSpacing.s2)
            .frame(minHeight: AppCompactActionMetrics.hitTarget)
            .contentShape(shape)

        surface(label, shape: shape, palette: palette)
            .opacity(configuration.isPressed ? AppMotion.TapFeedback.opacityDip : 1)
            .scaleEffect(configuration.isPressed ? AppMotion.TapFeedback.scaleDown : 1)
            .animation(AppMotion.TapFeedback.animation, value: configuration.isPressed)
    }

    @ViewBuilder
    private func surface<Content: View>(
        _ content: Content,
        shape: AppRoundedRect,
        palette: (foreground: Color, background: Color, border: Color)
    ) -> some View {
        switch tone {
        case .primary:
            content
                .background(shape.fill(palette.background))
                .overlay(shape.stroke(palette.border, lineWidth: 1))
        case .neutral:
            content.glassEffect(.regular.interactive(), in: shape)
        case .outline:
            content.glassEffect(
                .regular
                    .tint(appTheme.palette.accent.opacity(0.08))
                    .interactive(),
                in: shape
            )
        case .destructive:
            content.glassEffect(
                .regular
                    .tint(appTheme.palette.destructiveBg)
                    .interactive(),
                in: shape
            )
        }
    }

    static func surface(for tone: AppActionTone) -> AppCompactActionSurface {
        switch tone {
        case .primary: .solid
        case .neutral, .outline, .destructive: .glass
        }
    }

    private var stylePalette: (foreground: Color, background: Color, border: Color) {
        switch tone {
        case .primary:
            // 奶黃 CTA：light/dark 各自走 palette.brandHero，前景為 deep charcoal
            // onBrandHero (#1C1A17)：
            //   brandHeroLight #B5894B + onBrandHero = ~5.11:1 ✓ AA pass
            //   brandHeroDark  #C9A968 + onBrandHero = ~7.05:1 ✓ AAA pass
            // 白字反而 fail（~3.4:1）— 此 ButtonStyle 走 AppColors.onBrandHero 故合規。
            let bg = appTheme.palette.brandHero
            return (AppColors.onBrandHero, bg, bg)
        case .neutral:
            return (
                appTheme.palette.primaryText,
                .clear,
                .clear
            )
        case .outline:
            return (
                appTheme.palette.primaryText,
                .clear,
                .clear
            )
        case .destructive:
            return (
                appTheme.palette.destructive,
                .clear,
                .clear
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
    .environmentObject(AppAppearanceStore.preview)
}
