#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `VocabSceneShell` — the unified four-state container
/// every vocabulary scene routes through (`loading` / `loadingSkeleton` /
/// `empty` / `error` / `content`).
///
/// 為什麼補這條:之前只有 inline `#Preview`，不進 snapshot。Vocabulary surface 的
/// 非 content 狀態(載入中、骨架、空、錯誤)是 web 對拍最容易漂移的視覺面 —
/// canvas background + 居中卡片 + 骨架列高度都是 token 驅動。把四態固化成
/// snapshot 才有對拍基準。
///
/// shell 是純 `@Environment(\.appSkin)` view、無 `@MainActor` init trap，
/// 故直接 wrap，不需 model container / auth seam。`content` 態 pass-through
/// 也覆蓋，確認殼本身不污染 content。
enum VocabSceneShellScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Vocab Scene Shell") {
            Scenario("Loading · centered spinner", layout: .fill) {
                VocabSceneShellScene(phase: .loading(
                    title: "載入單字中…",
                    systemImage: "arrow.clockwise"
                ))
            }
            Scenario("Loading skeleton · 6 rows", layout: .fill) {
                VocabSceneShellScene(phase: .loadingSkeleton(rowCount: 6))
            }
            Scenario("Empty · with CTA", layout: .fill) {
                VocabSceneShellScene(phase: .empty(
                    title: "尚無已收錄單字",
                    systemImage: "sparkles",
                    description: "同步完成後，這裡會顯示你的雲端單字。",
                    action: AppEmptyStateAction(
                        title: "前往閱讀",
                        systemImage: "book",
                        handler: {}
                    )
                ))
            }
            Scenario("Empty · no action", layout: .fill) {
                VocabSceneShellScene(phase: .empty(
                    title: "沒有符合的單字",
                    systemImage: "magnifyingglass",
                    description: "換個關鍵字或篩選條件試試。"
                ))
            }
            Scenario("Error · retry", layout: .fill) {
                VocabSceneShellScene(phase: .error(
                    title: "無法載入單字",
                    systemImage: "exclamationmark.triangle",
                    description: "請檢查網路連線後重試。",
                    retryAction: {}
                ))
            }
            Scenario("Content · pass-through", layout: .fill) {
                VocabSceneShellScene(phase: .content)
            }
        }
    }
}

// MARK: - Scene harness

/// `VocabSceneShell` 的 `content` builder 在 `.content` 態才渲染。為了讓
/// pass-through 場景有可視內容、其餘狀態確認殼覆蓋 content，content 固定餵一張
/// 範例卡片。
private struct VocabSceneShellScene: View {
    let phase: VocabScenePhase

    var body: some View {
        AppThemeContainer {
            VocabSceneShell(phase: phase) {
                VStack(alignment: .leading, spacing: AppSpacing.s2) {
                    Text("serendipity")
                        .font(.title2.weight(.semibold))
                    Text("機緣巧合 · n.")
                        .foregroundStyle(.secondary)
                    Text("The fortunate happenstance of finding something good without looking for it.")
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding()
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
