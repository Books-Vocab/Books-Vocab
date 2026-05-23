#if DEBUG
import Playbook
import SwiftUI

/// Visual reference sheet for the AppSkin design tokens. Used as the
/// baseline check when shifting palette / typography / spacing values
/// — render this in the catalog before/after a token change and diff
/// the screenshots.
///
/// 故意不依賴任何 production view；純 token swatch grid，避免改 UI 時
/// 順手把這頁也改壞。
enum TokenSheetScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Design Tokens") {
            Scenario("Palette / Light", layout: .fill) {
                paletteSheet(theme: .light, scheme: .light)
            }
            Scenario("Palette / Dark", layout: .fill) {
                paletteSheet(theme: .dark, scheme: .dark)
            }
            Scenario("Typography", layout: .fill) {
                typographySheet()
            }
            Scenario("Radii & Spacing", layout: .fill) {
                radiiSpacingSheet()
            }
        }
    }

    // MARK: - Sheets

    private static func paletteSheet(theme: AppTheme, scheme: ColorScheme) -> some View {
        let skin = AppSkin.themed(theme)
        let palette = skin.palette

        let groups: [(String, [(String, Color)])] = [
            ("Surfaces", [
                ("pageBackground", palette.pageBackground),
                ("stageBackground", palette.stageBackground),
                ("cardBackground", palette.cardBackground),
                ("mutedFill", palette.mutedFill)
            ]),
            ("Text", [
                ("primaryText", palette.primaryText),
                ("secondaryText", palette.secondaryText),
                ("tertiaryText", palette.tertiaryText),
                ("quaternaryText", palette.quaternaryText)
            ]),
            ("Brand Hero (primary · cream gold)", [
                ("brandHero", palette.brandHero)
            ]),
            ("Accent (passive · Morandi blue)", [
                ("accent", palette.accent),
                ("link", palette.link),
                ("info", palette.info)
            ]),
            ("State", [
                ("success", palette.success),
                ("warning", palette.warning),
                ("destructive", palette.destructive),
                ("overdue", palette.overdue)
            ])
        ]

        return ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("Palette · \(scheme == .dark ? "Dark" : "Light")")
                    .font(skin.typography.displayTitle)
                    .foregroundStyle(palette.primaryText)
                    .padding(.top, 12)

                ForEach(Array(groups.enumerated()), id: \.offset) { _, group in
                    VStack(alignment: .leading, spacing: 8) {
                        Text(group.0)
                            .font(skin.typography.caption)
                            .tracking(0.6)
                            .foregroundStyle(palette.tertiaryText)
                        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
                            ForEach(Array(group.1.enumerated()), id: \.offset) { _, swatch in
                                swatchTile(label: swatch.0, color: swatch.1, palette: palette, typography: skin.typography)
                            }
                        }
                    }
                }
            }
            .padding(.horizontal, 18)
            .padding(.bottom, 32)
        }
        .background(palette.pageBackground.ignoresSafeArea())
        .environment(\.colorScheme, scheme)
        .appTheme(theme)
        .appSkin(skin)
    }

    private static func swatchTile(label: String, color: Color, palette: AppSkin.Palette, typography: AppSkin.Typography) -> some View {
        HStack(spacing: 10) {
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .fill(color)
                .overlay(
                    RoundedRectangle(cornerRadius: 6, style: .continuous)
                        .stroke(palette.cardBorder, lineWidth: 0.5)
                )
                .frame(width: 36, height: 36)
            Text(label)
                .font(typography.monoBody)
                .foregroundStyle(palette.secondaryText)
                .lineLimit(1)
                .truncationMode(.tail)
            Spacer(minLength: 0)
        }
    }

    private static func typographySheet() -> some View {
        let skin = AppSkin.previewNeutral
        let palette = skin.palette
        let samples: [(String, Font)] = [
            ("displayTitle", skin.typography.displayTitle),
            ("sectionTitle", skin.typography.sectionTitle),
            ("detailWord", skin.typography.detailWord),
            ("rowWord", skin.typography.rowWord),
            ("translationTitle", skin.typography.translationTitle),
            ("body", skin.typography.body),
            ("example", skin.typography.example),
            ("caption", skin.typography.caption),
            ("monoLabel", skin.typography.monoLabel),
            ("monoBody", skin.typography.monoBody),
            ("numericHero", skin.typography.numericHero)
        ]
        return ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("Typography")
                    .font(skin.typography.displayTitle)
                    .foregroundStyle(palette.primaryText)
                    .padding(.top, 12)
                ForEach(Array(samples.enumerated()), id: \.offset) { _, sample in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(sample.0)
                            .font(skin.typography.caption)
                            .foregroundStyle(palette.tertiaryText)
                        Text("The quick brown fox · 機智的棕狐") // i18n-allow: typography preview sample
                            .font(sample.1)
                            .foregroundStyle(palette.primaryText)
                    }
                }
            }
            .padding(.horizontal, 18)
            .padding(.bottom, 32)
        }
        .background(palette.pageBackground.ignoresSafeArea())
        .appSkin(skin)
    }

    private static func radiiSpacingSheet() -> some View {
        let skin = AppSkin.previewNeutral
        let palette = skin.palette
        let radii: [(String, CGFloat)] = [
            ("tiny (sm)", skin.radii.tiny),
            ("chip (sm)", skin.radii.chip),
            ("control (sm)", skin.radii.control),
            ("card (md)", skin.radii.card),
            ("overlay (md)", skin.radii.overlay)
        ]
        let spacings: [(String, CGFloat)] = [
            ("microGap", skin.spacing.microGap),
            ("tinyGap", skin.spacing.tinyGap),
            ("inlineGap", skin.spacing.inlineGap),
            ("controlGap", skin.spacing.controlGap),
            ("sectionGap", skin.spacing.sectionGap),
            ("cardPadding", skin.spacing.cardPadding),
            ("sheetSectionSpacing", skin.spacing.sheetSectionSpacing),
            ("sheetPadding", skin.spacing.sheetPadding)
        ]
        return ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("Radii & Spacing")
                    .font(skin.typography.displayTitle)
                    .foregroundStyle(palette.primaryText)
                    .padding(.top, 12)

                VStack(alignment: .leading, spacing: 10) {
                    Text("Radii")
                        .font(skin.typography.caption)
                        .foregroundStyle(palette.tertiaryText)
                    ForEach(Array(radii.enumerated()), id: \.offset) { _, radius in
                        HStack(spacing: 10) {
                            RoundedRectangle(cornerRadius: radius.1, style: .continuous)
                                .fill(palette.mutedFill)
                                .overlay(
                                    RoundedRectangle(cornerRadius: radius.1, style: .continuous)
                                        .stroke(palette.cardBorder, lineWidth: 0.5)
                                )
                                .frame(width: 56, height: 40)
                            Text("\(radius.0) · \(Int(radius.1))pt")
                                .font(skin.typography.monoBody)
                                .foregroundStyle(palette.secondaryText)
                        }
                    }
                }

                VStack(alignment: .leading, spacing: 10) {
                    Text("Spacing")
                        .font(skin.typography.caption)
                        .foregroundStyle(palette.tertiaryText)
                    ForEach(Array(spacings.enumerated()), id: \.offset) { _, spacing in
                        HStack(spacing: 10) {
                            Rectangle()
                                .fill(palette.accent)
                                .frame(width: spacing.1, height: 12)
                            Text("\(spacing.0) · \(Int(spacing.1))pt")
                                .font(skin.typography.monoBody)
                                .foregroundStyle(palette.secondaryText)
                        }
                    }
                }
            }
            .padding(.horizontal, 18)
            .padding(.bottom, 32)
        }
        .background(palette.pageBackground.ignoresSafeArea())
        .appSkin(skin)
    }
}
#endif
