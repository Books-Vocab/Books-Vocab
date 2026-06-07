#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the full `KnowledgeGraphView` surface (知識圖譜).
///
/// `KnowledgeGraphView(allEntries:)` takes its vocab as a plain array (no
/// `@Query`) and loads graph links in `.task { coordinator.loadGraphData(...) }`.
/// That coordinator method opens with `guard authManager.isLoggedIn else
/// { return }`, so on the env-default (logged-out) `AuthManager.shared` it
/// no-ops to the empty / sign-in graph surface — no WKWebView force-graph render,
/// no network — which is the deterministic catalog rendering. Env-default
/// services (`KGService`, detail router, review settings store) resolve in the
/// `@MainActor` body.
enum KnowledgeGraphViewScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Knowledge Graph View") {
            Scenario("Logged out · empty graph", layout: .fill) {
                KnowledgeGraphViewScene()
            }
        }
    }
}

// MARK: - Scene harness

private struct KnowledgeGraphViewScene: View {
    var body: some View {
        AppThemeContainer {
            KnowledgeGraphView(allEntries: [])
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
