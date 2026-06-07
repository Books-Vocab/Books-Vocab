#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `SettingsSocialBadge` — the small circular social-provider
/// badge (Google "G" on a card-background disc with elevation, Apple logo on a
/// black disc) shown in the account section's linked-provider summary.
///
/// The badge reads only `@Environment(\.appSkin)` and a pure `SettingsSocialKind`
/// enum value, so each scenario can construct it directly inside the Scenario
/// closure without a `@MainActor` scene harness.
enum SettingsSocialBadgeScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Settings · Social Badge") {
            Scenario("Google", layout: .compressed) {
                AppThemeContainer {
                    SettingsSocialBadge(kind: .google)
                        .padding()
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Apple", layout: .compressed) {
                AppThemeContainer {
                    SettingsSocialBadge(kind: .apple)
                        .padding()
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Both", layout: .compressed) {
                AppThemeContainer {
                    HStack(spacing: 16) {
                        SettingsSocialBadge(kind: .google)
                        SettingsSocialBadge(kind: .apple)
                    }
                    .padding()
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }
    }
}
#endif