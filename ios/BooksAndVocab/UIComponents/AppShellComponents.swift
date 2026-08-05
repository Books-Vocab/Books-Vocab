import SwiftUI

enum AppShellMetrics {
    static let pageHorizontalPadding = AppSpacing.s5
    static let pageTopPadding = AppSpacing.s3
    static let pageBottomPadding = AppSpacing.s9
    static let sectionSpacing = AppSpacing.s6
    static let cardRoundness = AppRoundness.card
    static let cardPadding: CGFloat = 18
    static let toolbarBadgeHorizontalPadding: CGFloat = 5
    static let toolbarBadgeVerticalPadding: CGFloat = 2
}

struct AppSectionCardStyle {
    let background: Color
    let border: Color
    let roundness: CGFloat
    let borderOpacity: Double
    let elevation: AppElevation
}

struct AppSectionTextStyle {
    let font: Font
    let color: Color
}

struct AppSectionCard<Content: View>: View {
    @Environment(\.appTheme) private var appTheme
    let padding: CGFloat
    let customStyle: AppSectionCardStyle?
    @ViewBuilder let content: Content

    init(
        padding: CGFloat = AppShellMetrics.cardPadding,
        @ViewBuilder content: () -> Content
    ) {
        self.padding = padding
        self.customStyle = nil
        self.content = content()
    }

    init(
        padding: CGFloat = AppShellMetrics.cardPadding,
        style: AppSectionCardStyle,
        @ViewBuilder content: () -> Content
    ) {
        self.padding = padding
        self.customStyle = style
        self.content = content()
    }

    var body: some View {
        let style = customStyle ?? .themed(appTheme)
        let shape = AppRoundedRect(roundness: style.roundness)
        content
            .padding(padding)
            .background(style.background)
            .clipShape(shape)
            .overlay(
                shape.stroke(style.border.opacity(style.borderOpacity), lineWidth: 1)
            )
            .appElevation(style.elevation)
    }
}

struct AppSectionHeader: View {
    @Environment(\.appTheme) private var appTheme
    let title: String
    let systemImage: String
    let customStyle: AppSectionTextStyle?

    init(title: String, systemImage: String, style: AppSectionTextStyle? = nil) {
        self.title = title
        self.systemImage = systemImage
        self.customStyle = style
    }

    var body: some View {
        let style = customStyle ?? .header(appTheme)
        Label(title.localized, systemImage: systemImage)
            .font(style.font)
            .foregroundStyle(style.color)
            .padding(.leading, AppSpacing.s1)
    }
}

struct AppSectionFooter: View {
    @Environment(\.appTheme) private var appTheme
    let text: String
    let customStyle: AppSectionTextStyle?

    init(text: String, style: AppSectionTextStyle? = nil) {
        self.text = text
        self.customStyle = style
    }

    var body: some View {
        let style = customStyle ?? .footer(appTheme)
        Text(text.localized)
            .font(style.font)
            .foregroundStyle(style.color)
            .lineSpacing(3)
            .padding(.horizontal, AppSpacing.s1)
    }
}

/// Mochi 化北極星二：border 退場、divider 進場。
///
/// 「呼吸式」群組分節 — 對應 Mochi `<hr style="margin:32px 0">` 的 long-form 切段感。
/// 給 list / 群組之間的軟分隔使用，**取代「卡片邊框 + section header 背景色塊」**。
///
/// 用法：
/// ```swift
/// VStack(spacing: 0) {
///     bookshelfSectionReading
///     AppAirDivider()
///     bookshelfSectionCompleted
///     AppAirDivider()
///     bookshelfSectionPodcasts
/// }
/// ```
///
/// 規格：1pt hairline、`palette.divider` 色、上下各 `AppMetrics.dividerAirMargin = 16` margin。
struct AppAirDivider: View {
    @Environment(\.appTheme) private var appTheme

    /// 自訂 hairline 色（預設 `palette.divider`）— 用於需特殊色相的場景。
    let tone: Color?

    init(tone: Color? = nil) { self.tone = tone }

    var body: some View {
        Rectangle()
            .fill(tone ?? appTheme.palette.divider)
            .frame(height: AppMetrics.dividerStandard)
            .padding(.vertical, AppMetrics.dividerAirMargin)
            .accessibilityHidden(true)
    }
}

struct AppSearchFieldStyle {
    let iconFont: Font
    let iconColor: Color
    let textFont: Font
    let textColor: Color
    let clearButtonFont: Font
    let clearButtonColor: Color
    let background: Color
    let border: Color
    let roundness: CGFloat
}

