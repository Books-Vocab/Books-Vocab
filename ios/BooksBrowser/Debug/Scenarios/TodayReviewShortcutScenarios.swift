#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the macCatalyst keyboard-shortcut hint primitives
/// defined in `TodayReviewPresenter+Toolbar.swift`:
/// - `ShortcutKeyCap` — a single mono key cap (e.g. `␣`, `1`, `←`).
/// - `ShortcutHintChip` — a key cap + label capsule, primary / secondary styling.
///
/// Both are pure value views (take `String` / `TodayReviewPresenter.ShortcutHint`,
/// no `@MainActor` construction), so scenarios build them inline without a Scene
/// struct. They read `appSkin` from the environment via `AppThemeContainer`.
/// These views only exist under `targetEnvironment(macCatalyst)`, so this file
/// is gated the same way.
enum TodayReviewShortcutScenarios {
    /// Manifest categories — 與 `register` 的 macCatalyst gating 對稱:非 Catalyst
    /// 時為空,避免 `CatalogCoverageTests` 把宣告但未註冊的群組判為缺漏。
    static var manifestCategories: [String] {
        #if targetEnvironment(macCatalyst)
        ["Today Review · Shortcut Key Cap", "Today Review · Shortcut Hint Chip"]
        #else
        []
        #endif
    }

    static func register(in playbook: Playbook) {
        // `ShortcutKeyCap` / `ShortcutHintChip` 僅在 macCatalyst 編譯;非 Catalyst
        // 時 register 為 no-op,讓 manifest entry 可無條件引用本 enum。
        #if targetEnvironment(macCatalyst)
        // MARK: Key Caps
        playbook.addScenarios(of: "Today Review · Shortcut Key Cap") {
            Scenario("Space", layout: .compressed) {
                AppThemeContainer {
                    ShortcutKeyCap(key: "␣")
                        .padding(40)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Digit", layout: .compressed) {
                AppThemeContainer {
                    ShortcutKeyCap(key: "1")
                        .padding(40)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Arrow row", layout: .compressed) {
                AppThemeContainer {
                    HStack(spacing: 8) {
                        ShortcutKeyCap(key: "←")
                        ShortcutKeyCap(key: "→")
                        ShortcutKeyCap(key: "↑")
                        ShortcutKeyCap(key: "↓")
                    }
                    .padding(40)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }

        // MARK: Hint Chips
        playbook.addScenarios(of: "Today Review · Shortcut Hint Chip") {
            Scenario("Primary", layout: .compressed) {
                AppThemeContainer {
                    ShortcutHintChip(
                        hint: TodayReviewPresenter.ShortcutHint(
                            id: "space",
                            key: "␣",
                            label: "翻面",
                            isPrimary: true
                        )
                    )
                    .padding(40)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Secondary", layout: .compressed) {
                AppThemeContainer {
                    ShortcutHintChip(
                        hint: TodayReviewPresenter.ShortcutHint(
                            id: "shuffle",
                            key: "S",
                            label: "洗牌",
                            isPrimary: false
                        )
                    )
                    .padding(40)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Long label", layout: .compressed) {
                AppThemeContainer {
                    ShortcutHintChip(
                        hint: TodayReviewPresenter.ShortcutHint(
                            id: "remembered",
                            key: "→",
                            label: "標記為已記住並前往下一張",
                            isPrimary: true
                        )
                    )
                    .padding(40)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Row", layout: .compressed) {
                AppThemeContainer {
                    HStack(spacing: 12) {
                        ShortcutHintChip(
                            hint: TodayReviewPresenter.ShortcutHint(
                                id: "space", key: "␣", label: "翻面", isPrimary: true
                            )
                        )
                        ShortcutHintChip(
                            hint: TodayReviewPresenter.ShortcutHint(
                                id: "left", key: "←", label: "忘記", isPrimary: false
                            )
                        )
                        ShortcutHintChip(
                            hint: TodayReviewPresenter.ShortcutHint(
                                id: "right", key: "→", label: "記住", isPrimary: false
                            )
                        )
                    }
                    .padding(40)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }
        #endif
    }
}
#endif