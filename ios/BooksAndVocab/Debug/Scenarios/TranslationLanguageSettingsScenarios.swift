#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `TranslationLanguageSettingsView`.
///
/// The view holds save error / in-flight state in private `@State` that is only
/// reachable via tap interaction, so the catalog covers the statically
/// renderable resting states (selected source/target language pairs). The
/// `onChanged` closure is stubbed; the failure-banner state is driven by
/// internal `@State` after an async commit and cannot be seeded synchronously.
enum TranslationLanguageSettingsScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Translation Language Settings") {
            Scenario("English to Traditional Chinese", layout: .fill) {
                TranslationLanguageSettingsScene(source: .en, target: .zhHant)
            }
            Scenario("Japanese to English", layout: .fill) {
                TranslationLanguageSettingsScene(source: .ja, target: .en)
            }
            Scenario("French to Simplified Chinese", layout: .fill) {
                TranslationLanguageSettingsScene(source: .fr, target: .zhHans)
            }
            Scenario("Korean to Japanese", layout: .fill) {
                TranslationLanguageSettingsScene(source: .ko, target: .ja)
            }
        }
    }
}

// MARK: - Scene harness

private struct TranslationLanguageSettingsScene: View {
    @State private var sourceLang: TranslationLanguage
    @State private var targetLang: TranslationLanguage

    init(source: TranslationLanguage, target: TranslationLanguage) {
        self._sourceLang = State(initialValue: source)
        self._targetLang = State(initialValue: target)
    }

    var body: some View {
        AppThemeContainer {
            NavigationStack {
                TranslationLanguageSettingsView(
                    sourceLang: $sourceLang,
                    targetLang: $targetLang,
                    onChanged: { _, _ in true }
                )
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
