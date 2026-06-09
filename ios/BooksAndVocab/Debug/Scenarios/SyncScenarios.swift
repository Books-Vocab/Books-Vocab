#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `SyncPresenter` — the vocabulary sync overlay.
///
/// 故意完全不接 `SyncCoordinator`（其 init 為 @MainActor 且會跑真實 pipeline）。
/// 直接餵合成的 `SyncPresenterState` 覆蓋四個 `SyncPhase` 與 `SyncFailureKind`，
/// 讓 ready / running / completed / failed(.partial) 都有永久視覺基準。
/// `SyncPresenter` 用到 `.navigationTitle` / `.toolbar` / `dismiss`，故每個 scenario
/// 包一層 NavigationStack 提供導覽容器。
enum SyncScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Sync") {
            Scenario("Ready · pending rows", layout: .fill) {
                presenter(state: Self.readyState)
            }
            Scenario("Running · steps in flight", layout: .fill) {
                presenter(state: Self.runningState)
            }
            Scenario("Completed", layout: .fill) {
                presenter(state: Self.completedState)
            }
            Scenario("Failed · partial", layout: .fill) {
                presenter(state: Self.partialFailureState)
            }
            Scenario("Failed · full error", layout: .fill) {
                presenter(state: Self.fullFailureState)
            }
        }
    }

    // MARK: - Presenter wrapper

    private static func presenter(state: SyncPresenterState) -> some View {
        AppThemeContainer {
            NavigationStack {
                SyncPresenter(
                    state: state,
                    onPrimaryAction: {},
                    onCancel: {},
                    onShowSettings: {},
                    onPendingRowTapped: { _ in },
                    onPendingActionTapped: { _ in }
                )
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    // MARK: - States

    private static var readyState: SyncPresenterState {
        SyncPresenterState(
            isLoggedIn: true,
            isConnected: true,
            phase: .ready,
            failureKind: nil,
            pendingCount: 3,
            addCount: 2,
            deleteCount: 1,
            steps: [],
            summaryText: "",
            pendingRows: [
                pendingRow(word: "ineffable", pos: "adj.", translation: "難以言喻的", action: .add),
                pendingRow(word: "ephemeral", pos: "adj.", translation: "短暫的", action: .add),
                pendingRow(word: "obsolete", pos: "adj.", translation: "過時的", action: .delete)
            ]
        )
    }

    private static var runningState: SyncPresenterState {
        SyncPresenterState(
            isLoggedIn: true,
            isConnected: true,
            phase: .running,
            failureKind: nil,
            pendingCount: 3,
            addCount: 2,
            deleteCount: 1,
            steps: [
                step(id: "upload_delete", label: "刪除 Books & Vocab 單字", status: .done, current: 1, total: 1, detail: "已刪除 1 個單字"),
                step(id: "upload_add", label: "上傳新單字", status: .running, current: 1, total: 2),
                step(id: "trigger", label: "觸發背景 AI 處理", status: .waiting),
                step(id: "push_review", label: "上傳複習進度", status: .waiting),
                step(id: "pull", label: "下載單字至本地", status: .waiting)
            ],
            summaryText: ""
        )
    }

    private static var completedState: SyncPresenterState {
        SyncPresenterState(
            isLoggedIn: true,
            isConnected: true,
            phase: .completed,
            failureKind: nil,
            pendingCount: 0,
            addCount: 2,
            deleteCount: 1,
            steps: [
                step(id: "upload_delete", label: "刪除 Books & Vocab 單字", status: .done, current: 1, total: 1, detail: "已刪除 1 個單字"),
                step(id: "upload_add", label: "上傳新單字", status: .done, current: 2, total: 2, detail: "2 新增, 0 已存在"),
                step(id: "trigger", label: "觸發背景 AI 處理", status: .done, detail: "已交由伺服器背景處理"),
                step(id: "push_review", label: "上傳複習進度", status: .done, detail: "已同步 5 筆複習紀錄"),
                step(id: "pull", label: "下載單字至本地", status: .done, current: 1, total: 1, detail: "本地單字已建立完成")
            ],
            summaryText: ""
        )
    }

    private static var partialFailureState: SyncPresenterState {
        SyncPresenterState(
            isLoggedIn: true,
            isConnected: true,
            phase: .failed,
            failureKind: .partial,
            pendingCount: 1,
            addCount: 2,
            deleteCount: 1,
            steps: [
                step(id: "upload_delete", label: "刪除 Books & Vocab 單字", status: .done, current: 1, total: 1, detail: "已刪除 1 個單字"),
                step(id: "upload_add", label: "上傳新單字", status: .error, current: 1, total: 2, detail: "部分上傳失敗（1 筆）"),
                step(id: "trigger", label: "觸發背景 AI 處理", status: .done, detail: "已交由伺服器背景處理"),
                step(id: "push_review", label: "上傳複習進度", status: .done, detail: "已同步 5 筆複習紀錄"),
                step(id: "pull", label: "下載單字至本地", status: .done, current: 1, total: 1, detail: "本地單字已建立完成")
            ],
            summaryText: "部分項目未成功同步，可直接再次重試。"
        )
    }

    private static var fullFailureState: SyncPresenterState {
        SyncPresenterState(
            isLoggedIn: true,
            isConnected: true,
            phase: .failed,
            failureKind: .full,
            pendingCount: 3,
            addCount: 2,
            deleteCount: 1,
            steps: [
                step(id: "upload_delete", label: "刪除 Books & Vocab 單字", status: .running, current: 0, total: 1),
                step(id: "upload_add", label: "上傳新單字", status: .waiting),
                step(id: "trigger", label: "觸發背景 AI 處理", status: .waiting),
                step(id: "push_review", label: "上傳複習進度", status: .waiting),
                step(id: "pull", label: "下載單字至本地", status: .waiting)
            ],
            summaryText: "網路連線中斷，請稍後再試。"
        )
    }

    // MARK: - Fixture helpers

    private enum PendingAction {
        case add
        case delete
    }

    private static func pendingRow(
        word: String,
        pos: String,
        translation: String,
        action: PendingAction
    ) -> SyncPresenterState.RowItem {
        let id = UUID()
        let isDelete = action == .delete
        return SyncPresenterState.RowItem(
            id: id,
            row: WordRow.ViewData(
                id: id,
                word: word,
                wordTone: isDelete ? .destructive : .primary,
                isStrikethrough: isDelete,
                partOfSpeech: pos,
                translation: translation,
                bookTitle: nil,
                chapterTitle: nil,
                difficultyTier: nil,
                reviewProgress: nil,
                leadingSystemImage: nil,
                leadingTone: nil,
                trailingLabel: nil,
                trailingTone: nil,
                statusText: nil,
                statusTone: nil
            ),
            actionSystemImage: isDelete ? "arrow.uturn.backward" : "minus.circle",
            actionTone: isDelete ? .destructive : .secondary,
            actionAccessibilityLabel: isDelete ? "復原刪除" : "移除待收錄"
        )
    }

    private static func step(
        id: String,
        label: String,
        status: PipelineStep.StepStatus,
        current: Int = 0,
        total: Int = 0,
        detail: String = ""
    ) -> PipelineStep {
        PipelineStep(
            id: id,
            label: label,
            status: status,
            current: current,
            total: total,
            detail: detail
        )
    }
}
#endif
