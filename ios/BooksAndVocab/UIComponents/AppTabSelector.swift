import SwiftUI

struct AppTabOption<ID: Hashable>: Identifiable, Hashable {
    let id: ID
    let title: String
    let count: Int?
    let systemImage: String?

    init(id: ID, title: String, count: Int? = nil, systemImage: String? = nil) {
        self.id = id
        self.title = title
        self.count = count
        self.systemImage = systemImage
    }
}

struct AppTabSelectorStyle {
    let iconFont: Font
    let titleFont: Font
    let countFont: Font
    let iconSelectedColor: Color
    let iconUnselectedColor: Color
    let textSelectedColor: Color
    let textUnselectedColor: Color
    let countSelectedFill: Color
    let countUnselectedFill: Color
    let selectedBackground: Color
    let unselectedBackground: Color
    let selectedBorder: Color
    let unselectedBorder: Color
    let selectedOuterBorder: Color
    let unselectedOuterBorder: Color
    let containerBackground: Color
    /// 容器圓度。chip 本身恆為 `AppRoundness.pill`（見 `appChipLabel`），容器同樣走
    /// pill 即自動同心 —— 半徑由各自的 box 導出，容器高度只比 chip 多兩倍 padding，
    /// 兩者半徑差恰等於該 padding。舊版靠 `±2` / `+4` 手算補償，在相對圓角下已無必要。
    let containerRoundness: CGFloat
    let outerBorderInset: CGFloat
}

/// a11y label for a chip — title plus optional item count. Shared by `AppTabSelector`
/// and `AppFilterChipBar` alongside `appChipLabel`, keeping the spoken text identical.
func appChipAccessibilityLabel<ID: Hashable>(option: AppTabOption<ID>) -> String {
    option.count.map { "\(option.title.localized), \($0) \("個項目".localized)" } ?? option.title.localized
}

/// Shared chip label body for `AppTabSelector` (single-select) and
/// `AppFilterChipBar` (multi-select). Both compute their own `isSelected`
/// and supply identical visual treatment via this builder — keep it as the
/// single source of truth for chip label/count/border/a11y geometry.
@ViewBuilder
func appChipLabel<ID: Hashable>(
    option: AppTabOption<ID>,
    isSelected: Bool,
    style: AppTabSelectorStyle
) -> some View {
    HStack(spacing: 6) {
        if let systemImage = option.systemImage {
            Image(systemName: systemImage)
                .font(style.iconFont)
                .foregroundStyle(isSelected ? style.iconSelectedColor : style.iconUnselectedColor)
                .fixedSize()
        }

        Text(option.title.localized)
            .font(style.titleFont)
            .foregroundStyle(isSelected ? style.textSelectedColor : style.textUnselectedColor)
            .lineLimit(1)
            .minimumScaleFactor(0.72)
            .layoutPriority(1)

        if let count = option.count {
            Text("\(count)")
                .font(style.countFont)
                .minimumScaleFactor(0.7)
                .monospacedDigit()
                .lineLimit(1)
                .fixedSize(horizontal: true, vertical: false)
                .frame(minWidth: 26)
                .padding(.horizontal, AppSkin.baseSpacing.compactChipHorizontalPadding)
                .padding(.vertical, AppSpacing.microGap)
                .background(
                    AppRoundedRect(roundness: AppRoundness.pill)
                        .fill(isSelected ? style.countSelectedFill : style.countUnselectedFill)
                )
        }
    }
    .frame(maxWidth: .infinity)
    .padding(.horizontal, AppSpacing.s2)
    .padding(.vertical, AppSpacing.s2)
    .background(
        AppRoundedRect(roundness: AppRoundness.pill)
            .fill(isSelected ? style.selectedBackground : style.unselectedBackground)
    )
    .overlay(
        AppRoundedRect(roundness: AppRoundness.pill)
            .stroke(isSelected ? style.selectedBorder : style.unselectedBorder, lineWidth: 1)
    )
    .overlay(
        AppRoundedRect(roundness: AppRoundness.pill)
        .stroke(
            isSelected ? style.selectedOuterBorder : style.unselectedOuterBorder,
            lineWidth: 0.8
        )
        .padding(-style.outerBorderInset)
    )
}

