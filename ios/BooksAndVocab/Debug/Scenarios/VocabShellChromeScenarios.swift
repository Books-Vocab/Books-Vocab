#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the leaf chrome components in `VocabShellComponents.swift`
/// + `VocabShellComponents+Actions.swift` that lacked snapshot coverage:
/// `VocabSearchField` / `VocabToolbarGlyph` / `VocabChromeIconButton` /
/// `VocabSectionHeader` / `VocabSliderRow` / `VocabAccessoryIconButton` /
/// `VocabInlineActionButton`.
///
/// 為什麼補:這些是 vocabulary chrome 的最小可復用單位(搜尋欄、工具列字符、
/// section header、slider 列)，web 對拍需要逐顆元件的 token 基準(字級、邊框、
/// badge、capsule、chrome surface 32pt)。所有元件純 `@Environment(\.appSkin)`，
/// binding-backed 者(SearchField / SliderRow)用 `@State` scene 承載讓互動態渲染。
///
/// layout 約定:pill/chip/字符 → `.compressed`(貼合 intrinsic)；
/// 滿寬列(SearchField / SectionHeader / SliderRow) → `.fillH`。
enum VocabShellChromeScenarios {
    static func register(in playbook: Playbook) {
        // MARK: Search Field (full-width → .fillH)
        playbook.addScenarios(of: "Vocab Shell · Search Field") {
            Scenario("Empty · prompt visible", layout: .fillH) {
                VocabSearchFieldScene(initial: "")
            }
            Scenario("With query", layout: .fillH) {
                VocabSearchFieldScene(initial: "serendipity")
            }
        }

        // MARK: Toolbar Glyph (compact → .compressed)
        playbook.addScenarios(of: "Vocab Shell · Toolbar Glyph") {
            Scenario("Plain", layout: .compressed) {
                wrapCompact { VocabToolbarGlyph(systemImage: "arrow.triangle.2.circlepath") }
            }
            Scenario("With badge", layout: .compressed) {
                wrapCompact { VocabToolbarGlyph(systemImage: "arrow.triangle.2.circlepath", badge: "5") }
            }
            Scenario("Badge stress (99+)", layout: .compressed) {
                wrapCompact { VocabToolbarGlyph(systemImage: "arrow.triangle.2.circlepath", badge: "99+") }
            }
        }

        // MARK: Chrome Icon Button (32pt surface, compact → .compressed)
        playbook.addScenarios(of: "Vocab Shell · Chrome Icon Button") {
            Scenario("Close", layout: .compressed) {
                wrapCompact { VocabChromeIconButton(systemImage: "xmark", action: {}) }
            }
            Scenario("Toned (filter)", layout: .compressed) {
                wrapCompact { VocabChromeIconButton(systemImage: "line.3.horizontal.decrease", tone: .accentColor, action: {}) }
            }
        }

        // MARK: Section Header (full-width label row → .fillH)
        playbook.addScenarios(of: "Vocab Shell · Section Header") {
            Scenario("Title only", layout: .fillH) {
                wrapWide { VocabSectionHeader(title: "已收錄") }
            }
            Scenario("Icon + trailing count", layout: .fillH) {
                wrapWide { VocabSectionHeader(title: "待複習", systemImage: "clock.badge", trailingText: "5") }
            }
        }

        // MARK: Slider Row (full-width interactive → .fillH)
        playbook.addScenarios(of: "Vocab Shell · Slider Row") {
            Scenario("Interactive", layout: .fillH) {
                VocabSliderRowScene(initial: 0.6)
            }
        }

        // MARK: Accessory Icon Button (compact → .compressed)
        playbook.addScenarios(of: "Vocab Shell · Accessory Icon Button") {
            Scenario("Default fill", layout: .compressed) {
                wrapCompact {
                    VocabAccessoryIconButton(
                        systemImage: "trash",
                        tone: .red,
                        accessibilityLabel: "刪除",
                        action: {}
                    )
                }
            }
        }

        // MARK: Inline Action Button (compact text button → .compressed)
        playbook.addScenarios(of: "Vocab Shell · Inline Action Button") {
            Scenario("Accent default", layout: .compressed) {
                wrapCompact { VocabInlineActionButton(title: "全部選取", action: {}) }
            }
            Scenario("Toned", layout: .compressed) {
                wrapCompact { VocabInlineActionButton(title: "取消", tone: .secondary, action: {}) }
            }
        }
    }

    // MARK: - Layout helpers
    // 第一性原理:PNG = contentView.bounds。building block 不是一支手機。
    // .compressed → 貼合 intrinsic(pill/字符/inline button)；
    // .fillH → 滿寬貼合高(SectionHeader / Slider 列)。

    /// 緊湊元件:畫布貼合 intrinsic 尺寸。搭 `layout: .compressed`。
    @ViewBuilder
    private static func wrapCompact<Content: View>(@ViewBuilder _ content: @escaping () -> Content) -> some View {
        AppThemeContainer {
            content()
                .padding(24)
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    /// 滿寬元件:撐滿寬度、貼合高度。搭 `layout: .fillH`。
    @ViewBuilder
    private static func wrapWide<Content: View>(@ViewBuilder _ content: @escaping () -> Content) -> some View {
        AppThemeContainer {
            content()
                .frame(maxWidth: .infinity)
                .padding(24)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

// MARK: - Binding-backed scene harnesses

private struct VocabSearchFieldScene: View {
    @State private var text: String

    init(initial: String) {
        self._text = State(initialValue: initial)
    }

    var body: some View {
        AppThemeContainer {
            VocabSearchField(text: $text, prompt: "搜尋單字")
                .frame(maxWidth: .infinity)
                .padding(24)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

private struct VocabSliderRowScene: View {
    @State private var value: Double

    init(initial: Double) {
        self._value = State(initialValue: initial)
    }

    var body: some View {
        AppThemeContainer {
            VocabSliderRow(
                label: "間隔",
                value: $value,
                range: 0...1,
                format: "%.1f"
            )
            .frame(maxWidth: .infinity)
            .padding(24)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
