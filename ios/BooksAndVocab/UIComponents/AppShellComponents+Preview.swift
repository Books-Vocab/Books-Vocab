import SwiftUI

// MARK: - Preview

#Preview("Shared Shell / App") {
    AppThemeContainer {
        AppShellPreview(variant: .app)
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("Shared Shell / Vocab") {
    AppThemeContainer {
        AppShellPreview(variant: .vocab)
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("Shared Shell / Settings") {
    AppThemeContainer {
        AppShellPreview(variant: .settings)
    }
    .environmentObject(AppAppearanceStore.preview)
}

enum AppShellPreviewVariant {
    case app
    case vocab
    case settings
}

struct AppShellPreview: View {
    @Environment(\.appTheme) private var appTheme
    @Environment(\.appSkin) private var appSkin
    let variant: AppShellPreviewVariant
    @State private var selectedTab = 0
    @State private var searchText = "mystery"

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: AppShellMetrics.sectionSpacing) {
                previewHeader
                previewBody
            }
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
            .padding(.top, AppShellMetrics.pageTopPadding)
            .padding(.bottom, AppShellMetrics.pageBottomPadding)
        }
        .background(previewBackground.ignoresSafeArea())
    }

    private var previewBackground: Color {
        switch variant {
        case .app:
            return appTheme.palette.pageBackground
        case .vocab, .settings:
            return appSkin.palette.pageBackground
        }
    }

    private var previewHeader: some View {
        switch variant {
        case .app:
            return AnyView(AppSectionHeader(title: "Shell", systemImage: "square.grid.2x2"))
        case .vocab:
            return AnyView(
                AppSectionHeader(
                    title: "Vocabulary Shell",
                    systemImage: "character.book.closed",
                    style: .init(
                        font: appSkin.typography.caption,
                        color: appSkin.palette.secondaryText
                    )
                )
            )
        case .settings:
            return AnyView(
                AppSectionHeader(
                    title: "Settings Shell",
                    systemImage: "gearshape",
                    style: .init(
                        font: appSkin.typography.caption,
                        color: appSkin.palette.secondaryText
                    )
                )
            )
        }
    }

    @ViewBuilder
    private var previewBody: some View {
        switch variant {
        case .app:
            previewShellCard(
                cardStyle: .themed(appTheme),
                tabStyle: .themed(appTheme),
                searchStyle: .themed(appTheme),
                keyValueStyle: .themed(appTheme),
                toolbarStyle: .themed(appTheme),
                valueColor: appTheme.palette.secondaryText,
                emptyCardStyle: .themed(appTheme),
                emptyContentStyle: .themed(appTheme),
                actionTitle: "主要操作",
                actionTone: .primary
            )
        case .vocab:
            previewShellCard(
                cardStyle: .vocab(appSkin),
                tabStyle: .vocab(appSkin),
                searchStyle: .vocab(appSkin),
                keyValueStyle: .vocab(appSkin),
                toolbarStyle: .vocab(appSkin),
                valueColor: appSkin.palette.secondaryText,
                emptyCardStyle: .vocab(appSkin),
                emptyContentStyle: .vocab(appSkin),
                actionTitle: "開始複習",
                actionTone: .neutral
            )
        case .settings:
            previewSettingsCard
        }
    }

    private func previewShellCard(
        cardStyle: AppSectionCardStyle,
        tabStyle: AppTabSelectorStyle,
        searchStyle: AppSearchFieldStyle,
        keyValueStyle: AppKeyValueRowStyle,
        toolbarStyle: AppToolbarGlyphStyle,
        valueColor: Color,
        emptyCardStyle: AppSectionCardStyle,
        emptyContentStyle: AppEmptyStateStyle,
        actionTitle: String,
        actionTone: AppActionTone
    ) -> some View {
        VStack(alignment: .leading, spacing: AppShellMetrics.sectionSpacing) {
            AppSectionCard(style: cardStyle) {
                VStack(alignment: .leading, spacing: AppSpacing.s4) {
                    AppTabSelector(
                        options: [
                            .init(id: 0, title: "書庫", count: 12, systemImage: "books.vertical"),
                            .init(id: 1, title: "單字本", count: 248, systemImage: "character.book.closed"),
                            .init(id: 2, title: "設定", systemImage: "gearshape")
                        ],
                        selection: $selectedTab,
                        style: tabStyle
                    )

                    AppSearchField(
                        text: $searchText,
                        prompt: "搜尋",
                        style: searchStyle
                    )

                    AppKeyValueRow(
                        icon: "server.rack",
                        label: "伺服器",
                        style: keyValueStyle
                    ) {
                        Text("Books & Vocab")
                            .font(AppFonts.monoNumbers(size: 12))
                            .foregroundStyle(valueColor)
                    }
                }
            }

            AppEmptyStateCard(
                title: "尚無內容",
                systemImage: "tray",
                description: "這個 preview 用來保護 shared shell 元件的基本輸出。",
                cardStyle: emptyCardStyle,
                contentStyle: emptyContentStyle
            )

            HStack(spacing: AppSpacing.s3) {
                AppToolbarGlyph(systemImage: "arrow.clockwise", style: toolbarStyle)
                AppToolbarGlyph(systemImage: "tray.full", badge: "7", style: toolbarStyle)
            }

            Button(actionTitle) {}
                .buttonStyle(.appAction(actionTone))
        }
    }

    private var previewSettingsCard: some View {
        VStack(alignment: .leading, spacing: AppShellMetrics.sectionSpacing) {
            AppSectionCard(padding: 0, style: .settings(appSkin)) {
                VStack(spacing: 0) {
                    AppKeyValueRow(
                        icon: "person.circle",
                        label: "帳號",
                        style: .settings(appSkin)
                    ) {
                        Text("reader@example.com")
                            .font(appSkin.typography.caption)
                            .foregroundStyle(appSkin.palette.secondaryText)
                    }

                    Rectangle()
                        .fill(appSkin.palette.divider)
                        .frame(height: AppMetrics.dividerStandard)
                        .padding(.leading, 50)

                    AppKeyValueRow(
                        icon: "server.rack",
                        label: "伺服器",
                        style: .settings(appSkin)
                    ) {
                        Text("Books & Vocab")
                            .font(appSkin.typography.monoLabel)
                            .foregroundStyle(appSkin.palette.secondaryText)
                    }
                }
            }

            Button("登出帳號") {}
                .buttonStyle(.appAction(.destructive))

            AppSectionFooter(
                text: "Settings variant 會保護 shared row 與 card 在無陰影設定皮膚下的輸出。",
                style: .init(
                    font: appSkin.typography.caption,
                    color: appSkin.palette.tertiaryText
                )
            )
        }
    }
}
