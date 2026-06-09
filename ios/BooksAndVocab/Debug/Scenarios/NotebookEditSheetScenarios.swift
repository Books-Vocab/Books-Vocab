#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `NotebookEditSheet` — the create / edit single
/// vocab-notebook sheet.
///
/// 不接 SwiftData / Presenter：sheet 完全由傳入的 `Mode` 與 `onSave`
/// closure 驅動，狀態全在 `@State`，故可直接渲染。
///
/// 涵蓋：新建空白、編輯既有（含顏色 + 圖案）、長名稱壓力、空名稱
/// （儲存按鈕應 disabled）等視覺基準。
enum NotebookEditSheetScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Notebook Edit") {
            Scenario("Create · blank", layout: .fill) {
                AppThemeContainer {
                    NotebookEditSheet(mode: .create, onSave: { _ in })
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            Scenario("Edit · color + pattern", layout: .fill) {
                AppThemeContainer {
                    NotebookEditSheet(
                        mode: .edit(
                            name: "GRE 高頻字",
                            color: "#AFC2D3",
                            coverPattern: NotebookCoverPattern.allCases.first?.rawValue,
                            coverImagePath: nil
                        ),
                        onSave: { _ in }
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            Scenario("Edit · color only", layout: .fill) {
                AppThemeContainer {
                    NotebookEditSheet(
                        mode: .edit(
                            name: "雅思核心詞彙",
                            color: "#DCABA4",
                            coverPattern: nil,
                            coverImagePath: nil
                        ),
                        onSave: { _ in }
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            Scenario("Edit · long name", layout: .fill) {
                AppThemeContainer {
                    NotebookEditSheet(
                        mode: .edit(
                            name: "莎士比亞十四行詩裡那些古英文罕用字與華麗修辭專用詞庫",
                            color: "#C5B2D0",
                            coverPattern: nil,
                            coverImagePath: nil
                        ),
                        onSave: { _ in }
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            Scenario("Edit · empty name (save disabled)", layout: .fill) {
                AppThemeContainer {
                    NotebookEditSheet(
                        mode: .edit(
                            name: "",
                            color: "#B1C5AE",
                            coverPattern: nil,
                            coverImagePath: nil
                        ),
                        onSave: { _ in }
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }
    }
}
#endif
