#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the Welcome / onboarding surface.
/// Reuses `WelcomePreviewScene` (defined in `WelcomeView.swift`).
enum WelcomeScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Welcome") {
            Scenario("Step 1 / Capture", layout: .fill) {
                WelcomePreviewScene(initialPage: 0, preferredColorScheme: nil)
            }
            Scenario("Step 2 / Link", layout: .fill) {
                WelcomePreviewScene(initialPage: 1, preferredColorScheme: nil)
            }
            Scenario("Step 3 / Review", layout: .fill) {
                WelcomePreviewScene(initialPage: 2, preferredColorScheme: nil)
            }
            Scenario("Step 3 / Dark", layout: .fill) {
                WelcomePreviewScene(initialPage: 2, preferredColorScheme: .dark)
            }
        }
    }
}
#endif
