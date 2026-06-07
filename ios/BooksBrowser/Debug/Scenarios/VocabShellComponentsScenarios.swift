#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the leaf chrome components in
/// `VocabShellComponents.swift` + `VocabShellComponents+Actions.swift`.
/// All components are pure @Environment(\.appSkin) / @Binding views — no
/// @MainActor init traps — but binding-backed components are hosted in
/// @State scene structs so Slider / Menu / Search interactions render live.
enum VocabShellComponentsScenarios {
    static func register(in playbook: Playbook) {
        // MARK: Chrome Icon Button (32pt visual, 44pt touch)
        playbook.addScenarios(of: "Vocab Shell · Chrome Icon Button") {
            Scenario("Default", layout: .fill) {
                wrap {
                    VocabChromeIconButton(systemImage: "xmark", label: "Close") {}
                }
            }
            Scenario("Toned + row", layout: .fill) {
                wrap {
                    HStack(spacing: 12) {
                        VocabChromeIconButton(systemImage: "slider.horizontal.3", label: "Filter") {}
                        VocabChromeIconButton(systemImage: "magnifyingglass", label: "Search") {}
                        VocabChromeIconButton(systemImage: "trash", tone: .red, label: "Delete") {}
                    }
                }
            }
        }

        // MARK: Search Field
        playbook.addScenarios(of: "Vocab Shell · Search Field") {
            Scenario("Empty / prompt", layout: .fill) {
                VocabSearchFieldScene(initialText: "", prompt: "搜尋單字…")
            }
            Scenario("With query", layout: .fill) {
                VocabSearchFieldScene(initialText: "serendipity", prompt: "搜尋單字…")
            }
        }

        // MARK: Toolbar Glyph
        playbook.addScenarios(of: "Vocab Shell · Toolbar Glyph") {
            Scenario("Plain", layout: .fill) {
                wrap {
                    VocabToolbarGlyph(systemImage: "line.3.horizontal.decrease.circle")
                }
            }
            Scenario("Badge + tone", layout: .fill) {
                wrap {
                    HStack(spacing: 24) {
                        VocabToolbarGlyph(systemImage: "bell", badge: "3")
                        VocabToolbarGlyph(systemImage: "flame.fill", badge: "99+", tone: .orange)
                    }
                }
            }
        }

        // MARK: Accessory Icon Button (filled square)
        playbook.addScenarios(of: "Vocab Shell · Accessory Icon Button") {
            Scenario("Default fill", layout: .fill) {
                wrap {
                    VocabAccessoryIconButton(
                        systemImage: "square.and.pencil",
                        tone: .accentColor,
                        accessibilityLabel: "Edit"
                    ) {}
                }
            }
            Scenario("Custom background row", layout: .fill) {
                wrap {
                    HStack(spacing: 12) {
                        VocabAccessoryIconButton(
                            systemImage: "checkmark",
                            tone: .white,
                            background: .green,
                            accessibilityLabel: "Confirm"
                        ) {}
                        VocabAccessoryIconButton(
                            systemImage: "xmark",
                            tone: .white,
                            background: .red,
                            accessibilityLabel: "Cancel"
                        ) {}
                    }
                }
            }
        }

        // MARK: Inline Action Button (text link)
        playbook.addScenarios(of: "Vocab Shell · Inline Action Button") {
            Scenario("Accent + destructive", layout: .fill) {
                wrap {
                    HStack(spacing: 24) {
                        VocabInlineActionButton(title: "全選") {}
                        VocabInlineActionButton(title: "清除", tone: .red) {}
                    }
                }
            }
        }

        // MARK: Metric Hero Card
        playbook.addScenarios(of: "Vocab Shell · Metric Hero Card") {
            Scenario("Single", layout: .fill) {
                wrap {
                    VocabMetricHeroCard(
                        title: "待複習",
                        description: "今天到期的卡片數",
                        value: "42"
                    )
                }
            }
            Scenario("Stacked metrics", layout: .fill) {
                wrap {
                    VStack(spacing: 12) {
                        VocabMetricHeroCard(title: "總單字", description: "詞庫累積總量", value: "1,284")
                        VocabMetricHeroCard(title: "已掌握", description: "連續答對 3 次以上", value: "0")
                        VocabMetricHeroCard(title: "連續天數", description: "目前複習連勝", value: "128")
                    }
                }
            }
        }

        // MARK: Section Header
        playbook.addScenarios(of: "Vocab Shell · Section Header") {
            Scenario("Title only", layout: .fill) {
                wrap {
                    VocabSectionHeader(title: "最近新增")
                }
            }
            Scenario("Icon + trailing count", layout: .fill) {
                wrap {
                    VStack(spacing: 20) {
                        VocabSectionHeader(title: "到期複習", systemImage: "clock.badge", trailingText: "12")
                        VocabSectionHeader(title: "未學詞彙", systemImage: "sparkles", trailingText: "—")
                    }
                }
            }
        }

        // MARK: Slider Row
        playbook.addScenarios(of: "Vocab Shell · Slider Row") {
            Scenario("Single (interactive)", layout: .fill) {
                VocabSliderRowScene()
            }
        }

        // MARK: Sort Pill
        playbook.addScenarios(of: "Vocab Shell · Sort Pill") {
            Scenario("Default (複習優先)", layout: .fill) {
                VocabSortPillScene(initial: .default)
            }
            Scenario("Alphabetical", layout: .fill) {
                VocabSortPillScene(initial: .alphabetical)
            }
            Scenario("Difficulty", layout: .fill) {
                VocabSortPillScene(initial: .difficulty)
            }
        }
    }

    // MARK: - Layout helper (no @MainActor types involved → nonisolated ok)

    @ViewBuilder
    private static func wrap<Content: View>(@ViewBuilder _ content: @escaping () -> Content) -> some View {
        AppThemeContainer {
            content()
                .padding(24)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

// MARK: - Binding-backed scene harnesses

private struct VocabSearchFieldScene: View {
    @State private var text: String
    let prompt: String

    init(initialText: String, prompt: String) {
        self._text = State(initialValue: initialText)
        self.prompt = prompt
    }

    var body: some View {
        AppThemeContainer {
            VocabSearchField(text: $text, prompt: prompt)
                .padding(24)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

private struct VocabSliderRowScene: View {
    @State private var fontSize: Double = 17
    @State private var lineSpacing: Double = 1.4

    var body: some View {
        AppThemeContainer {
            VStack(spacing: 12) {
                VocabSliderRow(
                    label: "字級",
                    value: $fontSize,
                    range: 12...28,
                    format: "%.0f"
                )
                VocabSliderRow(
                    label: "行距",
                    value: $lineSpacing,
                    range: 1.0...2.0,
                    format: "%.1f"
                )
            }
            .padding(24)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

private struct VocabSortPillScene: View {
    @State private var sortOption: KGVocabSortOption

    init(initial: KGVocabSortOption) {
        self._sortOption = State(initialValue: initial)
    }

    var body: some View {
        AppThemeContainer {
            VocabSortPill(sortOption: $sortOption)
                .padding(24)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