struct AppTabSelector<ID: Hashable>: View {
    let options: [AppTabOption<ID>]
    @Binding var selection: ID
    let style: AppTabSelectorStyle

    var body: some View {
        HStack(spacing: AppSpacing.s2) {
            ForEach(options) { option in
                let isSelected = selection == option.id
                Button {
                    withAnimation(AppMotion.chipSelect) {
                        selection = option.id
                    }
                } label: {
                    appChipLabel(option: option, isSelected: isSelected, style: style)
                }
                .buttonStyle(.plain)
                .appPointerHover()
                .accessibilityLabel(appChipAccessibilityLabel(option: option))
                .accessibilityAddTraits(isSelected ? .isSelected : [])
            }
        }
        .padding(AppSpacing.tinyGap)
        .background(
            AppRoundedRect(roundness: style.containerRoundness)
                .fill(style.containerBackground)
        )
    }
}

extension AppTabSelectorStyle {
    static func themed(_ theme: AppTheme) -> AppTabSelectorStyle {
        .init(
            iconFont: AppFonts.caption(weight: .medium),
            titleFont: AppFonts.caption(weight: .semibold),
            countFont: AppFonts.monoNumbers(size: 10),
            iconSelectedColor: theme.palette.primaryText,
            iconUnselectedColor: theme.palette.secondaryText,
            textSelectedColor: theme.palette.primaryText,
            textUnselectedColor: theme.palette.secondaryText,
            countSelectedFill: theme.palette.primaryText.opacity(0.08),
            countUnselectedFill: theme.palette.mutedFill,
            selectedBackground: theme.palette.cardBackground,
            unselectedBackground: theme.palette.stageBackground,
            selectedBorder: theme.palette.cardBorder,
            unselectedBorder: theme.palette.divider.opacity(0.8),
            selectedOuterBorder: theme.palette.cardBorder.opacity(0.45),
            unselectedOuterBorder: theme.palette.divider.opacity(0.45),
            containerBackground: theme.palette.pageBackground,
            containerRoundness: AppRoundness.pill,
            outerBorderInset: 3
        )
    }

    static func vocab(_ skin: AppSkin) -> AppTabSelectorStyle {
        .init(
            iconFont: skin.typography.iconSmall,
            titleFont: skin.typography.caption,
            countFont: skin.typography.monoLabel,
            iconSelectedColor: skin.palette.primaryText,
            iconUnselectedColor: skin.palette.secondaryText,
            textSelectedColor: skin.palette.primaryText,
            textUnselectedColor: skin.palette.secondaryText,
            countSelectedFill: skin.palette.primaryText.opacity(0.08),
            countUnselectedFill: skin.palette.mutedFill,
            selectedBackground: skin.palette.mutedFill,
            unselectedBackground: .clear,
            selectedBorder: .clear,
            unselectedBorder: .clear,
            selectedOuterBorder: .clear,
            unselectedOuterBorder: .clear,
            containerBackground: skin.palette.stageBackground,
            containerRoundness: skin.roundness.pill,
            outerBorderInset: 0
        )
    }
}

#Preview("AppTabSelector") {
    AppThemeContainer {
        AppTabSelectorPreview()
    }
    .environmentObject(AppAppearanceStore.preview)
}

private struct AppTabSelectorPreview: View {
    @Environment(\.appTheme) private var appTheme
    @State private var selected = 0

    var body: some View {
        VStack(spacing: AppSpacing.s5) {
            AppTabSelector(
                options: [
                    .init(id: 0, title: "書庫", count: 12, systemImage: "books.vertical"),
                    .init(id: 1, title: "單字本", count: 248, systemImage: "character.book.closed"),
                    .init(id: 2, title: "設定", systemImage: "gearshape")
                ],
                selection: $selected,
                style: .themed(appTheme)
            )
        }
        .padding()
        .background(appTheme.palette.pageBackground.ignoresSafeArea())
    }
}
