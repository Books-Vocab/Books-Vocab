import SwiftUI

// MARK: - Style Static Extensions

extension AppSectionCardStyle {
    static func themed(_ theme: AppTheme) -> AppSectionCardStyle {
        .init(
            background: theme.palette.cardBackground,
            border: theme.palette.cardBorder,
            roundness: AppShellMetrics.cardRoundness,
            borderOpacity: 0.7,
            elevation: .z1
        )
    }

    static func vocab(_ skin: AppSkin) -> AppSectionCardStyle {
        .init(
            background: skin.palette.cardBackground,
            border: skin.palette.cardBorder,
            roundness: skin.roundness.card,
            borderOpacity: 0.7,
            elevation: .z1
        )
    }

    static func settings(_ skin: AppSkin) -> AppSectionCardStyle {
        .init(
            background: skin.palette.cardBackground,
            border: skin.palette.cardBorder,
            roundness: skin.roundness.card,
            borderOpacity: 1,
            elevation: .z0
        )
    }

    /// Mochi 化北極星二：border 退場、divider 進場。
    /// `.flat` style — 純背景、無 border、無 shadow，給 list cards 預設樣式。
    /// 視覺分區改靠 `AppAirDivider` + 留白，不再靠卡片邊框。
    static func flat(_ theme: AppTheme) -> AppSectionCardStyle {
        .init(
            background: theme.palette.cardBackground,
            border: .clear,
            roundness: AppShellMetrics.cardRoundness,
            borderOpacity: 0,
            elevation: .z0
        )
    }


    /// `.flat` 的「完全透明」版 — 連 background 都不上，只佔 layout，給「就坐在 page bg 上」的場景用。
    static var ghostFlat: AppSectionCardStyle {
        .init(
            background: .clear,
            border: .clear,
            roundness: AppShellMetrics.cardRoundness,
            borderOpacity: 0,
            elevation: .z0
        )
    }
}

extension AppSectionTextStyle {
    static func header(_ theme: AppTheme) -> AppSectionTextStyle {
        .init(font: AppFonts.caption(weight: .semibold), color: theme.palette.secondaryText)
    }

    static func footer(_ theme: AppTheme) -> AppSectionTextStyle {
        .init(font: AppFonts.caption(), color: theme.palette.tertiaryText)
    }
}

extension AppSearchFieldStyle {
    static func themed(_ theme: AppTheme) -> AppSearchFieldStyle {
        .init(
            iconFont: AppFonts.caption(weight: .medium),
            iconColor: theme.palette.tertiaryText,
            textFont: AppFonts.body(),
            textColor: theme.palette.primaryText,
            clearButtonFont: AppFonts.caption(weight: .medium),
            clearButtonColor: theme.palette.quaternaryText,
            background: theme.palette.cardBackground,
            border: theme.palette.cardBorder,
            roundness: AppRoundness.control
        )
    }

    static func vocab(_ skin: AppSkin) -> AppSearchFieldStyle {
        .init(
            iconFont: skin.typography.iconSmall,
            iconColor: skin.palette.tertiaryText,
            textFont: skin.typography.body,
            textColor: skin.palette.primaryText,
            clearButtonFont: skin.typography.iconMedium,
            clearButtonColor: skin.palette.quaternaryText,
            background: skin.palette.mutedFill,
            border: skin.palette.divider,
            roundness: skin.roundness.control
        )
    }
}

extension AppKeyValueRowStyle {
    static func themed(_ theme: AppTheme) -> AppKeyValueRowStyle {
        .init(
            iconFont: AppFonts.caption(weight: .medium),
            iconColor: theme.palette.secondaryText,
            labelFont: AppFonts.body(),
            labelColor: theme.palette.primaryText,
            horizontalPadding: AppShellMetrics.cardPadding,
            verticalPadding: 13,
            minHeight: 50,
            iconWidth: 22,
            spacing: AppSpacing.s3
        )
    }

    static func vocab(_ skin: AppSkin) -> AppKeyValueRowStyle {
        .init(
            iconFont: skin.typography.iconSmall,
            iconColor: skin.palette.secondaryText,
            labelFont: skin.typography.body,
            labelColor: skin.palette.primaryText,
            horizontalPadding: skin.spacing.cardPadding,
            verticalPadding: 13,
            minHeight: 50,
            iconWidth: 22,
            spacing: AppSpacing.s3
        )
    }

    static func settings(_ skin: AppSkin) -> AppKeyValueRowStyle {
        .init(
            iconFont: skin.typography.iconSmall,
            iconColor: skin.palette.secondaryText,
            labelFont: skin.typography.body,
            labelColor: skin.palette.primaryText,
            horizontalPadding: skin.spacing.cardPadding,
            verticalPadding: 13,
            minHeight: 50,
            iconWidth: 22,
            spacing: AppSpacing.s3
        )
    }
}
