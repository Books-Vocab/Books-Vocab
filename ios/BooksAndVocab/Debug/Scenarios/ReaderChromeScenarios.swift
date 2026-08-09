#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the full Reader chrome (`ReaderViewPresenter`), as
/// rendered through `ReaderView.presenterState`. Reuses the internal
/// `ReaderChromePreviewScene` preview seam from `ReaderViewPresenter+Preview.swift`
/// so #Preview and the agent workbench stay aligned.
///
/// Preview harness visibility lifted from `private` → `internal` in:
/// - ReaderViewPresenter+Preview.swift (ReaderChromePreviewScene)
///
/// Note: most scenarios render synthetic block placeholders for page content
/// (no live publication / WKWebView), driving every state purely off
/// `ReaderViewPresenterState`. The "Reading · Prose" scenario is the exception:
/// it renders native SwiftUI book prose (`pageContent: .prose`) so an agent can
/// inspect chrome against realistic content.
enum ReaderChromeScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Reader View · Chrome") {
            Scenario("Loading · Render", layout: .fill) {
                AppThemeContainer {
                    ReaderChromePreviewScene(
                        state: ReaderViewPresenterState(
                            paperColor: AppColors.paperSepiaDeep,
                            isWebViewReady: false,
                            loadingPhase: "渲染頁面…",
                            underlineProgress: 0.42,
                            chrome: ReaderChromeState(header: .compact, overlay: .none),
                            totalProgression: 0.18,
                            bookTitle: "The Left Hand of Darkness"
                        ),
                        showsErrorCard: false
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            Scenario("Loading · Mark Vocab", layout: .fill) {
                AppThemeContainer {
                    ReaderChromePreviewScene(
                        state: ReaderViewPresenterState(
                            paperColor: AppColors.paperSepia,
                            isWebViewReady: false,
                            loadingPhase: "標記生字…",
                            underlineProgress: 0.68,
                            chrome: ReaderChromeState(header: .compact, overlay: .none),
                            totalProgression: 0.18,
                            bookTitle: "The Left Hand of Darkness"
                        ),
                        showsErrorCard: false
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            Scenario("Reading · Compact Header", layout: .fill) {
                AppThemeContainer {
                    ReaderChromePreviewScene(
                        state: ReaderViewPresenterState(
                            paperColor: AppColors.paperSepia,
                            isWebViewReady: true,
                            loadingPhase: "開啟書本…",
                            underlineProgress: nil,
                            chrome: ReaderChromeState(header: .compact, overlay: .none),
                            totalProgression: 0.37,
                            bookTitle: "The Left Hand of Darkness"
                        ),
                        showsErrorCard: false
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            Scenario("Reading · Expanded Header", layout: .fill) {
                AppThemeContainer {
                    ReaderChromePreviewScene(
                        state: ReaderViewPresenterState(
                            paperColor: AppColors.paperSepia,
                            isWebViewReady: true,
                            loadingPhase: "開啟書本…",
                            underlineProgress: nil,
                            chrome: ReaderChromeState(header: .expanded, overlay: .none),
                            totalProgression: 0.81,
                            bookTitle: "The Left Hand of Darkness"
                        ),
                        showsErrorCard: false
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            Scenario("Reading · Translation Overlay", layout: .fill) {
                AppThemeContainer {
                    ReaderChromePreviewScene(
                        state: ReaderViewPresenterState(
                            paperColor: AppColors.paperSepiaDeep,
                            isWebViewReady: true,
                            loadingPhase: "開啟書本…",
                            underlineProgress: nil,
                            chrome: ReaderChromeState(header: .compact, overlay: .translation),
                            totalProgression: 0.37,
                            bookTitle: "The Left Hand of Darkness"
                        ),
                        showsErrorCard: false
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            Scenario("Reading · Prose", layout: .fill) {
                // Force light appearance so the translation card resolves to the
                // light theme's white card. In the shipped reader the sepia paper
                // is coupled to the light skin; capturing this scene in a dark sim
                // otherwise renders a dark card over sepia paper — a combination
                // that never occurs in the real app. `AppThemeContainer` derives
                // its theme from `colorScheme`, so the injected `.light` wins.
                AppThemeContainer {
                    ReaderChromePreviewScene(
                        state: ReaderViewPresenterState(
                            paperColor: AppColors.paperSepiaDeep,
                            isWebViewReady: true,
                            loadingPhase: "開啟書本…",
                            underlineProgress: nil,
                            chrome: ReaderChromeState(header: .compact, overlay: .translation),
                            totalProgression: 0.37,
                            bookTitle: "The Left Hand of Darkness"
                        ),
                        showsErrorCard: false,
                        pageContent: .prose
                    )
                }
                .environment(\.colorScheme, .light)
                .environmentObject(AppAppearanceStore.preview)
            }

            Scenario("Error · Open Failed", layout: .fill) {
                AppThemeContainer {
                    ReaderChromePreviewScene(
                        state: ReaderViewPresenterState(
                            paperColor: AppColors.paperSepiaDeep,
                            isWebViewReady: true,
                            loadingPhase: "開啟書本…",
                            underlineProgress: nil,
                            chrome: ReaderChromeState(header: .compact, overlay: .none),
                            totalProgression: 0,
                            bookTitle: "The Left Hand of Darkness"
                        ),
                        showsErrorCard: true
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }
    }
}
#endif
