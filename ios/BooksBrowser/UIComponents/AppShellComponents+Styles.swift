import SwiftUI

// MARK: - Style Static Extensions

extension AppSectionCardStyle {
    static func themed(_ theme: AppTheme) -> AppSectionCardStyle {
        .init(
            background: theme.palette.cardBackground,
            border: theme.palette.cardBorder,
            cornerRadius: AppShellMetrics.cardCornerRadius,
            borderOpacity: 0.7,
            elevation: .z1
        )
    }

    static func vocab(_ skin: AppSkin) -> AppSectionCardStyle {
        .init(
            background: skin.palette.cardBackground,
            border: skin.palette.cardBorder,
            cornerRadius: skin.radii.card,
            borderOpacity: 0.7,
            elevation: .z1
        )
    }

    static func settings(_ skin: AppSkin) -> AppSectionCardStyle {
        .init(
            background: skin.palette.cardBackground,
            border: skin.palette.cardBorder,
            cornerRadius: skin.radii.card,
            borderOpacity: 1,
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
            cornerRadius: AppRadius.md - 2
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
            cornerRadius: skin.radii.control
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
