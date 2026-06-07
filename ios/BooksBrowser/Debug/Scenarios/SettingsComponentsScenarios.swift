#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the Settings leaf presentational components defined in
/// `SettingsPresenter+Components.swift`. All components are pure SwiftUI structs
/// reading `@Environment(\.appSkin)`, which `AppThemeContainer` injects. They have
/// no @MainActor-isolated initializers, so each Scenario constructs them directly.
/// Backgrounds use the themed surface so capsule/indicator tones read correctly.
enum SettingsComponentsScenarios {
    static func register(in playbook: Playbook) {
        // MARK: Section Header
        playbook.addScenarios(of: "Settings Components · Section Header") {
            Scenario("Account", layout: .fill) {
                row { SettingsSectionHeader(title: "帳戶", icon: "person.crop.circle") }
            }
            Scenario("Long Title", layout: .fill) {
                row {
                    SettingsSectionHeader(
                        title: "同步與資料備份偏好設定總覽",
                        icon: "arrow.triangle.2.circlepath"
                    )
                }
            }
        }

        // MARK: Section Footer
        playbook.addScenarios(of: "Settings Components · Section Footer") {
            Scenario("Short", layout: .fill) {
                row { SettingsSectionFooter("變更後會立即套用。") }
            }
            Scenario("Multiline", layout: .fill) {
                row {
                    SettingsSectionFooter(
                        "登出後本機詞庫仍會保留，但雲端同步將暫停，直到你重新登入帳戶為止。"
                    )
                }
            }
        }

        // MARK: Status Badge
        playbook.addScenarios(of: "Settings Components · Status Badge") {
            Scenario("Tone Variants", layout: .fill) {
                column { skin in
                    SettingsStatusBadge(text: "ACTIVE", tone: skin.palette.success)
                    SettingsStatusBadge(text: "PENDING", tone: skin.palette.warning)
                    SettingsStatusBadge(text: "FAILED", tone: skin.palette.destructive)
                    SettingsStatusBadge(text: "PRO", tone: skin.palette.accent)
                }
            }
        }

        // MARK: Status Value
        playbook.addScenarios(of: "Settings Components · Status Value") {
            Scenario("Single Line", layout: .fill) {
                row { skin in
                    SettingsStatusValue(text: "已同步", color: skin.palette.success)
                }
            }
            Scenario("Wrapping", layout: .fill) {
                row { skin in
                    SettingsStatusValue(
                        text: "上次同步失敗，請檢查網路連線後再試一次",
                        color: skin.palette.destructive,
                        lineLimit: nil,
                        alignment: .leading
                    )
                }
            }
        }

        // MARK: Status Summary
        playbook.addScenarios(of: "Settings Components · Status Summary") {
            Scenario("With Indicator", layout: .fill) {
                column { skin in
                    SettingsStatusSummaryValue(text: "線上", color: skin.palette.success)
                    SettingsStatusSummaryValue(text: "離線", color: skin.palette.warning)
                    SettingsStatusSummaryValue(
                        text: "未連線",
                        color: skin.palette.destructive
                    )
                }
            }
            Scenario("No Indicator", layout: .fill) {
                row { skin in
                    SettingsStatusSummaryValue(
                        text: "v1.6.0 (482)",
                        color: skin.palette.secondaryText,
                        showsIndicator: false
                    )
                }
            }
        }

        // MARK: Disclosure Value
        playbook.addScenarios(of: "Settings Components · Disclosure Value") {
            Scenario("Default", layout: .fill) {
                row { SettingsDisclosureValue(text: "繁體中文") }
            }
        }

        // MARK: Menu Value
        playbook.addScenarios(of: "Settings Components · Menu Value") {
            Scenario("Default", layout: .fill) {
                row { SettingsMenuValue(text: "自動") }
            }
        }

        // MARK: Title Subtitle Stack
        playbook.addScenarios(of: "Settings Components · Title Subtitle") {
            Scenario("With Subtitle", layout: .fill) {
                row { skin in
                    SettingsTitleSubtitleStack(
                        title: "雲端同步",
                        subtitle: "上次同步：今天 14:32",
                        titleFont: skin.typography.body,
                        titleColor: skin.palette.primaryText,
                        subtitleColor: skin.palette.secondaryText
                    )
                }
            }
            Scenario("Title Only", layout: .fill) {
                row { skin in
                    SettingsTitleSubtitleStack(
                        title: "關於本 App",
                        titleFont: skin.typography.body,
                        titleColor: skin.palette.primaryText,
                        subtitleColor: skin.palette.secondaryText
                    )
                }
            }
            Scenario("Multiline Subtitle", layout: .fill) {
                row { skin in
                    SettingsTitleSubtitleStack(
                        title: "資料匯出",
                        subtitle: "將所有詞庫與筆記匯出成 CSV 檔，並透過分享面板儲存到任意位置",
                        titleFont: skin.typography.body,
                        titleColor: skin.palette.primaryText,
                        subtitleColor: skin.palette.secondaryText,
                        subtitleLineLimit: 2
                    )
                }
            }
        }

        // MARK: Trailing Chevron Icon
        playbook.addScenarios(of: "Settings Components · Chevron Icon") {
            Scenario("Default", layout: .fill) {
                row { SettingsTrailingChevronIcon() }
            }
        }
    }

    // MARK: - Layout helpers

    /// Wraps content in a single padded surface row for an isolated component view.
    private static func row<Content: View>(
        @ViewBuilder _ content: @escaping () -> Content
    ) -> some View {
        AppThemeContainer {
            content()
                .padding()
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    /// Skin-aware variant: hands the resolved AppSkin into the builder so scenarios
    /// can pick semantic palette tones.
    private static func row<Content: View>(
        @ViewBuilder _ content: @escaping (AppSkin) -> Content
    ) -> some View {
        AppThemeContainer {
            SettingsComponentSkinReader { skin in
                content(skin)
                    .padding()
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    /// Vertical stack of multiple component instances (skin-aware).
    private static func column<Content: View>(
        @ViewBuilder _ content: @escaping (AppSkin) -> Content
    ) -> some View {
        AppThemeContainer {
            SettingsComponentSkinReader { skin in
                VStack(alignment: .leading, spacing: 16) {
                    content(skin)
                }
                .padding()
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

// MARK: - Skin reader

/// Reads the injected AppSkin from the environment so scenario builders can choose
/// semantic palette tones without reaching into theme internals.
private struct SettingsComponentSkinReader<Content: View>: View {
    @Environment(\.appSkin) private var appSkin
    @ViewBuilder let content: (AppSkin) -> Content

    var body: some View {
        content(appSkin)
    }
}
#endif
