#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `AppStartupRecoveryView` — the storage-init failure
/// recovery surface shown when the ModelContainer cannot be built safely.
///
/// The view takes plain value props (`AppStartupFailure` + `AppStartupRecoveryActions`),
/// both with non-isolated initializers, so scenarios render it directly without a
/// @MainActor scene harness. Closures are stubbed; the view shows the `.idle` phase
/// on first render (interactive phases like retrying/exhausted require taps and are
/// not reachable in a static snapshot).
enum AppStartupRecoveryScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Startup Recovery") {
            // Happy path: typical CloudKit schema-mismatch failure, all actions available.
            Scenario("CloudKit Schema Failure", layout: .fill) {
                AppThemeContainer {
                    AppStartupRecoveryView(
                        failure: .storageInitialization(error: NSError(
                            domain: "NSCocoaErrorDomain",
                            code: 134_060,
                            userInfo: [NSLocalizedDescriptionKey:
                                "CloudKit schema validation failed: Notebook.coverPalette missing remote field."]
                        )),
                        actions: .preview
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            // Edge: very long / multi-line technical detail to stress the mono details box.
            Scenario("Long Technical Detail", layout: .fill) {
                AppThemeContainer {
                    AppStartupRecoveryView(
                        failure: .storageInitialization(error: NSError(
                            domain: "SwiftDataError",
                            code: 134_110,
                            userInfo: [NSLocalizedDescriptionKey:
                                "Persistent store migration failed: lightweight migration is not possible because the model "
                                + "hash for entity 'VocabularyEntry' changed (added attribute 'masteryStreak', removed "
                                + "attribute 'legacyScore') and no mapping model was found. Source store URL: "
                                + "file:///var/mobile/Containers/Data/Application/0E1F.../Library/Application%20Support/default.store"]
                        )),
                        actions: .preview
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            // Custom failure with a single recovery step + minimal detail (sparse content).
            Scenario("Minimal Failure", layout: .fill) {
                AppThemeContainer {
                    AppStartupRecoveryView(
                        failure: AppStartupFailure(
                            title: "資料庫暫時無法使用",
                            message: "App 已停止載入主要功能，避免覆寫既有資料。",
                            recoverySteps: ["請重新嘗試啟動。"],
                            technicalDetails: "code=1"
                        ),
                        actions: .preview
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            // Error-affordance variant: all recovery actions fail / unavailable
            // (retry=false, clearCache=false, no mail URL). Static render still shows
            // idle, but exercises the exhausted-path wiring.
            Scenario("All Actions Unavailable", layout: .fill) {
                AppThemeContainer {
                    AppStartupRecoveryView(
                        failure: .storageInitialization(error: NSError(domain: "SwiftDataError", code: 1)),
                        actions: AppStartupRecoveryActions(
                            retry: { false },
                            clearLocalCache: { false },
                            supportMailURL: { _ in nil }
                        )
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }
    }
}
#endif
