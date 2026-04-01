import SwiftUI

struct WelcomeView: View {
    @Environment(\.appTheme) private var appTheme
    @State private var currentPage = 0

    let onStart: () -> Void
    let onLogin: () -> Void
    let onTryDemo: () -> Void

    private let pages: [WelcomePage] = [
        WelcomePage(
            icon: "book.fill",
            title: "閱讀原文書",
            subtitle: "匯入 EPUB 電子書，沉浸式閱讀"
        ),
        WelcomePage(
            icon: "text.bubble.fill",
            title: "即時翻譯",
            subtitle: "長按查詞，AI 依語境精準翻譯"
        ),
        WelcomePage(
            icon: "rectangle.stack.fill",
            title: "智慧複習",
            subtitle: "間隔重複演算法，滑動歸類卡片"
        ),
        WelcomePage(
            icon: "point.3.connected.trianglepath.dotted",
            title: "知識圖譜",
            subtitle: "同義、混淆、衍生關係一目了然"
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
            Spacer()

            // App icon
            Image("AppIconImage")
                .resizable()
                .scaledToFit()
                .frame(width: 80, height: 80)
                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                .padding(.bottom, AppWelcomeMetrics.iconBottomPadding)

            // Page content
            TabView(selection: $currentPage) {
                ForEach(Array(pages.enumerated()), id: \.offset) { index, page in
                    pageView(page)
                        .tag(index)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: .always))
            .frame(height: AppWelcomeMetrics.pageHeight)

            Spacer()

            // CTA buttons
            VStack(spacing: AppMetrics.spacingSmall) {
                Button("開始使用".localized, action: onStart)
                    .buttonStyle(.appAction(.primary))

                Button(action: onLogin) {
                    Label("登入帳號".localized, systemImage: "person.crop.circle")
                }
                .buttonStyle(.appAction(.outline))

                Button(action: onTryDemo) {
                    HStack(spacing: 6) {
                        Image(systemName: "play.circle")
                            .font(AppFonts.body())
                        Text("先體驗看看".localized)
                            .font(AppFonts.body(weight: .medium))
                    }
                    .foregroundStyle(appTheme.palette.accent)
                }
                .buttonStyle(.plain)
                .padding(.vertical, AppMetrics.spacingSmall)
            }
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
            .padding(.bottom, AppWelcomeMetrics.bottomPadding)
        }
        .background(appTheme.palette.pageBackground.ignoresSafeArea())
    }

    private func pageView(_ page: WelcomePage) -> some View {
        VStack(spacing: AppMetrics.spacingMedium) {
            Image(systemName: page.icon)
                .font(AppFonts.h2(weight: .medium))
                .foregroundStyle(appTheme.palette.accent)
                .frame(width: AppWelcomeMetrics.featureIconFrame, height: AppWelcomeMetrics.featureIconFrame)
                .background(
                    Circle()
                        .fill(appTheme.palette.accent.opacity(0.10))
                )

            Text(page.title.localized)
                .font(AppFonts.h2(weight: .semibold))
                .foregroundStyle(appTheme.palette.primaryText)

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

#Preview("Welcome / Reader") {
    WelcomePreviewScene(initialPage: 0, preferredColorScheme: nil)
}

#Preview("Welcome / Translate") {
    WelcomePreviewScene(initialPage: 1, preferredColorScheme: nil)
}

#Preview("Welcome / Review") {
    WelcomePreviewScene(initialPage: 2, preferredColorScheme: nil)
}

#Preview("Welcome / Graph Dark") {
    WelcomePreviewScene(initialPage: 3, preferredColorScheme: .dark)
}
