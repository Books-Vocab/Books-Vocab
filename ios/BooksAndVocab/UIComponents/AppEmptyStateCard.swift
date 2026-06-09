import SwiftUI

struct AppEmptyStateStyle {
    let iconFont: Font
    let iconColor: Color
    let titleFont: Font
    let titleColor: Color
    let descriptionFont: Font
    let descriptionColor: Color
    let spacing: CGFloat
    let verticalPadding: CGFloat
}

struct AppEmptyStateAction {
    let title: String
    let systemImage: String?
    let handler: () -> Void
}

struct AppEmptyStateContent: View {
    @Environment(\.appTheme) private var appTheme
    let title: String
    let systemImage: String
    let description: String
    let guidanceText: String?
    let action: AppEmptyStateAction?
    let customStyle: AppEmptyStateStyle?
    let symbolBounce: Bool

    init(title: String, systemImage: String, description: String, guidanceText: String? = nil, action: AppEmptyStateAction? = nil, symbolBounce: Bool = false, style: AppEmptyStateStyle? = nil) {
        self.title = title
        self.systemImage = systemImage
        self.description = description
        self.guidanceText = guidanceText
        self.action = action
        self.symbolBounce = symbolBounce
        self.customStyle = style
    }

    var body: some View {
        let style = customStyle ?? .themed(appTheme)
        VStack(spacing: style.spacing) {
            Image(systemName: systemImage)
                .font(style.iconFont)
                .foregroundStyle(style.iconColor)
                .symbolEffect(.bounce, value: symbolBounce)

            Text(title.localized)
                .font(style.titleFont)
                .foregroundStyle(style.titleColor)

            Text(description.localized)
                .font(style.descriptionFont)
                .foregroundStyle(style.descriptionColor)
                .multilineTextAlignment(.center)

            if let guidanceText {
                Text(guidanceText.localized)
                    .font(style.descriptionFont)
                    .foregroundStyle(style.descriptionColor.opacity(0.7))
                    .multilineTextAlignment(.center)
            }

            if let action {
                Button(action: action.handler) {
                    Label(action.title, systemImage: action.systemImage ?? "arrow.right")
                }
                .buttonStyle(.appAction(.outline))
            }
        }
        .frame(maxWidth: .infinity)
    }
}

struct AppEmptyStateCard: View {
    @Environment(\.appTheme) private var appTheme
    let title: String
    let systemImage: String
    let description: String
    let action: AppEmptyStateAction?
    let customCardStyle: AppSectionCardStyle?
    let customContentStyle: AppEmptyStateStyle?

    init(
        title: String,
        systemImage: String,
        description: String,
        action: AppEmptyStateAction? = nil,
        cardStyle: AppSectionCardStyle? = nil,
        contentStyle: AppEmptyStateStyle? = nil
    ) {
        self.title = title
        self.systemImage = systemImage
        self.description = description
        self.action = action
        self.customCardStyle = cardStyle
        self.customContentStyle = contentStyle
    }

    var body: some View {
        let cardStyle = customCardStyle ?? .themed(appTheme)
        let contentStyle = customContentStyle ?? .themed(appTheme)

        AppSectionCard(style: cardStyle) {
            AppEmptyStateContent(
                title: title,
                systemImage: systemImage,
                description: description,
                action: action,
                style: contentStyle
            )
            .padding(.vertical, contentStyle.verticalPadding)
        }
    }
}

extension AppEmptyStateStyle {
    static func themed(_ theme: AppTheme) -> AppEmptyStateStyle {
        .init(
            iconFont: AppFonts.hero(weight: .light),
            iconColor: theme.palette.tertiaryText,
            titleFont: AppFonts.h2(weight: .semibold),
            titleColor: theme.palette.primaryText,
            descriptionFont: AppFonts.body(),
            descriptionColor: theme.palette.secondaryText,
            spacing: 14,
            verticalPadding: 12
        )
    }

    static func vocab(_ skin: AppSkin) -> AppEmptyStateStyle {
        .init(
            iconFont: skin.typography.symbolLarge,
            iconColor: skin.palette.tertiaryText,
            titleFont: skin.typography.sectionTitle,
            titleColor: skin.palette.primaryText,
            descriptionFont: skin.typography.body,
            descriptionColor: skin.palette.secondaryText,
            spacing: 14,
            verticalPadding: 12
        )
    }

    static func bookshelf(_ theme: AppTheme) -> AppEmptyStateStyle {
        .init(
            iconFont: AppFonts.symbol(size: 48, weight: .ultraLight),
            iconColor: theme.palette.quaternaryText,
            titleFont: AppFonts.subhead(weight: .medium),
            titleColor: theme.palette.secondaryText,
            descriptionFont: AppFonts.caption(),
            descriptionColor: theme.palette.tertiaryText,
            spacing: 6,
            verticalPadding: 0
        )
    }
}

#Preview("AppEmptyStateCard") {
    AppThemeContainer {
        AppEmptyStateCardPreview()
    }
    .environmentObject(AppAppearanceStore.preview)
}

private struct AppEmptyStateCardPreview: View {
    @Environment(\.appTheme) private var appTheme

    var body: some View {
        VStack(spacing: AppSpacing.s4) {
            AppEmptyStateCard(
                title: "尚無內容",
                systemImage: "tray",
                description: "這個 preview 用來驗證空狀態卡片的基本輸出。"
            )
        }
        .padding()
        .background(appTheme.palette.pageBackground.ignoresSafeArea())
    }
}
