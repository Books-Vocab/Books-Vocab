import SwiftUI

struct WelcomeView: View {
    @Environment(\.appTheme) private var appTheme
    @State private var currentPage = 0

    let onStart: () -> Void
    let onLogin: () -> Void
    let onTryDemo: () -> Void

    /// 三步 walkthrough：捕捉詞彙 → 自動連結 → 每日複習
    private let pages: [WelcomePage] = [
        WelcomePage(
            icon: "text.viewfinder",
            title: "捕捉詞彙",
            subtitle: "閱讀中長按生詞，AI 依語境即時翻譯並收進筆記"
        ),
        WelcomePage(
            icon: "point.3.connected.trianglepath.dotted",
            title: "自動連結",
            subtitle: "同義、混淆、衍生自動成圖，把孤點串成知識網絡"
        ),
        WelcomePage(
            icon: "checkmark.circle.fill",
            title: "每日複習",
            subtitle: "間隔重複演算法挑選到期卡片，每日 5 分鐘穩定累積"
        ),
    ]

    init(initialPage: Int = 0, onStart: @escaping () -> Void, onLogin: @escaping () -> Void, onTryDemo: @escaping () -> Void) {
        self.onStart = onStart
        self.onLogin = onLogin
        self.onTryDemo = onTryDemo
        self._currentPage = State(initialValue: initialPage)
    }

