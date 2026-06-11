#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the Reader surface.
/// Reuses internal preview harnesses so Preview / Catalog / Snapshot stay aligned.
///
/// Preview harness visibility lifted from `private` → `internal` in:
/// - TranslationPanel.swift
/// - TOCView.swift
/// - ReaderSettingsPanel.swift
enum ReaderScenarios {
    static func register(in playbook: Playbook) {
        // MARK: Translation Panel
        playbook.addScenarios(of: "Reader · Translation") {
            Scenario("Expanded", layout: .fill) {
                AppThemeContainer {
                    TranslationPanelPreviewScene(isExpanded: true, isExplanationOnly: false)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Collapsed", layout: .fill) {
                AppThemeContainer {
                    TranslationPanelPreviewScene(isExpanded: false, isExplanationOnly: false)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Error", layout: .fill) {
                AppThemeContainer {
                    TranslationPanelPreviewScene(
                        isExpanded: false,
                        isExplanationOnly: false,
                        translation: nil,
                        translationErrorMessage: "翻譯服務逾時，請稍後再試。"
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Loading", layout: .fill) {
                AppThemeContainer {
                    TranslationPanelPreviewScene(
                        isExpanded: false,
                        isExplanationOnly: false,
                        translation: nil,
                        isLoading: true
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Explain Only", layout: .fill) {
                AppThemeContainer {
                    TranslationPanelPreviewScene(isExpanded: true, isExplanationOnly: true)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Explanation Error", layout: .fill) {
                AppThemeContainer {
                    // explanation:"" suppresses the harness fallback so this
                    // scenario isolates the error overlay (nil would coalesce
                    // to the default explanation text and muddy the state).
                    TranslationPanelPreviewScene(
                        isExpanded: true,
                        isExplanationOnly: false,
                        explanation: "",
                        explanationErrorMessage: "語境分析暫時不可用。"
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }

        // MARK: TOC
        playbook.addScenarios(of: "Reader · TOC") {
            Scenario("Loading", layout: .fill) {
                AppThemeContainer {
                    TOCViewPreviewScene(loadState: .loading, tocTitles: [])
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Loaded", layout: .fill) {
                AppThemeContainer {
                    TOCViewPreviewScene(
                        loadState: .loaded,
                        tocTitles: ["第一章", "第二章", "第三章", "第四章", "第五章"]
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Empty", layout: .fill) {
                AppThemeContainer {
                    TOCViewPreviewScene(loadState: .empty, tocTitles: [])
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Failed", layout: .fill) {
                AppThemeContainer {
                    TOCViewPreviewScene(
                        loadState: .failed("Publication manifest 解析失敗。"),
                        tocTitles: []
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }

        // MARK: Settings Panel
        playbook.addScenarios(of: "Reader · Settings") {
            Scenario("Normal", layout: .fill) {
                AppThemeContainer {
                    ReaderSettingsPanelPreviewHarness(
                        initialFontSizeText: "1.0x",
                        canDecreaseFontSize: true,
                        canIncreaseFontSize: true
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Bounds (min)", layout: .fill) {
                AppThemeContainer {
                    ReaderSettingsPanelPreviewHarness(
                        initialFontSizeText: "0.75x",
                        canDecreaseFontSize: false,
                        canIncreaseFontSize: true
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Bounds (max)", layout: .fill) {
                AppThemeContainer {
                    ReaderSettingsPanelPreviewHarness(
                        initialFontSizeText: "2.0x",
                        canDecreaseFontSize: true,
                        canIncreaseFontSize: false
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }
    }
}
#endif
