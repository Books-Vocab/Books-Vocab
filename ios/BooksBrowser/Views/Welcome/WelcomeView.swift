import SwiftUI

struct WelcomeView: View {
    @Environment(\.appTheme) private var appTheme
    @State private var currentPage = 0

    let onStart: () -> Void
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

    var body: some View {
        VStack(spacing: 0) {
            Spacer()

            // App icon
            Image("AppIconImage")
                .resizable()
                .scaledToFit()
                .frame(width: 80, height: 80)
                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                .padding(.bottom, WelcomeMetrics.iconBottomPadding)

            // Page content
            TabView(selection: $currentPage) {
                ForEach(Array(pages.enumerated()), id: \.offset) { index, page in
                    pageView(page)
                        .tag(index)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: .always))
            .frame(height: WelcomeMetrics.pageHeight)

            Spacer()

            // CTA buttons
            VStack(spacing: WelcomeMetrics.buttonSpacing) {
                Button("開始使用".localized, action: onStart)
                    .buttonStyle(.appAction(.primary))

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
            .padding(.bottom, WelcomeMetrics.bottomPadding)
        }
        .background(appTheme.palette.pageBackground.ignoresSafeArea())
    }

    private func pageView(_ page: WelcomePage) -> some View {
        VStack(spacing: WelcomeMetrics.pageContentSpacing) {
            Image(systemName: page.icon)
                .font(AppFonts.h2(weight: .medium))
                .foregroundStyle(appTheme.palette.accent)
                .frame(width: WelcomeMetrics.featureIconFrame, height: WelcomeMetrics.featureIconFrame)
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
                .padding(.horizontal, WelcomeMetrics.subtitleHorizontalPadding)
        }
    }
}

// MARK: - Types

private struct WelcomePage {
    let icon: String
    let title: String
    let subtitle: String
}

private enum WelcomeMetrics {
    static let iconBottomPadding: CGFloat = 12
    static let pageHeight: CGFloat = 240
    static let pageContentSpacing: CGFloat = 16
    static let featureIconSize: CGFloat = 32
    static let featureIconFrame: CGFloat = 64
    static let subtitleHorizontalPadding: CGFloat = 40
    static let buttonSpacing: CGFloat = 8
    static let bottomPadding: CGFloat = 40
}

#Preview("Welcome / Light") {
    AppThemeContainer {
        WelcomeView(onStart: {}, onTryDemo: {})
    }
}

#Preview("Welcome / Dark") {
    AppThemeContainer {
        WelcomeView(onStart: {}, onTryDemo: {})
    }
    .preferredColorScheme(.dark)
}