    var body: some View {
        VStack(spacing: 0) {
            // 試用提示帶 — 鼓勵未登入者直接體驗
            tryItHint
                .padding(.top, AppMetrics.spacingSmall)
                .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)

            Spacer(minLength: AppMetrics.spacingMedium)

            // App icon
            Image("AppIconImage")
                .resizable()
                .scaledToFit()
                .frame(width: 80, height: 80)
                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                .padding(.bottom, AppWelcomeMetrics.iconBottomPadding)

            // Walkthrough（TabView 隱藏原生 indicator，改用自繪 step indicator）
            TabView(selection: $currentPage) {
                ForEach(Array(pages.enumerated()), id: \.offset) { index, page in
                    pageView(page, step: index + 1)
                        .tag(index)
                }
            }
            #if os(iOS)
            .tabViewStyle(.page(indexDisplayMode: .never))
            #endif
            .frame(height: AppWelcomeMetrics.pageHeight)
            .animateContentFade(currentPage)
            .accessibilityHint(Text("左右滑動切換步驟".localized))

            // 自繪 page indicator（避免 UIPageControl tint 跨平台不一致）
            stepIndicator
                .padding(.top, AppMetrics.spacingSmall)

            Spacer()

            // 底部固定 CTA 區
            ctaStack
                .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                .padding(.bottom, AppWelcomeMetrics.bottomPadding)
        }
        .background(appTheme.palette.pageBackground.ignoresSafeArea())
    }

    // MARK: - Subviews

    private var tryItHint: some View {
        HStack(spacing: AppMetrics.spacingSmall) {
            Image(systemName: "sparkles")
                .font(AppFonts.caption(weight: .semibold))
            Text("不用註冊也能先體驗 Demo".localized)
                .font(AppFonts.caption(weight: .medium))
            Spacer(minLength: 0)
            Button("試用".localized, action: onTryDemo)
                .font(AppFonts.caption(weight: .semibold))
                .foregroundStyle(appTheme.palette.accent)
                .accessibilityAddTraits(.isButton)
        }
        .foregroundStyle(appTheme.palette.secondaryText)
        .padding(.horizontal, AppBannerMetrics.horizontalPadding)
        .padding(.vertical, AppBannerMetrics.verticalPadding)
        .background(
            RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusMedium, style: .continuous)
                .fill(appTheme.palette.accent.opacity(AppBannerMetrics.backgroundOpacity))
        )
        .overlay(
            RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusMedium, style: .continuous)
                .stroke(appTheme.palette.accent.opacity(AppBannerMetrics.borderOpacity), lineWidth: AppMetrics.dividerStandard)
        )
        .accessibilityElement(children: .combine)
    }

    private var stepIndicator: some View {
        HStack(spacing: AppMetrics.spacingSmall) {
            ForEach(0..<pages.count, id: \.self) { index in
                Capsule()
                    .fill(index == currentPage
                          ? appTheme.palette.accent
                          : appTheme.palette.secondaryText.opacity(AppWelcomeMetrics.stepIndicatorInactiveOpacity))
                    .frame(
                        width: index == currentPage
                            ? AppWelcomeMetrics.stepIndicatorActiveWidth
                            : AppWelcomeMetrics.stepIndicatorInactiveWidth,
                        height: AppWelcomeMetrics.stepIndicatorHeight
                    )
            }
        }
        .animation(AppMotion.indicatorTransition, value: currentPage)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Text("第 \(currentPage + 1) 步，共 \(pages.count) 步".localized))
    }

    private var ctaStack: some View {
        VStack(spacing: AppMetrics.spacingSmall) {
            Button(action: onLogin) {
                Label("登入帳號".localized, systemImage: "person.crop.circle.fill")
            }
            .buttonStyle(.appAction(.primary))

            Button("開始使用".localized, action: onStart)
                .buttonStyle(.appAction(.outline))

            Text("登入後可在多裝置同步詞彙與筆記".localized)
                .font(AppFonts.caption())
                .foregroundStyle(appTheme.palette.secondaryText)
                .padding(.top, AppWelcomeMetrics.captionTopPadding)
        }
    }

    private func pageView(_ page: WelcomePage, step: Int) -> some View {
        VStack(spacing: AppMetrics.spacingMedium) {
            ZStack {
                Circle()
                    .fill(appTheme.palette.accent.opacity(AppWelcomeMetrics.iconHaloOpacity))
                    .frame(width: AppWelcomeMetrics.featureIconFrame + AppWelcomeMetrics.iconHaloPadding,
                           height: AppWelcomeMetrics.featureIconFrame + AppWelcomeMetrics.iconHaloPadding)
                Image(systemName: page.icon)
                    .font(AppFonts.hero(weight: .regular))
                    .foregroundStyle(appTheme.palette.accent)
                    .frame(width: AppWelcomeMetrics.featureIconFrame,
                           height: AppWelcomeMetrics.featureIconFrame)
            }

            VStack(spacing: AppWelcomeMetrics.pageContentSpacing) {
                Text("STEP \(step)".localized)
                    .font(AppFonts.caption(weight: .semibold))
                    .foregroundStyle(appTheme.palette.accent)
                    .tracking(AppWelcomeMetrics.stepLabelTracking)

                Text(page.title.localized)
                    .font(AppFonts.h1(weight: .semibold))
                    .foregroundStyle(appTheme.palette.primaryText)
            }

            Text(page.subtitle.localized)
                .font(AppFonts.body())
                .foregroundStyle(appTheme.palette.secondaryText)
                .multilineTextAlignment(.center)
                .padding(.horizontal, AppWelcomeMetrics.subtitleHorizontalPadding)
        }
    }
}

// MARK: - Types

private struct WelcomePage {
    let icon: String
    let title: String
    let subtitle: String
}

private struct WelcomePreviewScene: View {
    let initialPage: Int
    let preferredColorScheme: ColorScheme?

    var body: some View {
        AppThemeContainer {
            WelcomeView(initialPage: initialPage, onStart: {}, onLogin: {}, onTryDemo: {})
        }
        .preferredColorScheme(preferredColorScheme)
    }
}

#Preview("Welcome / Step 1 Capture") {
    WelcomePreviewScene(initialPage: 0, preferredColorScheme: nil)
}

#Preview("Welcome / Step 2 Link") {
    WelcomePreviewScene(initialPage: 1, preferredColorScheme: nil)
}

#Preview("Welcome / Step 3 Review") {
    WelcomePreviewScene(initialPage: 2, preferredColorScheme: nil)
}

#Preview("Welcome / Step 3 Dark") {
    WelcomePreviewScene(initialPage: 2, preferredColorScheme: .dark)
}