struct AppSearchField: View {
    @Binding var text: String
    let prompt: String
    let style: AppSearchFieldStyle
    var isFocused: FocusState<Bool>.Binding? = nil
    /// UI-test hook: applied to the inner TextField (and `.clear` suffix on the
    /// clear button) so flows can target the field by identifier. Empty = unset.
    var accessibilityID: String = ""

    var body: some View {
        HStack(spacing: AppSpacing.s2) {
            Image(systemName: "magnifyingglass")
                .font(style.iconFont)
                .foregroundStyle(style.iconColor)

            focusableTextField
                .platformTextInputConfig()
                .font(style.textFont)
                .foregroundStyle(style.textColor)
                .accessibilityIdentifier(accessibilityID)

            if !text.isEmpty {
                Button {
                    text = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(style.clearButtonFont)
                        .foregroundStyle(style.clearButtonColor)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(L10n.string("search.clear"))
                .accessibilityIdentifier(accessibilityID.isEmpty ? "" : "\(accessibilityID).clear")
            }
        }
        .padding(.horizontal, AppSpacing.s3)
        .padding(.vertical, AppSkin.baseSpacing.rowPadding)
        .background(
            AppRoundedRect(roundness: style.roundness)
                .fill(style.background)
        )
        .overlay(
            AppRoundedRect(roundness: style.roundness)
                .stroke(style.border, lineWidth: 1)
        )
    }

    @ViewBuilder
    private var focusableTextField: some View {
        if let isFocused {
            TextField(prompt.localized, text: $text)
                .focused(isFocused)
        } else {
            TextField(prompt.localized, text: $text)
        }
    }
}

struct AppKeyValueRowStyle {
    let iconFont: Font
    let iconColor: Color
    let labelFont: Font
    let labelColor: Color
    let horizontalPadding: CGFloat
    let verticalPadding: CGFloat
    let minHeight: CGFloat
    let iconWidth: CGFloat
    let spacing: CGFloat
}

struct AppKeyValueRow<Content: View>: View {
    let icon: String
    let label: String
    let style: AppKeyValueRowStyle
    let content: Content

    init(
        icon: String,
        label: String,
        style: AppKeyValueRowStyle,
        @ViewBuilder content: () -> Content
    ) {
        self.icon = icon
        self.label = label
        self.style = style
        self.content = content()
    }

    var body: some View {
        HStack(spacing: style.spacing) {
            Image(systemName: icon)
                .font(style.iconFont)
                .foregroundStyle(style.iconColor)
                .frame(width: style.iconWidth, alignment: .center)

            Text(label.localized)
                .font(style.labelFont)
                .foregroundStyle(style.labelColor)

            Spacer()

            content
        }
        .padding(.horizontal, style.horizontalPadding)
        .padding(.vertical, style.verticalPadding)
        .frame(minHeight: style.minHeight)
    }
}

struct AppSettingsDivider: View {
    @Environment(\.appSkin) private var appSkin
    let leadingInset: CGFloat

    init(leadingInset: CGFloat = 50) {
        self.leadingInset = leadingInset
    }

    var body: some View {
        Rectangle()
            .fill(appSkin.palette.divider)
            .frame(height: AppMetrics.dividerStandard)
            .padding(.leading, leadingInset)
    }
}

struct AppSectionBlock<Content: View>: View {
    @Environment(\.appSkin) private var appSkin
    let title: String
    let eyebrow: String?
    /// Mochi 北極星 #2：border 退場 — `flat=true` 時 group 不再用卡片背景包覆,
    /// 改靠呼叫端 `AppAirDivider` 切群組。`false`(預設) 維持既有 settings card 樣式以利向後相容。
    let flat: Bool
    @ViewBuilder let content: Content

    init(
        title: String,
        eyebrow: String? = nil,
        flat: Bool = false,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.eyebrow = eyebrow
        self.flat = flat
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            VStack(alignment: .leading, spacing: AppSpacing.microGap) {
                if let eyebrow, !eyebrow.isEmpty {
                    Text(eyebrow.localized)
                        .font(appSkin.typography.monoLabel)
                        .foregroundStyle(appSkin.palette.quaternaryText)
                        .tracking(1.0)
                }
                Text(title.localized)
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.tertiaryText)
            }
            .padding(.horizontal, ReaderMetrics.settingsHeaderMicroInset)

            if flat {
                // 群組內容直接坐在 panel 背景上,不再用 card 包覆。
                content
                    .padding(.horizontal, ReaderMetrics.settingsHeaderMicroInset)
            } else {
                AppSectionCard(padding: ReaderMetrics.settingsCardPadding, style: .settings(appSkin)) {
                    content
                }
            }
        }
    }
}
