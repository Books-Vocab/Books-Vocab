#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `CollocationExplainSheet`.
///
/// The sheet's `.task` only hits the network when `existingExplanation` is nil.
/// Every scenario here passes a non-nil `existingExplanation`, so the view
/// resolves synchronously to its `.loaded` phase — no `TranslationService`
/// call, deterministic for snapshotting.
enum CollocationExplainScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Collocation Explain") {
            Scenario("Loaded · short", layout: .fill) {
                CollocationExplainScene(
                    collocation: "take into account",
                    context: "You must take into account the cost before deciding.",
                    existingExplanation: "片語動詞，意為「將……納入考量」，常用於正式決策語境。"
                )
            }

            Scenario("Loaded · long", layout: .fill) {
                CollocationExplainScene(
                    collocation: "come to terms with",
                    context: "It took her years to come to terms with the loss.",
                    existingExplanation: """
                    此搭配表示「接受並適應某件難以面對的事實或情況」，\
                    語氣帶有心理層面的調適過程。常見於描述失去、改變或無法逆轉\
                    的處境。例如：to come to terms with one's mortality（接受自己終將一死）。\
                    與單純的 accept 相比，本搭配更強調歷時性的內在和解，而非當下的同意。
                    """
                )
            }

            // existingExplanation == nil would normally show the .delete-less
            // save toolbar, but renders the loaded explanation supplied here;
            // this case verifies the trash button appears (existing != nil).
            Scenario("Loaded · with delete", layout: .fill) {
                CollocationExplainScene(
                    collocation: "on the verge of",
                    context: "The company was on the verge of bankruptcy.",
                    existingExplanation: "意為「瀕臨、即將……」，後接名詞或動名詞，描述某事即將發生的臨界狀態。"
                )
            }
        }
    }
}

// MARK: - Scene harness

private struct CollocationExplainScene: View {
    let collocation: String
    let context: String
    let existingExplanation: String?

    var body: some View {
        AppThemeContainer {
            CollocationExplainSheet(
                collocation: collocation,
                context: context,
                existingExplanation: existingExplanation,
                onSave: { _ in },
                onDelete: {}
            )
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
