#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the macCatalyst keyboard-shortcut hint primitives
/// defined in `TodayReviewPresenter+Toolbar.swift`:
/// - `ShortcutKeyCap` — a single mono key cap (e.g. `␣`, `1`, `←`).
/// - `ShortcutHintChip` — a key cap + label capsule, primary / secondary styling.
///
/// Both are pure value views (take `String` / `TodayReviewShortcutHint`,
/// no `@MainActor` construction), so scenarios build them inline without a Scene
/// struct. They read `appSkin` from the environment via `AppThemeContainer`.
/// These views only exist under `targetEnvironment(macCatalyst)`, so this file
/// is gated the same way.
enum TodayReviewShortcutScenarios {
    /// Manifest surfaces (category + source-declared backing view) — 與 `register`
    /// 的 macCatalyst gating 對稱：非 Catalyst 時為空。每個 category 對應其
    /// production 元件型別，讓 agent 查詢能由源碼真相映射 surface→type。
    static var manifestSurfaces: [(category: String, backing: any View.Type)] {
        #if targetEnvironment(macCatalyst)
        [
            ("Today Review · Shortcut Key Cap", ShortcutKeyCap.self),
            ("Today Review · Shortcut Hint Chip", ShortcutHintChip.self),
        ]
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
                        hint: TodayReviewShortcutHint(
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
                        hint: TodayReviewShortcutHint(
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
                        hint: TodayReviewShortcutHint(
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
                            hint: TodayReviewShortcutHint(
                                id: "space", key: "␣", label: "翻面", isPrimary: true
                            )
                        )
                        ShortcutHintChip(
                            hint: TodayReviewShortcutHint(
                                id: "left", key: "←", label: "忘記", isPrimary: false
                            )
                        )
                        ShortcutHintChip(
                            hint: TodayReviewShortcutHint(
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
